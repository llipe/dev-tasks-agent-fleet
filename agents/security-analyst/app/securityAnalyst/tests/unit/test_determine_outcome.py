"""
Tests for `main.determine_outcome()` and `main._at_or_above_floor()` (spec
§8.10, PRD §8.1 / requirements 62-64 / D31, story S-135, tasks 11.4/11.11).

Scope: this story wires only the `audit_only` branch of the state machine
(the `fix` branch is S-136-S-140's scope — see module docstring in
`main.py`). Every `audit_only` row of PRD §8.1's table is covered here,
crossed with `min_severity` floor placement (PRD AC-12b / requirement 63):
the floor gates only the pass/fail decision, never what is reported.
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
