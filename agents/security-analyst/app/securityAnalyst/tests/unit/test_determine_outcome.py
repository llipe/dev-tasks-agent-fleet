"""
Tests for `main.determine_outcome()` and `main._at_or_above_floor()` (spec
§8.10, PRD §8.1 / requirements 62-64 / D31, stories S-135/S-140).

Scope: `TestAuditOnlyOutcomeTable`/`TestMinSeverityGatesStatusOnly`/
`test_audit_only_matrix` cover the `audit_only` branch (S-135) — every
`audit_only` row of PRD §8.1's table, crossed with `min_severity` floor
placement (PRD AC-12b / requirement 63): the floor gates only the pass/fail
decision, never what is reported.

`TestFixOutcomeTable`/`test_fix_mode_matrix` (S-140) cover the `fix` branch
added by this story, parametrized over every PRD §8.1 `fix`-mode row (spec
§8.10's pseudocode, reproduced in `main.determine_outcome()`'s own
docstring). `determine_outcome()` keeps its 3-tuple `(status, outcome,
error_code)` return shape for both modes — see `main.py`'s docstring for
why `pr_opened` is computed at the call site instead of widened into the
tuple, preserving every `audit_only` test above byte-for-byte.
"""

from __future__ import annotations

import pytest

from dedupe import MergedFinding
from main import _at_or_above_floor, determine_outcome
from normalize import Finding
from severity import Severity


def _finding(severity: Severity, tool: str = "semgrep") -> MergedFinding:
    f = Finding(
        tool=tool,
        rule_id="RULE1",
        severity=severity,
        file_path="app/main.py",
        line_start=1,
        line_end=1,
        message="test finding",
        cwe_or_category="CWE-000",
        remediation=None,
        raw_ref=f"{tool}:0",
    )
    return MergedFinding(finding=f, reported_by=(tool,))


# ---------------------------------------------------------------------------
# _at_or_above_floor
# ---------------------------------------------------------------------------


class TestAtOrAboveFloor:
    def test_empty_list_returns_empty(self):
        assert _at_or_above_floor([], "low") == []

    def test_low_floor_keeps_everything(self):
        findings = [_finding(Severity.LOW), _finding(Severity.CRITICAL)]
        assert _at_or_above_floor(findings, "low") == findings

    def test_high_floor_excludes_low_and_medium(self):
        low = _finding(Severity.LOW)
        medium = _finding(Severity.MEDIUM)
        high = _finding(Severity.HIGH)
        critical = _finding(Severity.CRITICAL)
        result = _at_or_above_floor([low, medium, high, critical], "high")
        assert result == [high, critical]

    def test_critical_floor_excludes_everything_but_critical(self):
        findings = [_finding(Severity.LOW), _finding(Severity.HIGH)]
        assert _at_or_above_floor(findings, "critical") == []

    def test_medium_floor_boundary_inclusive(self):
        """A finding exactly at the floor is kept (>=, not >)."""
        medium = _finding(Severity.MEDIUM)
        assert _at_or_above_floor([medium], "medium") == [medium]

    def test_monotonic_raising_floor_never_increases_result_size(self):
        """RT-6: raising min_severity never increases the gated-finding-set size."""
        findings = [
            _finding(Severity.LOW),
            _finding(Severity.MEDIUM),
            _finding(Severity.HIGH),
            _finding(Severity.CRITICAL),
        ]
        floors_in_order = ["low", "medium", "high", "critical"]
        sizes = [len(_at_or_above_floor(findings, floor)) for floor in floors_in_order]
        assert sizes == sorted(sizes, reverse=True)


# ---------------------------------------------------------------------------
# determine_outcome — audit_only mode, PRD §8.1 rows
# ---------------------------------------------------------------------------


class TestAuditOnlyOutcomeTable:
    """Every audit_only row of PRD §8.1's status/outcome table."""

    def test_no_findings_at_all(self):
        """Row 1: no findings -> succeeded/no_findings."""
        status, outcome, error_code = determine_outcome(
            mode="audit_only", findings=[], min_severity="low", fail_on_findings=True
        )
        assert (status, outcome, error_code) == ("succeeded", "no_findings", None)

    def test_findings_none_at_or_above_floor(self):
        """Row 2: findings exist but none reach min_severity -> succeeded/no_findings."""
        findings = [_finding(Severity.LOW), _finding(Severity.MEDIUM)]
        status, outcome, error_code = determine_outcome(
            mode="audit_only", findings=findings, min_severity="high", fail_on_findings=True
        )
        assert (status, outcome, error_code) == ("succeeded", "no_findings", None)

    def test_gated_findings_fail_on_findings_false(self):
        """Row 3: findings at/above floor, fail_on_findings=false -> succeeded/needs_review."""
        findings = [_finding(Severity.HIGH)]
        status, outcome, error_code = determine_outcome(
            mode="audit_only", findings=findings, min_severity="low", fail_on_findings=False
        )
        assert (status, outcome, error_code) == ("succeeded", "needs_review", None)

    def test_gated_findings_fail_on_findings_true(self):
        """Row 4: findings at/above floor, fail_on_findings=true -> failed/AUDIT_FINDINGS."""
        findings = [_finding(Severity.HIGH)]
        status, outcome, error_code = determine_outcome(
            mode="audit_only", findings=findings, min_severity="low", fail_on_findings=True
        )
        assert (status, outcome, error_code) == ("failed", "needs_review", "AUDIT_FINDINGS")


