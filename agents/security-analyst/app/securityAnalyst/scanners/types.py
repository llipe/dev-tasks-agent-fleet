"""
Scanner dispatch result shape (spec §8.5), shared by every `run_<tool>()`
function across the `scanners/` subpackage.

This module has no story-specific logic of its own -- it exists so
`ScanStatus`/`ScanResult` are defined exactly once and imported verbatim by
`semgrep_runner.py` (S-128) and, from S-129 onward, `gitleaks_runner.py`,
`trivy_runner.py`, `checkov_runner.py`, and `codeql_runner.py`. Spec §8.5
shows this shape inline alongside all five `run_<tool>()` signatures and the
`run_scanners()` dispatcher (S-135's scope); factoring it into its own
module here is this story's minimal, spec-consistent design decision so
later scanner stories reuse the identical class objects (not five
independently-defined-but-structurally-identical enums/dataclasses, which
would break `isinstance`/equality checks across tool boundaries once
`run_scanners()` aggregates their results in S-135).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from normalize import Finding


class ScanStatus(Enum):
    """Per-tool scan outcome (PRD requirements 15-19)."""

    PASSED = "passed"  # ran, findings normalized (zero or more)
    SKIPPED = "skipped"  # not applicable to this repo content (req 17)
    FAILED = "failed"  # crashed, timed out, or unparseable output (req 18)


@dataclass(frozen=True)
class ScanResult:
    """Outcome of one `run_<tool>()` call.

    `reason` is populated for `SKIPPED`/`FAILED` (surfaced as a per-tool
    `error`-level `run_event`, per PRD requirement 18) and is `None` for
    `PASSED`. `findings` is always `[]` for `SKIPPED`/`FAILED` -- a failed
    or skipped tool contributes no findings to the run.
    """

    tool: str
    status: ScanStatus
    findings: list[Finding]
    reason: str | None
