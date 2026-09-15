"""
Unit tests for severity normalization (spec S8.1a, PRD S7.4b / D28-D30,
acceptance criterion 12a).

One parametrized case per table row, per tool (task 2.9), plus the
unknown-severity-floor and CodeQL dual-fallback paths (task 2.7) and a
free-text-metadata-inspection guard (task 2.8).

Deviation from spec S8.1a, confirmed by planner (see task instructions for
S-126): ``severity_from_semgrep`` is implemented with the same defensive
``.get(..., floor)`` pattern the other four functions use, not the raw dict
indexing literally shown in the spec — the literal version raises
``KeyError`` on an out-of-table value instead of falling to
``_UNKNOWN_SEVERITY_FLOOR``, which the spec's own §7.4b requirement 58 table
implies is a total function ("MUST carry a normalized severity ... derived
per tool"). ``TestSemgrepIsTotal`` below is the regression guard for this
fix. ``severity_from_checkov``'s present-value branch has the identical
deviation (found by the S-126 fidelity audit); ``TestCheckovIsTotal`` is
its regression guard.
"""

from __future__ import annotations

import pytest

from severity import (
    _UNKNOWN_SEVERITY_FLOOR,
    Severity,
    severity_from_checkov,
    severity_from_codeql,
    severity_from_gitleaks,
    severity_from_semgrep,
    severity_from_trivy,
)


def test_unknown_severity_floor_is_medium():
    # D30 -- shared across all tools' "no signal" case.
    assert _UNKNOWN_SEVERITY_FLOOR == Severity.MEDIUM


# ---------------------------------------------------------------------------
# Semgrep -- ERROR -> high, WARNING -> medium, INFO -> low (req 58 table row 1)
# ---------------------------------------------------------------------------


class TestSeverityFromSemgrep:
    @pytest.mark.parametrize(
        ("raw_severity", "expected"),
        [
            ("ERROR", Severity.HIGH),
            ("WARNING", Severity.MEDIUM),
            ("INFO", Severity.LOW),
        ],
    )
    def test_table_row(self, raw_severity, expected):
        assert severity_from_semgrep(raw_severity) == expected

    def test_semgrep_never_yields_critical_on_its_own(self):
        # req 58 table note: Semgrep never yields critical on its own.
        for raw in ("ERROR", "WARNING", "INFO"):
            assert severity_from_semgrep(raw) != Severity.CRITICAL


class TestSemgrepIsTotal:
    """Regression guard for the S-125 fidelity-audit finding (RT-4):

    the spec's literal `{"ERROR": ...}[raw_severity]` dict-indexing form
    raises KeyError on an out-of-table value. This function must instead
    fall to the shared unknown-severity floor, exactly like the other four
    severity_from_* functions.
    """

    @pytest.mark.parametrize("raw_severity", ["", "UNKNOWN", "critical", "Error", "debug"])
    def test_out_of_table_value_falls_to_floor_not_keyerror(self, raw_severity):
        assert severity_from_semgrep(raw_severity) == _UNKNOWN_SEVERITY_FLOOR


# ---------------------------------------------------------------------------
# Gitleaks -- unconditional critical, no per-rule grading (D29, req 59)
# ---------------------------------------------------------------------------


class TestSeverityFromGitleaks:
    @pytest.mark.parametrize(
        "finding",
        [
            {},
            {"RuleID": "aws-access-key"},
            {"RuleID": "generic-high-entropy-string", "Severity": "low"},
        ],
    )
    def test_always_critical_regardless_of_finding_shape(self, finding):
        assert severity_from_gitleaks(finding) == Severity.CRITICAL


# ---------------------------------------------------------------------------
# Trivy -- direct 4-level pass-through, UNKNOWN -> medium floor (req 58 row 3)
# ---------------------------------------------------------------------------


class TestSeverityFromTrivy:
    @pytest.mark.parametrize(
        ("raw_severity", "expected"),
        [
            ("CRITICAL", Severity.CRITICAL),
            ("HIGH", Severity.HIGH),
            ("MEDIUM", Severity.MEDIUM),
            ("LOW", Severity.LOW),
        ],
    )
    def test_table_row(self, raw_severity, expected):
        assert severity_from_trivy(raw_severity) == expected

    def test_unknown_falls_to_shared_floor(self):
        assert severity_from_trivy("UNKNOWN") == _UNKNOWN_SEVERITY_FLOOR

    def test_out_of_table_value_falls_to_floor(self):
        assert severity_from_trivy("bogus") == _UNKNOWN_SEVERITY_FLOOR


# ---------------------------------------------------------------------------
# Checkov -- pass-through when present, medium when absent (req 58 row 4)
# ---------------------------------------------------------------------------


