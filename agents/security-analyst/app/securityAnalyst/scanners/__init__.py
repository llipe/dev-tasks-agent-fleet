"""
Scanner subpackage (spec S8.5) — one module per tool (`semgrep_runner.py`,
and, from S-129-S-132 onward, `gitleaks_runner.py`, `trivy_runner.py`,
`checkov_runner.py`, `codeql_runner.py`), sharing the common
`ScanStatus`/`ScanResult` shape defined in `scanners.types`.

Generalizes the sibling agent's (dependency-update) `validator.py`
`CheckStatus`/multi-check-runner pattern to five independent scanner
subprocess calls, each with its own timeout envelope and non-fatal
crash/timeout/unparseable-output handling (PRD requirements 15-19).

``run_scanners()`` (story S-135) is this package's dispatcher, added here
(rather than a new module) because it is exactly the aggregation point this
module's own docstring already describes -- the one place all five
`run_<tool>()` call sites converge. It is a thin, sequential loop (PRD §11 /
OQ6 -- v1 deliberately does not parallelize scanners, to keep the AgentCore
container's resource envelope predictable), not a thread pool.

**S-141 real-invocation finding -- `file_path` normalization lives here.**
Spec §8.1's `Finding.file_path` contract is "repo-relative, normalized
separators", and every hand-authored test fixture honors it. The real
binaries do not agree with each other: Semgrep and Gitleaks, invoked with
the absolute workspace path this pipeline passes them, echo that absolute
path back (`/tmp/security-analyst-<repo>-<rand>/src/x.ts`), while Trivy,
Checkov, and CodeQL report paths relative to the scan root. Confirmed
against a real `audit_only` run, whose persisted `audit_report` artifact
carried the ephemeral `/tmp/...` workspace prefix. Two consequences beyond
cosmetics: `fingerprint()`/`dedupe()` key on `file_path`, so a Semgrep and a
CodeQL finding on the same line of the same file would never dedupe across
tools; and the temp-directory path would leak into PR bodies (S-139).
Rather than fix five runners five ways, `run_scanners()` relativizes every
returned finding's `file_path` against `workspace` at this single choke
point (`_normalize_findings()`), so the contract holds regardless of how
any individual tool formats its output. Paths that are absolute but *not*
under the workspace (Trivy `image` mode's target is an image reference, for
example) are left untouched.

**S-141 real-invocation finding (task 17.11) -- `cwe_or_category` is
canonicalized here too.** `dedupe()` groups on the exact
`(file_path, cwe_or_category)` string, and the real binaries spell the same
CWE differently: CodeQL's SARIF tags are zero-padded (`external/cwe/cwe-079`
-> `CWE-079`) while Semgrep's `metadata.cwe` and Trivy's `CweIDs` are not
(`CWE-79`). On the first real `fix` run, CodeQL's `js/reflected-xss` and
Semgrep's `raw-html-format` flagged the same line of the same file and were
reported twice -- exactly the cross-tool merge PRD requirement 22 exists
for. `canonicalize_category()` rewrites any `CWE-<n>` (case-insensitive,
leading zeros stripped) to `CWE-<int>`; anything that is not a CWE id (an
OWASP category, a rule id fallback) is left untouched.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path, PurePosixPath

from normalize import Finding
from scanners.checkov_runner import run_checkov
from scanners.codeql_runner import run_codeql
from scanners.gitleaks_runner import run_gitleaks
from scanners.semgrep_runner import run_semgrep
from scanners.trivy_runner import run_trivy
from scanners.types import ScanResult, ScanStatus

__all__ = [
    "AllScannersFailedError",
    "canonicalize_category",
    "relativize_path",
    "run_scanners",
    "run_semgrep",
    "run_gitleaks",
    "run_trivy",
    "run_checkov",
    "run_codeql",
]

_SCANNER_DISPATCH = {
    "semgrep": run_semgrep,
    "gitleaks": run_gitleaks,
    "trivy": run_trivy,
    "checkov": run_checkov,
    "codeql": run_codeql,
}


class AllScannersFailedError(Exception):
    """Raised when every requested scanner failed (PRD requirement 18).

    Carries the full list of :class:`~scanners.types.ScanResult` (all
    ``FAILED``) so the caller can surface each tool's own ``reason`` in the
    ``ALL_SCANNERS_FAILED`` error message/log, not just a bare exception.
    """

    def __init__(self, results: list[ScanResult]) -> None:
        self.results = results
        reasons = ", ".join(f"{r.tool}: {r.reason}" for r in results)
        super().__init__(f"All {len(results)} requested scanners failed ({reasons})")


def relativize_path(file_path: str, workspace: Path) -> str:
    """Return ``file_path`` as a repo-relative POSIX path (spec §8.1).

    An absolute path under ``workspace`` (either as given or after
    ``resolve()``, so a symlinked temp root like macOS's ``/tmp`` ->
    ``/private/tmp`` still matches) becomes relative to it. A relative path
    is returned POSIX-normalized. An empty path, or an absolute path *not*
    under the workspace (Checkov's leading-slash convention is already
    stripped by its own runner, so it never reaches here), is returned
    unchanged -- never raises.
    """
    if not file_path:
        return file_path
    path = Path(file_path)
    if not path.is_absolute():
        return PurePosixPath(file_path).as_posix()
    for root in (workspace, workspace.resolve()):
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            continue
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except (ValueError, OSError):
        return file_path


_CWE_ID = re.compile(r"^cwe-0*(\d+)$", re.IGNORECASE)


def canonicalize_category(value: str) -> str:
    """`CWE-079` / `cwe-79` / `CWE-0079` -> `CWE-79`; anything else unchanged."""
    match = _CWE_ID.match(value.strip())
    return f"CWE-{int(match.group(1))}" if match else value


def _normalize_findings(result: ScanResult, workspace: Path) -> ScanResult:
    if not result.findings:
        return result
    findings: list[Finding] = [
        replace(
            f,
            file_path=relativize_path(f.file_path, workspace),
            cwe_or_category=canonicalize_category(f.cwe_or_category),
        )
        for f in result.findings
    ]
    return replace(result, findings=findings)


def run_scanners(workspace: Path, requested: list[str], timeout: int) -> list[ScanResult]:
    """Run every scanner named in ``requested`` against ``workspace`` (spec §8.5).

    Sequential (v1, PRD §11/OQ6), one ``run_<tool>(workspace, timeout)`` call
    per requested tool, in ``requested``'s own order. Each ``run_<tool>()``
    already isolates its own crash/timeout/unparseable-output handling into a
    non-fatal ``ScanStatus.FAILED`` result (PRD requirement 18) — this
    function's only additional responsibility is the *total*-failure check:
    if literally every requested scanner failed, the whole audit produced no
    usable signal, so it raises :class:`AllScannersFailedError` rather than
    returning a list of all-``FAILED`` results for the caller to notice (or
    not) on its own. A partial failure (one, or even four, of five) is not
    raised here — the caller aggregates whatever ``PASSED`` findings exist
    from the rest (PRD acceptance criterion 24).

    Every returned finding is normalized here (module docstring, S-141):
    ``file_path`` relativized against ``workspace`` (spec §8.1's repo-relative
    contract) and ``cwe_or_category`` canonicalized to ``CWE-<int>`` -- so the
    cross-tool dedup key agrees across all five tools before anything
    downstream (`dedupe()`, the audit artifact, the PR body) sees them.
    """
    results = [
        _normalize_findings(_SCANNER_DISPATCH[name](workspace, timeout), workspace)
        for name in requested
    ]
    if all(r.status == ScanStatus.FAILED for r in results):
        raise AllScannersFailedError(results)
    return results
