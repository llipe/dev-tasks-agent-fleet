"""
Unit tests for cross-tool deduplication (spec §8.3, PRD requirement 22 / D19,
story S-133, acceptance criteria 7-8).

Covers:
  - AC7: a same-resource finding reported by two tools merges into one
    ``MergedFinding`` naming both tools.
  - AC8: two distinct findings (same file, different line, different
    category) stay separate.
  - The conservative merge boundary in both directions -- things that SHOULD
    merge and near-miss cases that must NOT merge: same line but different
    category, and same category but non-overlapping lines.
  - Three-way (chained) line-range overlap merges into a single record.
  - Representative-record selection: highest-severity contributor wins,
    with a deterministic tie-break; ``reported_by`` retains every
    contributing tool, deduplicated, order-preserving.
"""

from __future__ import annotations

import dataclasses

import pytest

from dedupe import MergedFinding, _merge_overlapping_by_line, dedupe
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
# MergedFinding schema shape
# ---------------------------------------------------------------------------


class TestMergedFindingSchema:
    def test_merged_finding_is_a_frozen_dataclass(self):
        assert dataclasses.is_dataclass(MergedFinding)
        finding = _make_finding()
        merged = MergedFinding(finding=finding, reported_by=("semgrep",))
        with pytest.raises(dataclasses.FrozenInstanceError):
            merged.reported_by = ("trivy",)  # type: ignore[misc]

    def test_merged_finding_field_names_match_spec(self):
        field_names = [f.name for f in dataclasses.fields(MergedFinding)]
        assert field_names == ["finding", "reported_by"]


# ---------------------------------------------------------------------------
# AC7 -- same-resource finding from two tools merges into one record naming
# both tools
# ---------------------------------------------------------------------------


class TestMergeCase:
    def test_overlapping_lines_same_category_merges_into_one_record(self):
        semgrep_finding = _make_finding(
            tool="semgrep",
            cwe_or_category="CWE-798",
            file_path="app/config.py",
            line_start=20,
            line_end=20,
            severity=Severity.HIGH,
        )
        gitleaks_finding = _make_finding(
            tool="gitleaks",
            cwe_or_category="CWE-798",
            file_path="app/config.py",
            line_start=20,
            line_end=20,
            severity=Severity.CRITICAL,
        )
        result = dedupe([semgrep_finding, gitleaks_finding])
        assert len(result) == 1
        assert set(result[0].reported_by) == {"semgrep", "gitleaks"}

    def test_merged_representative_uses_highest_severity_contributor(self):
        # AC7 + task 9.2 -- gitleaks (CRITICAL) must win over semgrep (HIGH)
        # as the representative record, even though semgrep appears first.
        semgrep_finding = _make_finding(
            tool="semgrep",
            cwe_or_category="CWE-798",
            file_path="app/config.py",
            line_start=20,
            line_end=20,
            severity=Severity.HIGH,
            message="semgrep message",
        )
        gitleaks_finding = _make_finding(
            tool="gitleaks",
            cwe_or_category="CWE-798",
            file_path="app/config.py",
            line_start=20,
            line_end=20,
            severity=Severity.CRITICAL,
            message="gitleaks message",
        )
        result = dedupe([semgrep_finding, gitleaks_finding])
        assert len(result) == 1
        assert result[0].finding.severity is Severity.CRITICAL
        assert result[0].finding.tool == "gitleaks"
        assert result[0].finding.message == "gitleaks message"

    def test_partial_line_range_overlap_merges(self):
        # Ranges [10,12] and [11,14] overlap without either containing the
        # other's start.
        a = _make_finding(tool="trivy", line_start=10, line_end=12)
        b = _make_finding(tool="checkov", line_start=11, line_end=14)
        result = dedupe([a, b])
        assert len(result) == 1
        assert set(result[0].reported_by) == {"trivy", "checkov"}

    def test_touching_line_ranges_merge(self):
        # Ranges [10,12] and [12,15] touch at line 12 -- treated as overlap.
        a = _make_finding(tool="trivy", line_start=10, line_end=12)
        b = _make_finding(tool="checkov", line_start=12, line_end=15)
        result = dedupe([a, b])
        assert len(result) == 1

    def test_same_severity_tie_break_keeps_first_contributor_as_representative(self):
        first = _make_finding(
            tool="semgrep", severity=Severity.HIGH, line_start=10, line_end=10, message="first"
        )
        second = _make_finding(
            tool="trivy", severity=Severity.HIGH, line_start=10, line_end=10, message="second"
        )
        result = dedupe([first, second])
        assert len(result) == 1
        assert result[0].finding.tool == "semgrep"
        assert result[0].finding.message == "first"


