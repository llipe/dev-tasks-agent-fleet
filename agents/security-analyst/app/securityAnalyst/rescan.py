"""
The re-scan gate (spec §8.7, PRD requirements 33-37 / D23, D25, story
S-137).

This is the agent's defining trust mechanism, with no analog in the sibling
(dependency-update) agent: after a mechanical or LLM fix is applied, the
agent re-runs the scanners and compares the before/after finding sets by
``fingerprint()`` (S-127) before ever proposing the change to a human via a
pull request. Two independent failure modes both fail the gate:

  - a fingerprint the fix was supposed to clear ("targeted") is still
    present after the fix -- the fix did not actually work (PRD AC14);
  - a fingerprint appears after the fix that was not present before it --
    the fix introduced a new problem (PRD AC15) -- unless that specific new
    finding matches an entry in the fixed, enumerated
    ``_ALLOWED_NEW_FINDING_EXCEPTIONS`` table (requirement 34's exception
    clause, e.g. Trivy's own advisory database briefly flagging an
    intermediate patch version as a known transitional artifact of Trivy's
    own remediation flow).

Requirement 34 is explicit that the allow-list is enumerated, never
inferred: ``_matches_allowed_exception`` below does an exact
``(tool, rule_id-or-category)`` membership check against the fixed table --
no substring, prefix, or fuzzy matching of any kind. A new finding whose
rule/category pattern is merely *close to* an enumerated entry (e.g. a
pluralized or reworded rule id) is, by design, NOT an allowed exception; it
fails the gate like any other unexplained new finding. Built and proven
standalone here (S-137) -- the orchestrator does not call this module yet;
that wiring is S-140.
"""

from __future__ import annotations

from dataclasses import dataclass

from dedupe import MergedFinding
from fingerprint import fingerprint

# tool -> set of rule_id/cwe_or_category patterns permitted as a known,
# enumerated transitional artifact of that tool's own remediation flow
# (requirement 34). Fixed and exhaustive -- adding a new exception means
# adding a new entry here, never adding matching logic.
_ALLOWED_NEW_FINDING_EXCEPTIONS: dict[str, set[str]] = {
    "trivy": {"intermediate-patch-advisory"},
}


@dataclass(frozen=True)
class GateResult:
    """The re-scan gate's verdict for one fix-and-rescan cycle (spec §8.7).

    ``clean`` is ``True`` only when both ``still_present`` and
    ``unexplained_new`` are empty. ``still_present`` and ``unexplained_new``
    are always populated (possibly empty sets, never ``None``) so a caller
    never needs a null check before reporting them (e.g. in the PR body's
    re-scan confirmation line, or a ``RESCAN_NOT_CLEAN`` failure record).
    """

    clean: bool
    still_present: set[str]
    unexplained_new: set[str]


def rescan_gate(
    before: list[MergedFinding],
    after: list[MergedFinding],
    targeted: set[str],
) -> GateResult:
    """Compare a pre-fix and post-fix finding set by fingerprint (spec §8.7).

    ``targeted`` is the set of fingerprints the fix was applied against --
    computed by the caller from ``before``, not derived here, since the
    gate itself has no notion of which findings a particular fix run
    intended to clear.

    ``still_present``: the subset of ``targeted`` whose fingerprint is
    still in the post-fix set -- the fix did not clear it (PRD requirement
    34's first bullet, AC14 groundwork).

    ``unexplained_new``: fingerprints present after the fix but absent
    before it, filtered to exclude fingerprints matching an enumerated
    ``_ALLOWED_NEW_FINDING_EXCEPTIONS`` entry (PRD requirement 34's second
    bullet, AC15 groundwork). A still-present target is never itself
    "new" (it was already in ``before``), so the two sets are always
    disjoint by construction -- no double-counting between them.
    """
    after_fp = {fingerprint(m.finding) for m in after}
    before_fp = {fingerprint(m.finding) for m in before}

    still_present = targeted & after_fp

    new_fp = after_fp - before_fp
    unexplained_new = {fp for fp in new_fp if not _matches_allowed_exception(fp, after)}

    clean = not still_present and not unexplained_new
    return GateResult(clean=clean, still_present=still_present, unexplained_new=unexplained_new)


def _matches_allowed_exception(fp: str, after: list[MergedFinding]) -> bool:
    """Exact-match check against the fixed allow-list table (requirement 34).

    Looks up the finding in ``after`` carrying fingerprint ``fp`` to read
    its ``tool`` and ``rule_id``/``cwe_or_category``, then checks for exact
    membership in ``_ALLOWED_NEW_FINDING_EXCEPTIONS[tool]``. Deliberately
    exact equality on both the tool key and the pattern string -- no
    ``in``/substring/prefix check -- so a near-miss pattern (e.g. a
    pluralized or reworded rule id close to but not identical to an
    enumerated entry) is correctly rejected rather than fuzzily accepted.
    If no finding in ``after`` carries ``fp`` (should not happen given
    ``fp`` is drawn from ``after``'s own fingerprints), this conservatively
    returns ``False`` -- an un-locatable fingerprint is never excused.
    """
    for merged in after:
        if fingerprint(merged.finding) == fp:
            allowed_patterns = _ALLOWED_NEW_FINDING_EXCEPTIONS.get(merged.finding.tool)
            if allowed_patterns is None:
                return False
            pattern = merged.finding.rule_id or merged.finding.cwe_or_category
            return pattern in allowed_patterns
    return False
