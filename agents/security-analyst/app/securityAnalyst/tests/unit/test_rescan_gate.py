"""
Unit tests for the re-scan gate (spec §8.7, PRD requirements 33-37 / D23,
D25, story S-137, acceptance criteria 14-15 groundwork).

Covers:
  - All four combinations of still-present / new-finding outcomes (task
    13.6): clean, still-present-only, new-finding-only, both.
  - PRD AC14 groundwork: a targeted finding surviving the fix ->
    ``clean=False``, named in ``still_present``.
  - PRD AC15 groundwork: an unrelated new finding introduced by the fix ->
    ``clean=False``, named in ``unexplained_new`` -- unless it matches an
    enumerated ``_ALLOWED_NEW_FINDING_EXCEPTIONS`` entry.
  - PRD requirement 34: the allow-list is a FIXED, ENUMERATED table, never
    inferred -- a near-miss (close but not identical) pattern must NOT be
    treated as an allowed exception.
"""

from __future__ import annotations

import dataclasses

import pytest

from dedupe import MergedFinding
from fingerprint import fingerprint
from normalize import Finding, Remediation
from rescan import _ALLOWED_NEW_FINDING_EXCEPTIONS, GateResult, rescan_gate
from severity import Severity


def _make_finding(
    *,
    tool: str = "semgrep",
    rule_id: str = "python.lang.security.audit.eval-detected",
    severity: Severity = Severity.HIGH,
    file_path: str = "app/main.py",
    line_start: int = 10,
    line_end: int = 10,
    message: str = "Detected use of eval().",
    cwe_or_category: str = "CWE-95",
    remediation: Remediation | None = None,
    raw_ref: str = "semgrep_findings.json#0",
) -> Finding:
    return Finding(
        tool=tool,
        rule_id=rule_id,
        severity=severity,
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        message=message,
        cwe_or_category=cwe_or_category,
        remediation=remediation,
        raw_ref=raw_ref,
    )


def _merged(finding: Finding, *, reported_by: tuple[str, ...] | None = None) -> MergedFinding:
    return MergedFinding(finding=finding, reported_by=reported_by or (finding.tool,))


# ---------------------------------------------------------------------------
# GateResult schema shape
# ---------------------------------------------------------------------------


class TestGateResultSchema:
    def test_gate_result_is_a_frozen_dataclass(self):
        assert dataclasses.is_dataclass(GateResult)
        result = GateResult(clean=True, still_present=set(), unexplained_new=set())
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.clean = False  # type: ignore[misc]

    def test_gate_result_field_names_match_spec(self):
        field_names = [f.name for f in dataclasses.fields(GateResult)]
        assert field_names == ["clean", "still_present", "unexplained_new"]


# ---------------------------------------------------------------------------
# Four combinations of still-present / new-finding outcomes (task 13.6)
# ---------------------------------------------------------------------------


class TestFourCombinations:
    def test_clean_when_target_gone_and_no_new_findings(self):
        # Combination 1: fix worked, nothing new -- clean=True.
        target = _make_finding(rule_id="eval-detected", line_start=10)
        unrelated = _make_finding(rule_id="hardcoded-secret", line_start=100)
        before = [_merged(target), _merged(unrelated)]
        after = [_merged(unrelated)]  # target cleared, unrelated survives untouched
        targeted = {fingerprint(target)}

        result = rescan_gate(before, after, targeted)

        assert result.clean is True
        assert result.still_present == set()
        assert result.unexplained_new == set()

    def test_not_clean_when_target_still_present_and_no_new_findings(self):
        # Combination 2: fix did not actually clear the target -- clean=False,
        # still_present names it, unexplained_new stays empty (PRD AC14
        # groundwork, task 13.2).
        target = _make_finding(rule_id="eval-detected", line_start=10)
        before = [_merged(target)]
        after = [_merged(target)]  # unchanged -- fix failed to clear it

        targeted = {fingerprint(target)}
        result = rescan_gate(before, after, targeted)

        assert result.clean is False
        assert result.still_present == {fingerprint(target)}
        assert result.unexplained_new == set()

    def test_not_clean_when_target_gone_but_unexplained_new_finding_appears(self):
        # Combination 3: fix removes the target but introduces an unrelated
        # new finding not on the allow-list -- clean=False, unexplained_new
        # names it, still_present stays empty (PRD AC15 groundwork, task
        # 13.3).
        target = _make_finding(rule_id="eval-detected", line_start=10)
        new_finding = _make_finding(tool="semgrep", rule_id="new-unrelated-issue", line_start=200)
        before = [_merged(target)]
        after = [_merged(new_finding)]

        targeted = {fingerprint(target)}
        result = rescan_gate(before, after, targeted)

        assert result.clean is False
        assert result.still_present == set()
        assert result.unexplained_new == {fingerprint(new_finding)}

    def test_not_clean_when_target_still_present_and_new_finding_appears(self):
        # Combination 4: both failure modes at once -- both sets populated.
        target = _make_finding(rule_id="eval-detected", line_start=10)
        new_finding = _make_finding(tool="semgrep", rule_id="new-unrelated-issue", line_start=200)
        before = [_merged(target)]
        after = [_merged(target), _merged(new_finding)]

        targeted = {fingerprint(target)}
        result = rescan_gate(before, after, targeted)

        assert result.clean is False
        assert result.still_present == {fingerprint(target)}
        assert result.unexplained_new == {fingerprint(new_finding)}