class TestThreeWayOverlap:
    def test_chained_overlap_merges_into_a_single_record(self):
        # A [10,12], B [11,14], C [13,16]: A overlaps B, B overlaps C, but A
        # and C do NOT directly overlap (12 < 13). The conservative-merge
        # chain must still collapse all three into one MergedFinding.
        a = _make_finding(tool="semgrep", line_start=10, line_end=12, severity=Severity.LOW)
        b = _make_finding(tool="trivy", line_start=11, line_end=14, severity=Severity.MEDIUM)
        c = _make_finding(tool="checkov", line_start=13, line_end=16, severity=Severity.HIGH)
        result = dedupe([a, b, c])
        assert len(result) == 1
        assert set(result[0].reported_by) == {"semgrep", "trivy", "checkov"}
        assert result[0].finding.severity is Severity.HIGH

    def test_three_findings_where_only_first_two_overlap_produce_two_records(self):
        # A [10,12], B [11,13] overlap; C [20,22] does not overlap either --
        # must remain a distinct record, not swept into the merge.
        a = _make_finding(tool="semgrep", line_start=10, line_end=12)
        b = _make_finding(tool="trivy", line_start=11, line_end=13)
        c = _make_finding(tool="checkov", line_start=20, line_end=22)
        result = dedupe([a, b, c])
        assert len(result) == 2
        reported_by_sets = {frozenset(m.reported_by) for m in result}
        assert frozenset({"semgrep", "trivy"}) in reported_by_sets
        assert frozenset({"checkov"}) in reported_by_sets


# ---------------------------------------------------------------------------
# AC8 -- two distinct findings (same file, different line, different
# category) stay separate, plus additional conservative near-miss cases.
# ---------------------------------------------------------------------------


class TestNoMergeCase:
    def test_same_file_different_line_different_category_stays_separate(self):
        # PRD AC8 exactly.
        a = _make_finding(
            file_path="app/main.py",
            cwe_or_category="CWE-95",
            line_start=10,
            line_end=10,
        )
        b = _make_finding(
            file_path="app/main.py",
            cwe_or_category="CWE-798",
            line_start=40,
            line_end=40,
        )
        result = dedupe([a, b])
        assert len(result) == 2

    def test_same_line_different_category_does_not_merge(self):
        # Near-miss: identical file+line, but category differs -- grouping
        # key requires BOTH file+line overlap AND category match, so this
        # must stay separate even though the lines coincide exactly.
        a = _make_finding(
            file_path="app/main.py",
            cwe_or_category="CWE-95",
            line_start=10,
            line_end=10,
        )
        b = _make_finding(
            file_path="app/main.py",
            cwe_or_category="CWE-798",
            line_start=10,
            line_end=10,
        )
        result = dedupe([a, b])
        assert len(result) == 2

    def test_same_category_non_overlapping_lines_does_not_merge(self):
        # Near-miss: same file+category (same group), but the line ranges
        # do not overlap -- must stay separate records within the group.
        a = _make_finding(
            file_path="app/main.py",
            cwe_or_category="CWE-95",
            line_start=10,
            line_end=10,
        )
        b = _make_finding(
            file_path="app/main.py",
            cwe_or_category="CWE-95",
            line_start=50,
            line_end=50,
        )
        result = dedupe([a, b])
        assert len(result) == 2

    def test_same_category_and_line_different_file_does_not_merge(self):
        a = _make_finding(file_path="app/main.py", line_start=10, line_end=10)
        b = _make_finding(file_path="app/other.py", line_start=10, line_end=10)
        result = dedupe([a, b])
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Tool-identifier retention semantics
# ---------------------------------------------------------------------------


class TestReportedByRetention:
    def test_single_tool_finding_reported_by_has_one_entry(self):
        result = dedupe([_make_finding(tool="semgrep")])
        assert result[0].reported_by == ("semgrep",)

    def test_reported_by_deduplicates_same_tool_reporting_twice(self):
        # Defensive: two overlapping findings from the SAME tool (e.g. two
        # semgrep rules mapped to the same category) must not duplicate the
        # tool name in reported_by.
        a = _make_finding(tool="semgrep", line_start=10, line_end=10)
        b = _make_finding(tool="semgrep", line_start=10, line_end=11)
        result = dedupe([a, b])
        assert len(result) == 1
        assert result[0].reported_by == ("semgrep",)

    def test_reported_by_preserves_first_appearance_order(self):
        a = _make_finding(tool="checkov", line_start=10, line_end=10)
        b = _make_finding(tool="trivy", line_start=10, line_end=11)
        result = dedupe([a, b])
        assert result[0].reported_by == ("checkov", "trivy")


# ---------------------------------------------------------------------------
# Empty input / single-finding pass-through
# ---------------------------------------------------------------------------


class TestEmptyAndSingleton:
    def test_empty_input_returns_empty_list(self):
        assert dedupe([]) == []

    def test_single_finding_passes_through_unmerged(self):
        finding = _make_finding()
        result = dedupe([finding])
        assert len(result) == 1
        assert result[0].finding == finding
        assert result[0].reported_by == ("semgrep",)


# ---------------------------------------------------------------------------
# _merge_overlapping_by_line -- exercised directly (spec §8.3 helper)
# ---------------------------------------------------------------------------


class TestMergeOverlappingByLineDirectly:
    def test_unsorted_input_still_merges_correctly(self):
        # The helper must not depend on caller-supplied ordering.
        b = _make_finding(tool="trivy", line_start=11, line_end=14)
        a = _make_finding(tool="semgrep", line_start=10, line_end=12)
        result = _merge_overlapping_by_line([b, a])
        assert len(result) == 1
        assert set(result[0].reported_by) == {"semgrep", "trivy"}

    def test_empty_group_returns_empty_list(self):
        assert _merge_overlapping_by_line([]) == []