class TestSeverityFromCheckov:
    @pytest.mark.parametrize(
        ("raw_severity", "expected"),
        [
            ("CRITICAL", Severity.CRITICAL),
            ("HIGH", Severity.HIGH),
            ("MEDIUM", Severity.MEDIUM),
            ("LOW", Severity.LOW),
        ],
    )
    def test_table_row(self, raw_severity, expected):
        assert severity_from_checkov(raw_severity) == expected

    def test_absent_severity_is_the_common_oss_case_falling_to_floor(self):
        assert severity_from_checkov(None) == _UNKNOWN_SEVERITY_FLOOR


class TestCheckovIsTotal:
    """Regression guard for the S-126 fidelity-audit finding: the same
    class of deviation as TestSemgrepIsTotal above. Spec S8.1a's literal
    raw-indexing form would KeyError on an out-of-table non-None Checkov
    severity string; this function must instead fall to the shared
    unknown-severity floor, exactly like the other four severity_from_*
    functions.
    """

    @pytest.mark.parametrize("raw_severity", ["", "UNKNOWN", "critical", "Error", "informational"])
    def test_out_of_table_value_falls_to_floor_not_keyerror(self, raw_severity):
        assert severity_from_checkov(raw_severity) == _UNKNOWN_SEVERITY_FLOOR


# ---------------------------------------------------------------------------
# CodeQL -- security-severity thresholds -> SARIF level fallback -> medium
# (req 58 row 5, AC-12a dual fallback)
# ---------------------------------------------------------------------------


class TestSeverityFromCodeql:
    @pytest.mark.parametrize(
        ("security_severity", "expected"),
        [
            (9.5, Severity.CRITICAL),
            (9.0, Severity.CRITICAL),
            (8.9, Severity.HIGH),
            (7.0, Severity.HIGH),
            (6.9, Severity.MEDIUM),
            (4.0, Severity.MEDIUM),
            (3.9, Severity.LOW),
            (0.0, Severity.LOW),
        ],
    )
    def test_security_severity_thresholds(self, security_severity, expected):
        assert severity_from_codeql(security_severity, level=None) == expected

    def test_security_severity_takes_priority_over_level_when_both_present(self):
        assert severity_from_codeql(9.5, level="note") == Severity.CRITICAL

    @pytest.mark.parametrize(
        ("level", "expected"),
        [
            ("error", Severity.HIGH),
            ("warning", Severity.MEDIUM),
            ("note", Severity.LOW),
        ],
    )
    def test_level_fallback_when_no_security_severity(self, level, expected):
        assert severity_from_codeql(None, level=level) == expected

    def test_out_of_table_level_falls_to_floor(self):
        assert severity_from_codeql(None, level="bogus") == _UNKNOWN_SEVERITY_FLOOR

    def test_neither_signal_present_falls_to_shared_floor(self):
        # AC-12a dual fallback: neither security-severity nor a usable level.
        assert severity_from_codeql(None, None) == _UNKNOWN_SEVERITY_FLOOR


# ---------------------------------------------------------------------------
# req 61 -- no function inspects free-text rule metadata beyond named fields
# ---------------------------------------------------------------------------


class TestNoFreeTextMetadataInspection:
    """Each function's signature is the exhaustive list of fields it may
    consult (req 58's table); passing an unrelated free-text field alongside
    the named ones must have zero effect on the result.
    """

    def test_gitleaks_ignores_all_finding_content_including_message_text(self):
        base = severity_from_gitleaks({})
        with_message = severity_from_gitleaks(
            {"Description": "contains the word critical low severity test fixture"}
        )
        assert base == with_message == Severity.CRITICAL

    def test_semgrep_signature_takes_only_the_named_severity_field(self):
        import inspect

        params = list(inspect.signature(severity_from_semgrep).parameters)
        assert params == ["raw_severity"]

    def test_trivy_signature_takes_only_the_named_severity_field(self):
        import inspect

        params = list(inspect.signature(severity_from_trivy).parameters)
        assert params == ["raw_severity"]

    def test_checkov_signature_takes_only_the_named_severity_field(self):
        import inspect

        params = list(inspect.signature(severity_from_checkov).parameters)
        assert params == ["raw_severity"]

    def test_codeql_signature_takes_only_the_two_named_fields(self):
        import inspect

        params = list(inspect.signature(severity_from_codeql).parameters)
        assert params == ["security_severity", "level"]

    def test_gitleaks_signature_takes_only_the_finding_dict(self):
        import inspect

        params = list(inspect.signature(severity_from_gitleaks).parameters)
        assert params == ["_finding"]
