"""
Unit tests for the Finding/Remediation schema and fingerprinting (spec §8.1,
§8.2; PRD requirement 21/D18/D20, acceptance criterion 6).

Covers:
  - ``Finding``/``Remediation`` field shape (story S-127 AC1, task 3.3).
  - ``fingerprint()`` stability under a sub-tolerance-band line shift, and
    change on file/rule difference (PRD AC6, task 3.4).
  - EC-34: the line-shift boundary exactly at the tolerance band, asserted
    explicitly inclusive/exclusive rather than left implicit.
  - EC-35: an empty ``rule_id`` falls back to ``cwe_or_category``.
"""

from __future__ import annotations

import dataclasses
import hashlib

import pytest

from fingerprint import _LINE_TOLERANCE_BAND, fingerprint
from normalize import Finding, Remediation
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


# ---------------------------------------------------------------------------
# Finding / Remediation schema shape (spec §8.1, story S-127 AC1)
# ---------------------------------------------------------------------------


class TestFindingSchema:
    def test_finding_is_a_frozen_dataclass(self):
        assert dataclasses.is_dataclass(Finding)
        with pytest.raises(dataclasses.FrozenInstanceError):
            _make_finding().tool = "trivy"  # type: ignore[misc]

    def test_finding_field_names_and_order_match_spec_exactly(self):
        field_names = [f.name for f in dataclasses.fields(Finding)]
        assert field_names == [
            "tool",
            "rule_id",
            "severity",
            "file_path",
            "line_start",
            "line_end",
            "message",
            "cwe_or_category",
            "remediation",
            "raw_ref",
        ]

    def test_finding_severity_field_holds_the_normalized_enum(self):
        finding = _make_finding(severity=Severity.CRITICAL)
        assert finding.severity is Severity.CRITICAL

    def test_finding_remediation_field_accepts_none_for_unscannable_candidate(self):
        finding = _make_finding(remediation=None)
        assert finding.remediation is None