# ---------------------------------------------------------------------------
# AC-12b -- min_severity gates status only, never what is scanned/reported
# ---------------------------------------------------------------------------


class TestMinSeverityGatesStatusOnly:
    def test_high_floor_with_only_low_and_medium_is_no_findings_not_failed(self):
        """AC-12b first half: min_severity=high, only low/medium findings present
        -> succeeded/no_findings, NOT failed, even with fail_on_findings=true."""
        findings = [_finding(Severity.LOW), _finding(Severity.MEDIUM)]
        status, outcome, error_code = determine_outcome(
            mode="audit_only", findings=findings, min_severity="high", fail_on_findings=True
        )
        assert status == "succeeded"
        assert outcome == "no_findings"
        assert error_code is None

    def test_same_repo_plus_one_high_finding_fails(self):
        """AC-12b second half: same repo + one high finding -> failed/AUDIT_FINDINGS."""
        findings = [_finding(Severity.LOW), _finding(Severity.MEDIUM), _finding(Severity.HIGH)]
        status, outcome, error_code = determine_outcome(
            mode="audit_only", findings=findings, min_severity="high", fail_on_findings=True
        )
        assert (status, outcome, error_code) == ("failed", "needs_review", "AUDIT_FINDINGS")

    def test_default_min_severity_low_is_equivalent_to_no_floor(self):
        """req 64: min_severity defaults to low, equivalent to no floor."""
        findings = [_finding(Severity.LOW)]
        status, outcome, error_code = determine_outcome(
            mode="audit_only", findings=findings, min_severity="low", fail_on_findings=True
        )
        assert (status, outcome, error_code) == ("failed", "needs_review", "AUDIT_FINDINGS")


# ---------------------------------------------------------------------------
# Parametrized crossing: every (findings-severity-set, min_severity,
# fail_on_findings) combination maps to the exact PRD §8.1 row.
# ---------------------------------------------------------------------------

_SEVERITIES = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
_FLOORS = ["low", "medium", "high", "critical"]
_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@pytest.mark.parametrize("floor", _FLOORS)
@pytest.mark.parametrize("finding_severity", _SEVERITIES)
@pytest.mark.parametrize("fail_on_findings", [True, False])
def test_audit_only_matrix(floor, finding_severity, fail_on_findings):
    """Full cross of one finding's severity x every min_severity x fail_on_findings."""
    findings = [_finding(finding_severity)]
    status, outcome, error_code = determine_outcome(
        mode="audit_only",
        findings=findings,
        min_severity=floor,
        fail_on_findings=fail_on_findings,
    )

    gated = _RANK[finding_severity.value] >= _RANK[floor]
    if not gated:
        assert (status, outcome, error_code) == ("succeeded", "no_findings", None)
    elif not fail_on_findings:
        assert (status, outcome, error_code) == ("succeeded", "needs_review", None)
    else:
        assert (status, outcome, error_code) == ("failed", "needs_review", "AUDIT_FINDINGS")


# ---------------------------------------------------------------------------
# determine_outcome — fix mode, PRD §8.1 rows (S-140)
# ---------------------------------------------------------------------------


