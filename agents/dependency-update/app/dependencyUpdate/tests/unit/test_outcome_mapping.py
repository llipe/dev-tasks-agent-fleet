"""
Tests for determine_outcome() — every row of the §8.1 outcome table + precedence rules.

Tests cover:
  - audit_only mode: clean, findings+fail_on, findings+!fail_on, major+fail_on, major+!fail_on
  - llm_fix mode: no_changes+no_major, no_changes+major, validation_failing,
    pr_existed (idempotency), pr_opened+no_major, pr_opened+major,
    pr_opened with unknowns → partial
"""

from __future__ import annotations

from classifier import ClassifiedAdvisory
from main import determine_outcome
from validator import CheckStatus, ValidationResult

# ---------------------------------------------------------------------------
# Fixtures / factories
# ---------------------------------------------------------------------------


def _make_advisory(bucket: str = "in_range", module: str = "pkg") -> ClassifiedAdvisory:
    return ClassifiedAdvisory(
        id="GHSA-xxxx",
        module=module,
        severity="high",
        title="Test advisory",
        url="https://github.com/advisories/GHSA-xxxx",
        bucket=bucket,
        reason="test",
    )


def _passing_validation() -> ValidationResult:
    r = ValidationResult()
    r.record("test", CheckStatus.PASSED)
    return r


def _failing_validation() -> ValidationResult:
    r = ValidationResult()
    r.record("test", CheckStatus.FAILED, "some error")
    return r


# ---------------------------------------------------------------------------
# audit_only mode
# ---------------------------------------------------------------------------


class TestAuditOnlyMode:
    """Outcome rows for fix_mode=audit_only."""

    def test_clean_no_findings(self):
        """audit_only + clean → succeeded / no_vulnerabilities."""
        status, outcome, error_code = determine_outcome(
            classified=[],
            params={"fix_mode": "audit_only", "fail_on_findings": True},
            validation=None,
            has_pr=False,
        )
        assert status == "succeeded"
        assert outcome == "no_vulnerabilities"
        assert error_code is None

    def test_findings_fail_on_true_no_major(self):
        """audit_only + findings + fail_on=true + no major → failed / AUDIT_FINDINGS."""
        classified = [_make_advisory("in_range")]
        status, outcome, error_code = determine_outcome(
            classified=classified,
            params={"fix_mode": "audit_only", "fail_on_findings": True},
            validation=None,
            has_pr=False,
        )
        assert status == "failed"
        assert outcome == "needs_review"
        assert error_code == "AUDIT_FINDINGS"

    def test_findings_fail_on_true_with_major(self):
        """audit_only + findings + fail_on=true + major → failed / MAJOR_UPDATE_REQUIRED."""
        classified = [_make_advisory("major_required")]
        status, outcome, error_code = determine_outcome(
            classified=classified,
            params={"fix_mode": "audit_only", "fail_on_findings": True},
            validation=None,
            has_pr=False,
        )
        assert status == "failed"
        assert outcome == "needs_review"
        assert error_code == "MAJOR_UPDATE_REQUIRED"

    def test_findings_fail_on_false(self):
        """audit_only + findings + fail_on=false → succeeded / needs_review."""
        classified = [_make_advisory("in_range")]
        status, outcome, error_code = determine_outcome(
            classified=classified,
            params={"fix_mode": "audit_only", "fail_on_findings": False},
            validation=None,
            has_pr=False,
        )
        assert status == "succeeded"
        assert outcome == "needs_review"
        assert error_code is None

    def test_major_with_fail_on_false(self):
        """audit_only + major + fail_on=false → succeeded / needs_review (req 42 3rd bullet)."""
        classified = [_make_advisory("major_required")]
        status, outcome, error_code = determine_outcome(
            classified=classified,
            params={"fix_mode": "audit_only", "fail_on_findings": False},
            validation=None,
            has_pr=False,
        )
        assert status == "succeeded"
        assert outcome == "needs_review"
        assert error_code is None

    def test_mixed_findings_fail_on_true_major_takes_precedence(self):
        """audit_only + mixed (in_range + major) + fail_on=true → MAJOR_UPDATE_REQUIRED."""
        classified = [_make_advisory("in_range"), _make_advisory("major_required")]
        status, outcome, error_code = determine_outcome(
            classified=classified,
            params={"fix_mode": "audit_only", "fail_on_findings": True},
            validation=None,
            has_pr=False,
        )
        assert status == "failed"
        assert outcome == "needs_review"
        assert error_code == "MAJOR_UPDATE_REQUIRED"


