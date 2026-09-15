"""
Fingerprinting (spec S8.2, PRD requirement 21 / D18 / D20).

A ``Finding``'s fingerprint identifies "the same underlying issue" across
scans, tools, and small unrelated line-shifting edits -- it is the key every
later stage (cross-tool dedup S-133, the re-scan gate S-137, diffing a run
against its predecessor) uses to decide "is this the finding I already know
about." Deliberately coarser than an exact line match (D18): banding
``line_start`` into fixed-width buckets trades a small false-merge risk
(two genuinely distinct findings landing in the same band) for a much lower
false-new-finding rate (a finding reappearing as "new" purely because an
unrelated edit shifted its line number by one or two lines).

Reviewed against the S-125/S-126 fidelity-audit pattern of literal spec
pseudocode hiding a `KeyError`-prone dict-indexing bug (see severity.py's
module docstring for that precedent): this module's spec S8.2 pseudocode has
no equivalent defect. ``finding.rule_id or finding.cwe_or_category`` is a
plain Python truthiness fallback (empty string -> falls to
``cwe_or_category``, per EC-35), not a raising dict lookup, so it is
implemented here verbatim with no deviation.
"""

from __future__ import annotations

import hashlib

from normalize import Finding

_LINE_TOLERANCE_BAND = 3  # lines


def fingerprint(finding: Finding) -> str:
    """Derive a stable identity hash for ``finding`` (PRD AC6).

    Keyed on ``(file_path, rule_id-or-cwe_or_category, banded line_start)``
    -- never raw tool output, never ``message``/``raw_ref`` (those vary
    across otherwise-identical re-detections and must not perturb the
    fingerprint). ``line_start`` is floored to the nearest multiple of
    ``_LINE_TOLERANCE_BAND`` before hashing, so a sub-band line shift (an
    unrelated edit nudging the finding by one or two lines) does not change
    the fingerprint, while a shift that crosses into a different band --
    including a shift of exactly ``_LINE_TOLERANCE_BAND`` lines, which is
    NOT guaranteed to land in the same band -- does (EC-34).
    """
    banded_line = finding.line_start - (finding.line_start % _LINE_TOLERANCE_BAND)
    key = f"{finding.file_path}::{finding.rule_id or finding.cwe_or_category}::{banded_line}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]