class TestRemediationSchema:
    def test_remediation_is_a_frozen_dataclass(self):
        assert dataclasses.is_dataclass(Remediation)
        remediation = Remediation(
            kind="semgrep_autofix",
            patch="--- a/app/main.py\n+++ b/app/main.py\n",
            target_version=None,
            lockfile_managed=False,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            remediation.kind = "structural"  # type: ignore[misc]

    def test_remediation_field_names_and_order_match_spec_exactly(self):
        # `current_version` was added by S-134 (see `normalize.py`'s
        # `Remediation` docstring) as an additive, defaulted-`None` trailing
        # field so `classifier.py`'s `_is_major_bump()` has a pre-fix
        # version to compare `target_version` against -- spec §8.4's own
        # pseudocode calls `_is_major_bump(f)` expecting exactly this, but
        # no prior story's schema carried it. Appending it after
        # `lockfile_managed` (rather than inserting it earlier) keeps every
        # existing keyword-argument `Remediation(...)` call site across the
        # four already-merged scanner normalizers valid unchanged.
        field_names = [f.name for f in dataclasses.fields(Remediation)]
        assert field_names == [
            "kind",
            "patch",
            "target_version",
            "lockfile_managed",
            "current_version",
        ]

    def test_remediation_optional_fields_accept_none(self):
        remediation = Remediation(
            kind="none", patch=None, target_version=None, lockfile_managed=False
        )
        assert remediation.patch is None
        assert remediation.target_version is None


# ---------------------------------------------------------------------------
# fingerprint() -- derived from (file_path, rule_id-or-category, banded line)
# (PRD requirement 21/D20, AC6)
# ---------------------------------------------------------------------------


class TestFingerprintDeterminism:
    def test_identical_findings_produce_identical_fingerprints(self):
        assert fingerprint(_make_finding()) == fingerprint(_make_finding())

    def test_fingerprint_is_a_16_char_hex_string(self):
        digest = fingerprint(_make_finding())
        assert len(digest) == 16
        int(digest, 16)  # raises ValueError if not hex

    def test_fingerprint_is_derived_from_named_fields_only(self):
        # Two findings differing only in message/raw_ref (not part of the
        # fingerprint key per spec §8.2) must fingerprint identically.
        a = _make_finding(message="Detected use of eval().", raw_ref="a.json#0")
        b = _make_finding(message="A completely different message.", raw_ref="b.json#7")
        assert fingerprint(a) == fingerprint(b)


class TestFingerprintStabilityUnderLineShift:
    """PRD AC6: a finding's fingerprint is stable when its line number
    shifts by less than the tolerance band due to an unrelated edit."""

    def test_stable_across_a_one_line_shift_within_the_same_band(self):
        # line_start=10 bands to 9 (10 - 10%3); line_start=11 also bands to
        # 9 (11 - 11%2... -> 11 - (11%3)=11-2=9) -- same band, same print.
        original = _make_finding(line_start=10)
        shifted = _make_finding(line_start=11)
        assert fingerprint(original) == fingerprint(shifted)

    def test_stable_when_already_on_a_band_boundary_and_shifted_by_one(self):
        # line_start=12 bands to 12 (12 - 12%3 = 12); line_start=13 bands to
        # 12 as well (13 - 13%3 = 13-1=12) -- same band.
        original = _make_finding(line_start=12)
        shifted = _make_finding(line_start=13)
        assert fingerprint(original) == fingerprint(shifted)


class TestFingerprintBoundaryOfToleranceBand:
    """EC-34: line shift exactly at the tolerance-band boundary (3 lines) --
    explicit inclusive/exclusive assertion, not left implicit."""

    def test_tolerance_band_constant_is_three_lines(self):
        assert _LINE_TOLERANCE_BAND == 3

    def test_shift_of_exactly_the_tolerance_band_crosses_into_a_new_band(self):
        # line_start=9 bands to 9 (start of its band); line_start=9+3=12
        # bands to 12 -- a different band, so the fingerprint MUST change.
        # This is the explicit boundary case: a shift of exactly
        # `_LINE_TOLERANCE_BAND` lines is NOT guaranteed to stay within the
        # tolerance band (bands are fixed-size buckets aligned to multiples
        # of the band size, not a sliding window centered on the original
        # line), so this is an "exclusive" boundary -- crossing, not merging.
        original = _make_finding(line_start=9)
        shifted = _make_finding(line_start=9 + _LINE_TOLERANCE_BAND)
        assert fingerprint(original) != fingerprint(shifted)

    def test_shift_of_one_less_than_the_tolerance_band_may_still_cross(self):
        # line_start=10 bands to 9; line_start=10+2=12 bands to 12 -- a
        # shift smaller than the band width can still cross a band edge,
        # because bands are fixed alignment buckets, not a rolling window.
        # This is the flip side of the boundary: "less than the tolerance
        # band" (PRD AC6's wording) is a necessary, not sufficient,
        # condition for stability -- it also depends on where the original
        # line sits within its band.
        original = _make_finding(line_start=10)
        shifted = _make_finding(line_start=12)
        assert fingerprint(original) != fingerprint(shifted)


class TestFingerprintChangesOnDifference:
    """PRD AC6: a finding's fingerprint changes when the file or rule
    changes."""

    def test_changes_when_file_path_differs(self):
        original = _make_finding(file_path="app/main.py")
        different_file = _make_finding(file_path="app/other.py")
        assert fingerprint(original) != fingerprint(different_file)

    def test_changes_when_rule_id_differs(self):
        original = _make_finding(rule_id="python.lang.security.audit.eval-detected")
        different_rule = _make_finding(rule_id="python.lang.security.audit.exec-detected")
        assert fingerprint(original) != fingerprint(different_rule)


class TestFingerprintEmptyRuleIdFallback:
    """EC-35: fingerprint with an empty ``rule_id`` falls back to
    ``cwe_or_category`` (spec §8.2's ``rule_id or cwe_or_category``)."""

    def test_empty_rule_id_falls_back_to_cwe_or_category(self):
        with_empty_rule_id = _make_finding(rule_id="", cwe_or_category="CWE-95")
        with_category_as_rule_id = _make_finding(rule_id="CWE-95", cwe_or_category="CWE-95")
        assert fingerprint(with_empty_rule_id) == fingerprint(with_category_as_rule_id)

    def test_empty_rule_id_with_different_category_differs_from_nonempty_rule_id_match(self):
        empty_rule_gitleaks_style = _make_finding(rule_id="", cwe_or_category="CWE-798")
        explicit_rule_id = _make_finding(rule_id="CWE-95", cwe_or_category="CWE-95")
        assert fingerprint(empty_rule_gitleaks_style) != fingerprint(explicit_rule_id)


class TestFingerprintKeyShape:
    """Directly exercises the key construction described in spec §8.2,
    without depending on hashlib internals beyond sha256 + truncation."""

    def test_key_matches_documented_format(self):
        finding = _make_finding(file_path="app/main.py", rule_id="eval-detected", line_start=10)
        banded_line = 10 - (10 % _LINE_TOLERANCE_BAND)
        expected_key = f"app/main.py::eval-detected::{banded_line}"
        expected_digest = hashlib.sha256(expected_key.encode()).hexdigest()[:16]
        assert fingerprint(finding) == expected_digest