# ---------------------------------------------------------------------------
# llm_fix mode — no changes
# ---------------------------------------------------------------------------


class TestLlmFixNoChanges:
    """Outcome rows for llm_fix mode when update produces no changes."""

    def test_no_changes_no_major(self):
        """llm_fix + no changes + no major → succeeded / no_vulnerabilities."""
        status, outcome, error_code = determine_outcome(
            classified=[],
            params={"fix_mode": "llm_fix", "fail_on_findings": True},
            validation=None,
            has_pr=False,
            has_working_changes=False,
        )
        assert status == "succeeded"
        assert outcome == "no_vulnerabilities"
        assert error_code is None

    def test_no_changes_with_major(self):
        """llm_fix + no changes + major → failed / MAJOR_UPDATE_REQUIRED."""
        classified = [_make_advisory("major_required")]
        status, outcome, error_code = determine_outcome(
            classified=classified,
            params={"fix_mode": "llm_fix", "fail_on_findings": True},
            validation=None,
            has_pr=False,
            has_working_changes=False,
        )
        assert status == "failed"
        assert outcome == "needs_review"
        assert error_code == "MAJOR_UPDATE_REQUIRED"


# ---------------------------------------------------------------------------
# llm_fix mode — validation failure
# ---------------------------------------------------------------------------


class TestLlmFixValidationFailure:
    """Validation failure takes highest precedence."""

    def test_validation_failing(self):
        """llm_fix + validation failed → failed / VALIDATION_FAILING."""
        val = _failing_validation()
        status, outcome, error_code = determine_outcome(
            classified=[_make_advisory("in_range")],
            params={"fix_mode": "llm_fix", "fail_on_findings": True},
            validation=val,
            has_pr=False,
        )
        assert status == "failed"
        assert outcome == "needs_review"
        assert error_code == "VALIDATION_FAILING"

    def test_validation_failing_beats_major(self):
        """VALIDATION_FAILING > MAJOR_UPDATE_REQUIRED (req 42 first bullet)."""
        val = _failing_validation()
        classified = [_make_advisory("major_required")]
        status, outcome, error_code = determine_outcome(
            classified=classified,
            params={"fix_mode": "llm_fix", "fail_on_findings": True},
            validation=val,
            has_pr=False,
        )
        assert status == "failed"
        assert outcome == "needs_review"
        assert error_code == "VALIDATION_FAILING"


# ---------------------------------------------------------------------------
# llm_fix mode — PR idempotency
# ---------------------------------------------------------------------------


class TestLlmFixPrIdempotency:
    """PR already exists → not_applicable."""

    def test_pr_existed(self):
        """llm_fix + PR already open → succeeded / not_applicable."""
        val = _passing_validation()
        status, outcome, error_code = determine_outcome(
            classified=[],
            params={"fix_mode": "llm_fix", "fail_on_findings": True},
            validation=val,
            has_pr=False,
            pr_existed=True,
        )
        assert status == "succeeded"
        assert outcome == "not_applicable"
        assert error_code is None


# ---------------------------------------------------------------------------
# llm_fix mode — PR opened
# ---------------------------------------------------------------------------