class TestFixOutcomeTable:
    """Every `fix`-mode row of PRD §8.1's status/outcome table (spec §8.10)."""

    def test_no_mechanical_no_manual_no_unscannable_is_no_findings(self):
        """Zero findings anywhere -> succeeded/no_findings, no PR (AC21/SC-30)."""
        status, outcome, error_code = determine_outcome(
            mode="fix",
            findings=[],
            min_severity="low",
            fail_on_findings=True,
            mechanical_findings=[],
            manual_or_unscannable_findings=[],
        )
        assert (status, outcome, error_code) == ("succeeded", "no_findings", None)

    def test_no_mechanical_but_manual_remaining_is_needs_review(self):
        """Zero mechanical, but manual/unscannable remain -> succeeded/needs_review,
        no PR (AC21/SC-31)."""
        remainder = [_finding(Severity.HIGH)]
        status, outcome, error_code = determine_outcome(
            mode="fix",
            findings=remainder,
            min_severity="low",
            fail_on_findings=True,
            mechanical_findings=[],
            manual_or_unscannable_findings=remainder,
        )
        assert (status, outcome, error_code) == ("succeeded", "needs_review", None)

    def test_no_mechanical_remainder_below_floor_is_no_findings(self):
        """req 63: min_severity still gates the fix-mode no-mechanical outcome
        label, exactly as it does for audit_only -- it never changes what was
        fixed/scanned."""
        remainder = [_finding(Severity.LOW)]
        status, outcome, error_code = determine_outcome(
            mode="fix",
            findings=remainder,
            min_severity="high",
            fail_on_findings=True,
            mechanical_findings=[],
            manual_or_unscannable_findings=remainder,
        )
        assert (status, outcome, error_code) == ("succeeded", "no_findings", None)

    def test_mechanical_present_rescan_not_clean_fails(self):
        """AC14/AC15 groundwork: mechanical findings existed, re-scan gate not
        clean -> failed/needs_review/RESCAN_NOT_CLEAN, no PR."""
        mechanical = [_finding(Severity.HIGH)]
        status, outcome, error_code = determine_outcome(
            mode="fix",
            findings=mechanical,
            min_severity="low",
            fail_on_findings=True,
            mechanical_findings=mechanical,
            manual_or_unscannable_findings=[],
            rescan_clean=False,
        )
        assert (status, outcome, error_code) == ("failed", "needs_review", "RESCAN_NOT_CLEAN")

    def test_mechanical_present_rescan_clean_no_remainder_is_fixed(self):
        """Clean gate, nothing left manual/unscannable -> succeeded/fixed, PR
        opened at the call site (AC13)."""
        mechanical = [_finding(Severity.HIGH)]
        status, outcome, error_code = determine_outcome(
            mode="fix",
            findings=mechanical,
            min_severity="low",
            fail_on_findings=True,
            mechanical_findings=mechanical,
            manual_or_unscannable_findings=[],
            rescan_clean=True,
        )
        assert (status, outcome, error_code) == ("succeeded", "fixed", None)

    def test_mechanical_present_rescan_clean_with_remainder_is_partial(self):
        """Clean gate, manual/unscannable findings still remain -> succeeded/partial."""
        mechanical = [_finding(Severity.HIGH)]
        remainder = [_finding(Severity.MEDIUM)]
        status, outcome, error_code = determine_outcome(
            mode="fix",
            findings=mechanical + remainder,
            min_severity="low",
            fail_on_findings=True,
            mechanical_findings=mechanical,
            manual_or_unscannable_findings=remainder,
            rescan_clean=True,
        )
        assert (status, outcome, error_code) == ("succeeded", "partial", None)

    def test_pr_already_existed_short_circuits_not_applicable(self):
        """PRD AC22 (idempotency): a clean gate but a pre-existing open PR ->
        succeeded/not_applicable, no NEW PR (the call site never constructs a
        second PullRequestResult in this case)."""
        mechanical = [_finding(Severity.HIGH)]
        status, outcome, error_code = determine_outcome(
            mode="fix",
            findings=mechanical,
            min_severity="low",
            fail_on_findings=True,
            mechanical_findings=mechanical,
            manual_or_unscannable_findings=[],
            rescan_clean=True,
            pr_existed=True,
        )
        assert (status, outcome, error_code) == ("succeeded", "not_applicable", None)

    def test_min_severity_never_changes_fix_branch_selection(self):
        """req 63: min_severity must never affect WHICH branch (mechanical vs.
        not, clean vs. not) is taken -- only the no-mechanical outcome label
        (covered above). A high floor with only a low-severity mechanical
        finding still reaches the clean-gate 'fixed' branch."""
        mechanical = [_finding(Severity.LOW)]
        status, outcome, error_code = determine_outcome(
            mode="fix",
            findings=mechanical,
            min_severity="high",
            fail_on_findings=True,
            mechanical_findings=mechanical,
            manual_or_unscannable_findings=[],
            rescan_clean=True,
        )
        assert (status, outcome, error_code) == ("succeeded", "fixed", None)


@pytest.mark.parametrize("rescan_clean", [True, False])
@pytest.mark.parametrize("has_remainder", [True, False])
@pytest.mark.parametrize("has_mechanical", [True, False])
def test_fix_mode_matrix(has_mechanical, has_remainder, rescan_clean):
    """Full cross of (mechanical present?, remainder present?, gate clean?)
    against PRD §8.1's fix-mode rows (spec §8.10's pseudocode)."""
    mechanical = [_finding(Severity.HIGH)] if has_mechanical else []
    remainder = [_finding(Severity.MEDIUM)] if has_remainder else []

    status, outcome, error_code = determine_outcome(
        mode="fix",
        findings=mechanical + remainder,
        min_severity="low",
        fail_on_findings=True,
        mechanical_findings=mechanical,
        manual_or_unscannable_findings=remainder,
        rescan_clean=rescan_clean,
    )

    if not has_mechanical:
        expected_outcome = "needs_review" if has_remainder else "no_findings"
        assert (status, outcome, error_code) == ("succeeded", expected_outcome, None)
    elif not rescan_clean:
        assert (status, outcome, error_code) == ("failed", "needs_review", "RESCAN_NOT_CLEAN")
    else:
        expected_outcome = "partial" if has_remainder else "fixed"
        assert (status, outcome, error_code) == ("succeeded", expected_outcome, None)
