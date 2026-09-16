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
"""

from __future__ import annotations

from pathlib import Path

from scanners.checkov_runner import run_checkov
from scanners.codeql_runner import run_codeql
from scanners.gitleaks_runner import run_gitleaks
from scanners.semgrep_runner import run_semgrep
from scanners.trivy_runner import run_trivy
from scanners.types import ScanResult, ScanStatus

__all__ = [
    "AllScannersFailedError",
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
    """
    results = [_SCANNER_DISPATCH[name](workspace, timeout) for name in requested]
    if all(r.status == ScanStatus.FAILED for r in results):
        raise AllScannersFailedError(results)
    return results