class TestLlmFixPrOpened:
    """Outcomes after a PR is successfully opened."""

    def test_pr_opened_no_major(self):
        """llm_fix + PR opened + no major remaining → succeeded / fixed."""
        val = _passing_validation()
        status, outcome, error_code = determine_outcome(
            classified=[_make_advisory("in_range")],
            params={"fix_mode": "llm_fix", "fail_on_findings": True},
            validation=val,
            has_pr=True,
        )
        assert status == "succeeded"
        assert outcome == "fixed"
        assert error_code is None

    def test_pr_opened_with_major(self):
        """llm_fix + PR opened + major remaining → failed / MAJOR_UPDATE_REQUIRED (PR kept)."""
        val = _passing_validation()
        classified = [_make_advisory("major_required")]
        status, outcome, error_code = determine_outcome(
            classified=classified,
            params={"fix_mode": "llm_fix", "fail_on_findings": True},
            validation=val,
            has_pr=True,
        )
        assert status == "failed"
        assert outcome == "needs_review"
        assert error_code == "MAJOR_UPDATE_REQUIRED"

    def test_pr_opened_with_unknown(self):
        """llm_fix + PR opened + unknown advisories → succeeded / partial."""
        val = _passing_validation()
        classified = [_make_advisory("unknown")]
        status, outcome, error_code = determine_outcome(
            classified=classified,
            params={"fix_mode": "llm_fix", "fail_on_findings": True},
            validation=val,
            has_pr=True,
        )
        assert status == "succeeded"
        assert outcome == "partial"
        assert error_code is None

    def test_pr_opened_mixed_in_range_and_unknown(self):
        """llm_fix + PR opened + in_range + unknown → succeeded / partial."""
        val = _passing_validation()
        classified = [_make_advisory("in_range"), _make_advisory("unknown")]
        status, outcome, error_code = determine_outcome(
            classified=classified,
            params={"fix_mode": "llm_fix", "fail_on_findings": True},
            validation=val,
            has_pr=True,
        )
        assert status == "succeeded"
        assert outcome == "partial"
        assert error_code is None

    def test_pr_opened_only_in_range(self):
        """llm_fix + PR opened + only in_range → succeeded / fixed."""
        val = _passing_validation()
        classified = [_make_advisory("in_range"), _make_advisory("in_range")]
        status, outcome, error_code = determine_outcome(
            classified=classified,
            params={"fix_mode": "llm_fix", "fail_on_findings": True},
            validation=val,
            has_pr=True,
        )
        assert status == "succeeded"
        assert outcome == "fixed"
        assert error_code is None


# ---------------------------------------------------------------------------
# Precedence edge cases
# ---------------------------------------------------------------------------


class TestPrecedenceEdgeCases:
    """Cross-cutting precedence rules."""

    def test_major_beats_fixed_in_llm_fix(self):
        """MAJOR_UPDATE_REQUIRED takes precedence over fixed (req 42 second bullet)."""
        val = _passing_validation()
        classified = [_make_advisory("in_range"), _make_advisory("major_required")]
        status, outcome, error_code = determine_outcome(
            classified=classified,
            params={"fix_mode": "llm_fix", "fail_on_findings": True},
            validation=val,
            has_pr=True,
        )
        assert status == "failed"
        assert outcome == "needs_review"
        assert error_code == "MAJOR_UPDATE_REQUIRED"

    def test_validation_failing_beats_all(self):
        """VALIDATION_FAILING is the highest priority error_code."""
        val = _failing_validation()
        classified = [_make_advisory("major_required"), _make_advisory("in_range")]
        status, outcome, error_code = determine_outcome(
            classified=classified,
            params={"fix_mode": "llm_fix", "fail_on_findings": True},
            validation=val,
            has_pr=True,
        )
        assert status == "failed"
        assert outcome == "needs_review"
        assert error_code == "VALIDATION_FAILING"

    def test_empty_classified_with_pr(self):
        """llm_fix + PR opened + no advisories at all → succeeded / fixed."""
        val = _passing_validation()
        status, outcome, error_code = determine_outcome(
            classified=[],
            params={"fix_mode": "llm_fix", "fail_on_findings": True},
            validation=val,
            has_pr=True,
        )
        assert status == "succeeded"
        assert outcome == "fixed"
        assert error_code is None