# ---------------------------------------------------------------------------
# Allow-list exception path (task 13.4, PRD requirement 34's exception
# clause)
# ---------------------------------------------------------------------------


class TestAllowListException:
    def test_enumerated_exception_does_not_fail_the_gate(self):
        # The one seeded entry: trivy / "intermediate-patch-advisory" is a
        # known, enumerated transitional artifact of Trivy's own remediation
        # flow -- must NOT count as an unexplained new finding.
        target = _make_finding(tool="trivy", rule_id="CVE-2024-1234", line_start=10)
        allowed_new = _make_finding(
            tool="trivy", rule_id="intermediate-patch-advisory", line_start=50
        )
        before = [_merged(target)]
        after = [_merged(allowed_new)]

        targeted = {fingerprint(target)}
        result = rescan_gate(before, after, targeted)

        assert result.clean is True
        assert result.still_present == set()
        assert result.unexplained_new == set()

    def test_allow_listed_new_finding_alongside_a_still_present_target_stays_not_clean(self):
        # The allow-list only excuses the NEW finding -- it never excuses a
        # still-present target. Gate must still fail via still_present.
        target = _make_finding(tool="trivy", rule_id="CVE-2024-1234", line_start=10)
        allowed_new = _make_finding(
            tool="trivy", rule_id="intermediate-patch-advisory", line_start=50
        )
        before = [_merged(target)]
        after = [_merged(target), _merged(allowed_new)]

        targeted = {fingerprint(target)}
        result = rescan_gate(before, after, targeted)

        assert result.clean is False
        assert result.still_present == {fingerprint(target)}
        assert result.unexplained_new == set()


# ---------------------------------------------------------------------------
# Requirement 34: the gate never infers an exception -- near-miss patterns
# must NOT be treated as allowed (task 13.5, task 13.6's near-miss case)
# ---------------------------------------------------------------------------


class TestNoInferenceNearMiss:
    def test_near_miss_rule_id_is_not_treated_as_an_allowed_exception(self):
        # "intermediate-patch-advisories" (plural) is close to, but not
        # identical to, the enumerated "intermediate-patch-advisory" entry.
        # A fuzzy/substring/prefix matcher would wrongly allow this; an
        # exact-match-only table must not.
        target = _make_finding(tool="trivy", rule_id="CVE-2024-1234", line_start=10)
        near_miss_new = _make_finding(
            tool="trivy", rule_id="intermediate-patch-advisories", line_start=50
        )
        before = [_merged(target)]
        after = [_merged(near_miss_new)]

        targeted = {fingerprint(target)}
        result = rescan_gate(before, after, targeted)

        assert result.clean is False
        assert result.unexplained_new == {fingerprint(near_miss_new)}

    def test_right_pattern_wrong_tool_is_not_treated_as_an_allowed_exception(self):
        # The exact pattern string "intermediate-patch-advisory" is
        # enumerated under "trivy" only. The same rule_id reported by a
        # different tool must not inherit the exception -- the table key is
        # (tool, pattern), not pattern alone.
        target = _make_finding(tool="checkov", rule_id="CKV-1234", line_start=10)
        wrong_tool_new = _make_finding(
            tool="checkov", rule_id="intermediate-patch-advisory", line_start=50
        )
        before = [_merged(target)]
        after = [_merged(wrong_tool_new)]

        targeted = {fingerprint(target)}
        result = rescan_gate(before, after, targeted)

        assert result.clean is False
        assert result.unexplained_new == {fingerprint(wrong_tool_new)}

    def test_allowed_exceptions_table_is_fixed_and_enumerated(self):
        # Directly exercises requirement 34's "enumerated by tool, never
        # inferred" shape: a fixed dict[str, set[str]], not a callable
        # heuristic or pattern-matcher.
        assert isinstance(_ALLOWED_NEW_FINDING_EXCEPTIONS, dict)
        assert {
            "trivy": {"intermediate-patch-advisory"},
        } == _ALLOWED_NEW_FINDING_EXCEPTIONS


# ---------------------------------------------------------------------------
# Empty-input edges
# ---------------------------------------------------------------------------


class TestEmptyInputs:
    def test_empty_before_after_and_targeted_is_clean(self):
        result = rescan_gate([], [], set())
        assert result == GateResult(clean=True, still_present=set(), unexplained_new=set())

    def test_targeted_fingerprint_not_present_pre_or_post_is_not_still_present(self):
        # A targeted fingerprint that never appears in `after` at all (not
        # just cleared, genuinely absent) is not "still present" -- the gate
        # only flags fingerprints that are BOTH targeted and present after.
        target = _make_finding(rule_id="eval-detected", line_start=10)
        before = [_merged(target)]
        after: list[MergedFinding] = []
        targeted = {fingerprint(target)}

        result = rescan_gate(before, after, targeted)

        assert result.clean is True
        assert result.still_present == set()
