"""
Shared fixer result shape (spec S8.6), used by both `semgrep_autofix.py` and
`trivy_bump.py`.

Mirrors `scanners/types.py`'s convention (S-128): defined exactly once so
both fixer modules import the same class object rather than two
structurally-identical-but-distinct dataclasses, keeping any future
aggregation (S-140's `fix` orchestration step) able to treat both fixers'
outcomes uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dedupe import MergedFinding


@dataclass(frozen=True)
class FixOutcome:
    """Outcome of one deterministic fixer invocation.

    `applied_fingerprints` is the set of targeted findings' `fingerprint()`
    values this fixer believes it resolved -- a best-effort, file-diff-level
    signal (see each fixer module's own `_diff_applied`-equivalent), never
    the authoritative resolution proof. The re-scan gate (`rescan.py`,
    S-137) is the actual authority: it re-runs the scanners and checks
    fingerprint absence, which is the only proof that a fix genuinely
    resolved the underlying issue rather than merely touching the file.

    `unresolved` carries the targeted `MergedFinding` records this fixer
    could not deterministically fix -- e.g. a Semgrep autofix patch that
    failed to apply cleanly, or a Trivy version bump requiring a source edit
    beyond the version string itself (PRD requirement 29). This story does
    not invoke the LLM escape hatch itself (`fix_agent.py`, S-138's scope);
    `unresolved` is the explicit handoff point a later story's orchestrator
    reads from.

    `output` is the combined stdout+stderr (or a synthesized failure
    message) of the underlying subprocess call(s), kept for the audit trail
    -- never embedded in a `Finding.message` or otherwise surfaced to a
    fingerprint/dedup/classification path.
    """

    applied_fingerprints: frozenset[str]
    unresolved: tuple[MergedFinding, ...] = field(default_factory=tuple)
    output: str = ""
