"""
Gitleaks scanner integration + secret redaction (spec S8.5, PRD S7.4b/S9.3/
S12, requirement 58 row 2 / D29, R14, story S-129).

Second concrete scanner -- follows `semgrep_runner.py`'s (S-128)
`run_<tool>(workspace, timeout) -> ScanResult` shape verbatim, importing
`ScanResult`/`ScanStatus` from `scanners.types` rather than redefining them.

Deviation from the spec's mermaid-level invocation (S4.3 shows only
``gitleaks --report-format json`` inline, with no literal pseudocode for
this module the way S8.5 gives Semgrep's `_build_command()`): Gitleaks'
real CLI has no ``--json``-to-stdout flag the way Semgrep does -- its
``--report-format`` only controls the *shape* of the file written to
``--report-path``; there is no native "print the report to stdout" mode.

**REVERTED -- S-141 real-invocation finding (PR #239's CodeQL SARIF fix
prompted re-checking this module's identical trick).** This module
originally pointed ``--report-path`` at ``/dev/stdout``, reasoning that a
Linux device file makes writing "to that report path" equivalent to writing
to stdout, keeping `run_gitleaks()`'s shape byte-for-byte identical to
`run_semgrep()`'s subprocess-capture-then-normalize pattern. Confirmed
against the real gitleaks v8.30.1 binary that this loses data silently:
run against a real repo containing two genuine, verified leaks (confirmed
by pointing ``--report-path`` at a real file instead), the exact same
invocation with ``--report-path /dev/stdout`` under Python's
``subprocess.run(..., capture_output=True)`` -- the shape every
`run_<tool>()` in this codebase uses, where the process's own stdout is a
pipe -- produced **zero captured bytes**, not the two real leaks and not
even the ``[]``/``null`` "no leaks" shape a real clean scan produces. This
is a distinct and more severe failure mode than CodeQL's SARIF-corruption
bug (PR #239): CodeQL's data was still present, merely preceded by an
unexpected line; here the data vanished outright, which -- before this
fix -- silently downgraded a findings-bearing run to `ScanStatus.PASSED`
with zero findings (the PR #237 "empty output means no leaks" fix,
written without realizing genuine leaks could also produce empty output
this way, made this silent-loss risk *worse*, not better -- it must not be
reintroduced). `--report-path` now points at a real file inside a
per-call `tempfile.TemporaryDirectory`, read via `Path.read_text()` before
normalization, the same pattern `codeql_runner.py` uses for its own SARIF
output. Flagged per this story's pre-authorized "apply proactively"
instruction (same class of decision as `semgrep_runner.py`'s `RULESET`
fix).

``--no-git`` scans the workspace's current file content only, not commit
history -- the orchestrator's shallow clone (spec S4.3 "clone shallow")
would not reliably contain full history for Gitleaks' git-log mode to walk
anyway, and every other scanner in this pipeline (Semgrep, Trivy, Checkov,
CodeQL) also operates on present working-tree content, not historical
commits. ``--exit-code 0`` disables Gitleaks' default "exit 1 when a leak
is found" behavior for the same reason `run_semgrep()` ignores Semgrep's
exit code: a findings-bearing run is not a crash (PRD requirement 18).

**AC-27 (PRD S9.3/S12, R14) -- Finding.message must never carry the raw
matched secret.** Two layers, both required:

1. Construction discipline: ``normalize_gitleaks()`` builds `message` from
   only the Gitleaks ``Description`` and ``RuleID`` fields -- the ``Secret``
   and ``Match`` fields (which contain the actual matched credential text
   and its surrounding source line) are never read into `message`.
2. Defense-in-depth redaction pass: `message` is additionally run through
   `scrubber.scrub()` (reused verbatim, not reinvented -- spec S12) against
   every ``Secret``/``Match`` value present in *this same scan batch*, so a
   future or custom Gitleaks rule whose own ``Description`` template echoes
   part of the match (this module's own test fixture exercises exactly that
   adversarial case) still cannot leak the secret through `message`.
   Applied at `Finding` construction time, not as an afterthought filter a
   later code path could bypass.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from normalize import Finding
from scanners.types import ScanResult, ScanStatus
from scrubber import scrub
from severity import severity_from_gitleaks

TOOL_NAME = "gitleaks"


def _build_command(workspace: Path, report_path: Path) -> list[str]:
    """Build the ``gitleaks detect`` invocation. See module docstring --
    ``--report-path`` is a real temp file (S-141 finding: ``/dev/stdout``
    silently lost real findings under pipe-captured stdout), not a device
    file.
    """
    return [
        "gitleaks",
        "detect",
        "--source",
        str(workspace),
        "--no-git",
        "--report-format",
        "json",
        "--report-path",
        str(report_path),
        "--exit-code",
        "0",
    ]


def _collect_secret_values(leaks: list[dict[str, Any]]) -> list[str]:
    """Every raw matched-secret string in this batch (``Secret`` and the
    surrounding ``Match`` context) -- the redaction set for `scrub()`.
    Order doesn't matter; duplicates are harmless (`scrub()` is a no-op on a
    substring not present in the target text).
    """
    secrets: list[str] = []
    for leak in leaks:
        secret = leak.get("Secret")
        if secret:
            secrets.append(secret)
        match = leak.get("Match")
        if match:
            secrets.append(match)
    return secrets


def normalize_gitleaks(raw_output: str) -> list[Finding]:
    """Parse Gitleaks ``--report-format json`` output into `Finding` records
    (spec S8.1, PRD requirement 58 row 2 / D29).

    Pure function over the raw JSON text. Gitleaks writes a bare ``null``
    (not ``[]``) on some older versions when zero leaks are found; the real
    v8.30.1 binary, confirmed against a real **file** ``--report-path``
    (module docstring's REVERTED section -- the earlier belief that a clean
    scan produces zero bytes was an artifact of the since-removed
    ``/dev/stdout`` trick silently losing data, not real gitleaks output
    shape), writes ``[]`` on a clean scan. The empty-string case is kept as
    a defensive fallback (harmless, matches `codeql_runner.py`'s equally
    defensive missing-file handling) rather than removed outright, since a
    zero-byte report file is still plausible from a future gitleaks version
    or an unusual filesystem interaction. All three (``null``, ``[]``, empty
    string) are treated identically as "no leaks" rather than a parse
    failure. Raises `json.JSONDecodeError` on
    invalid JSON, `TypeError` on a structurally-unexpected top-level shape
    (anything other than a list or `null`), and `KeyError` on a leak record
    missing a required field -- `run_gitleaks()` below catches all three and
    maps them to the non-fatal `ScanStatus.FAILED` path (PRD requirement
    18); this function itself stays a strict, total-over-its-documented-
    input-shape parser rather than silently swallowing structural errors.

    ``severity`` is always `Severity.CRITICAL` via `severity_from_gitleaks()`
    (D29, unconditional, no per-rule grading -- not reimplemented here).
    ``remediation`` is always `None`: Gitleaks has no native mechanical fix
    path (a leaked secret requires revocation/rotation, not a code patch).
    ``cwe_or_category`` falls back to `rule_id` -- Gitleaks carries no
    CWE/OWASP metadata, mirroring Semgrep's own last-resort fallback so the
    cross-tool dedup key (`fingerprint()`'s `rule_id or cwe_or_category`) is
    never empty.
    """
    if raw_output.strip() == "":
        return []
    data = json.loads(raw_output)
    if data is None:
        return []
    if not isinstance(data, list):
        raise TypeError(f"expected a JSON array (or null) of leaks, got {type(data).__name__}")

    leaks: list[dict[str, Any]] = data
    all_secret_values = _collect_secret_values(leaks)

    findings: list[Finding] = []
    for index, leak in enumerate(leaks):
        rule_id = leak["RuleID"]
        description = leak.get("Description") or "Secret detected"

        # AC-27 construction discipline: only Description + RuleID feed
        # `message` -- `Secret`/`Match` are never read here. The scrub() call
        # is the defense-in-depth second layer (module docstring point 2).
        message = scrub(f"{description} (gitleaks rule: {rule_id})", all_secret_values)

        findings.append(
            Finding(
                tool=TOOL_NAME,
                rule_id=rule_id,
                severity=severity_from_gitleaks(leak),
                file_path=leak["File"],
                line_start=leak["StartLine"],
                line_end=leak["EndLine"],
                message=message,
                cwe_or_category=rule_id,
                remediation=None,
                raw_ref=f"{TOOL_NAME}#{index}",
            )
        )
    return findings


def run_gitleaks(workspace: Path, timeout: int) -> ScanResult:
    """Run Gitleaks against `workspace` and normalize its output (spec S8.5).

    Enforces `timeout` independently of any other scanner (PRD requirement
    19 -- callers pass `config.SCANNER_TIMEOUT`, no shared timeout budget is
    read from here). A crash-to-start (`OSError` -- e.g. the `gitleaks`
    binary missing from the image), a timeout (`subprocess.TimeoutExpired`),
    a missing/unreadable report file, or unparseable/structurally-unexpected
    report content are all non-fatal to the overall run (PRD requirement
    18): each maps to `ScanStatus.FAILED` with `findings=[]` and a `reason`
    describing what happened, never an exception raised out of this
    function. Every `reason` string here is built only from exception
    metadata (timeout duration, `OSError`/`json.JSONDecodeError`/`TypeError`
    messages) -- never from the raw subprocess stdout/stderr or report-file
    text itself, so a malformed report containing partial secret content
    cannot leak through this failure-reporting surface either (AC-27's
    failure-path corollary).

    Deliberately does NOT treat a non-zero exit code alone as a failure,
    mirroring `run_semgrep()`: `--exit-code 0` is passed explicitly (see
    module docstring) so Gitleaks itself should never exit non-zero on a
    findings-bearing run, but `subprocess.run` is still called without
    `check=True` and success/failure is decided purely by whether stdout
    parses into the expected shape, in case that assumption is ever violated
    by a future Gitleaks version.

    No secrets list is threaded through this call from the caller side (the
    spec S8.5 `run_<tool>` signature takes only `workspace`/`timeout`) --
    the per-finding redaction set is derived from this same scan's own
    output inside `normalize_gitleaks()`. `scrubber.scrub_process_error()`
    is applied at the orchestration layer (S-135's `run_scanners()`) for any
    *other* known secrets (e.g. the GitHub installation token) once a
    per-run secrets list is available, before any per-tool `reason` string
    reaches a log, artifact, or PR body.
    """
    with tempfile.TemporaryDirectory(prefix="gitleaks-report-") as tmp:
        report_path = Path(tmp) / "report.json"
        cmd = _build_command(workspace, report_path)
        try:
            # returncode/stdout intentionally unused -- see docstring above:
            # --exit-code 0 neutralizes gitleaks' own findings-bearing exit
            # code, and findings now come from `report_path`, not stdout.
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ScanResult(
                tool=TOOL_NAME,
                status=ScanStatus.FAILED,
                findings=[],
                reason=f"gitleaks timed out after {timeout}s",
            )
        except OSError as exc:
            return ScanResult(
                tool=TOOL_NAME,
                status=ScanStatus.FAILED,
                findings=[],
                reason=f"gitleaks failed to start: {exc}",
            )

        try:
            raw_output = report_path.read_text()
        except OSError as exc:
            return ScanResult(
                tool=TOOL_NAME,
                status=ScanStatus.FAILED,
                findings=[],
                reason=f"gitleaks report file missing/unreadable: {exc}",
            )

        try:
            findings = normalize_gitleaks(raw_output)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            return ScanResult(
                tool=TOOL_NAME,
                status=ScanStatus.FAILED,
                findings=[],
                reason=f"unparseable gitleaks output: {exc}",
            )

    return ScanResult(tool=TOOL_NAME, status=ScanStatus.PASSED, findings=findings, reason=None)
