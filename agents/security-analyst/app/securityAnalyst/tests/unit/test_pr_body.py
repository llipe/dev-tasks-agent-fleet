"""
Unit tests for the PR body builder (`pull_request.build_pr_body`) and its
section helpers (spec §8.9, PRD requirement 42, story S-139).

Fixtures build synthetic `pull_request.PipelineState` values per the task
list's own scenario set: no-LLM, LLM-used, D24-boundary present,
major-version-guard present, zero-remaining, and all-sections-simultaneously.

Covered:
  - Always-present sections (summary, fixed findings, remaining-manual,
    re-scan confirmation) render even when their backing lists are empty —
    the remaining-manual table specifically keeps its header/table
    structure with zero rows (req 42's "no false all-clear", AC groundwork
    for SC-46 / CT-13).
  - Conditional sections (D24-boundary, major-version-guard, AI warning)
    appear only when their inputs are non-empty / `llm_used=True`.
  - Branch name format (`security/fix-YYYYMMDD-HHMMSS`).
  - Markdown cell escaping for pipe/newline in finding messages.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pull_request as pr
from dedupe import MergedFinding
from normalize import Finding, Remediation
from severity import Severity

# ---------------------------------------------------------------------------
# Builders for test data
# ---------------------------------------------------------------------------


def _finding(
    tool: str = "semgrep",
    rule_id: str = "rule-1",
    severity: Severity = Severity.HIGH,
    file_path: str = "src/app.py",
    line_start: int = 10,
    line_end: int = 10,
    message: str = "a finding",
    cwe_or_category: str = "CWE-79",
    remediation: Remediation | None = None,
    raw_ref: str = "ref-1",
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


def _merged(finding: Finding, reported_by: tuple[str, ...] = ("semgrep",)) -> MergedFinding:
    return MergedFinding(finding=finding, reported_by=reported_by)


def _bump_remediation(current: str, target: str) -> Remediation:
    return Remediation(
        kind="version_bump",
        patch=None,
        target_version=target,
        lockfile_managed=False,
        current_version=current,
        package_name="left-pad",
    )


def _state(**overrides) -> pr.PipelineState:
    kwargs: dict = {"findings_before": 0}
    kwargs.update(overrides)
    return pr.PipelineState(**kwargs)


# ---------------------------------------------------------------------------
# Branch naming (req 38)
# ---------------------------------------------------------------------------


class TestBranchName:
    def test_format(self):
        dt = datetime(2026, 9, 15, 3, 4, 5, tzinfo=UTC)
        assert pr.branch_name(dt) == "security/fix-20260915-030405"

    def test_prefix(self):
        assert pr.branch_name().startswith("security/fix-")


# ---------------------------------------------------------------------------
# Always-present sections — zero-remaining fixture
# ---------------------------------------------------------------------------


class TestZeroRemaining:
    def _build(self) -> str:
        state = _state(
            findings_before=0,
            fixed=[],
            manual_remaining=[],
            unscannable_remaining=[],
            rescan_before_count=0,
            rescan_after_count=0,
        )
        return pr.build_pr_body(state)

    def test_always_present_sections_render(self):
        body = self._build()
        assert "## Summary" in body
        assert "## Fixed Findings" in body
        assert "## Remaining Findings (Manual Review Required)" in body
        assert "Re-scan confirmation" in body

    def test_remaining_manual_table_structure_present_even_when_empty(self):
        """AC groundwork (SC-46/CT-13): the remaining-manual table's header
        and column structure MUST still be present with zero rows, not
        omitted — a green PR must not read as "all clear"."""
        body = self._build()
        assert "| Bucket | Tool | Rule | File | Severity | Description |" in body
        assert "| (none) | — | — | — | — | — |" in body

    def test_fixed_table_placeholder_row_when_empty(self):
        body = self._build()
        assert "| (none) | — | — | — | — |" in body

    def test_no_conditional_sections(self):
        body = self._build()
        assert "D24 boundary" not in body
        assert "Major Version Required" not in body
        assert "AI-Assisted Modifications" not in body


# ---------------------------------------------------------------------------
# No-LLM fixture — fixed findings present, no LLM
# ---------------------------------------------------------------------------


class TestNoLlm:
    def _build(self) -> str:
        fixed = [_merged(_finding(rule_id="fixed-1", message="pipe | newline\nhere"))]
        state = _state(
            findings_before=3,
            fixed=fixed,
            manual_remaining=[_merged(_finding(rule_id="manual-1", severity=Severity.MEDIUM))],
            unscannable_remaining=[_merged(_finding(rule_id="unscan-1", severity=Severity.LOW))],
            llm_used=False,
            rescan_before_count=3,
            rescan_after_count=2,
        )
        return pr.build_pr_body(state)

    def test_summary_counts_rendered(self):
        body = self._build()
        assert "| Findings before | 3 |" in body
        assert "| Findings fixed | 1 |" in body
        assert "| Remaining — manual | 1 |" in body
        assert "| Remaining — unscannable | 1 |" in body

    def test_fixed_findings_table_has_row(self):
        body = self._build()
        assert "fixed-1" in body

    def test_remaining_manual_table_groups_both_buckets(self):
        body = self._build()
        assert "| manual |" in body
        assert "| unscannable |" in body
        assert "manual-1" in body
        assert "unscan-1" in body

    def test_no_ai_warning(self):
        body = self._build()
        assert "AI-Assisted Modifications" not in body

    def test_rescan_confirmation_counts(self):
        body = self._build()
        assert "3 finding(s) before the fix, 2 finding(s) after" in body

    def test_markdown_escaping(self):
        body = self._build()
        assert "pipe \\| newline here" in body


# ---------------------------------------------------------------------------
# LLM-used fixture
# ---------------------------------------------------------------------------


class TestLlmUsed:
    def _build(self) -> str:
        llm_finding = _merged(_finding(rule_id="llm-1", file_path="src/llm.py"))
        state = _state(
            findings_before=1,
            fixed=[llm_finding],
            llm_used=True,
            llm_fixed=[llm_finding],
            rescan_before_count=1,
            rescan_after_count=0,
        )
        return pr.build_pr_body(state)

    def test_ai_warning_present(self):
        body = self._build()
        assert "AI-Assisted Modifications" in body

    def test_ai_warning_names_findings(self):
        body = self._build()
        assert "llm-1" in body
        assert "src/llm.py" in body


# ---------------------------------------------------------------------------
# D24-boundary fixture
# ---------------------------------------------------------------------------


class TestDependencyUpdateBoundary:
    def _build(self, boundary_findings) -> str:
        state = _state(
            findings_before=2,
            manual_remaining=boundary_findings,
            dependency_update_boundary=boundary_findings,
        )
        return pr.build_pr_body(state)

    def test_section_present_when_boundary_findings_exist(self):
        boundary = [
            _merged(
                _finding(
                    tool="trivy",
                    rule_id="CVE-2026-1",
                    remediation=Remediation(
                        kind="version_bump",
                        patch=None,
                        target_version="2.0.0",
                        lockfile_managed=True,
                        current_version="1.0.0",
                    ),
                )
            )
        ]
        body = self._build(boundary)
        assert "Owned by `dependency-update` (D24 boundary)" in body
        assert "CVE-2026-1" in body

    def test_section_absent_when_no_boundary_findings(self):
        body = self._build([])
        assert "D24 boundary" not in body


# ---------------------------------------------------------------------------
# Major-version-guard fixture
# ---------------------------------------------------------------------------


class TestMajorVersionGuard:
    def _build(self, guard_findings) -> str:
        state = _state(
            findings_before=1,
            manual_remaining=guard_findings,
            major_version_guard=guard_findings,
        )
        return pr.build_pr_body(state)

    def test_section_present_when_guard_findings_exist(self):
        guard = [
            _merged(
                _finding(
                    tool="trivy",
                    rule_id="CVE-2026-2",
                    remediation=_bump_remediation("1.0.0", "2.0.0"),
                )
            )
        ]
        body = self._build(guard)
        assert "Major Version Required" in body
        assert "CVE-2026-2" in body
        assert "1.0.0" in body
        assert "2.0.0" in body

    def test_section_absent_when_no_guard_findings(self):
        body = self._build([])
        assert "Major Version Required" not in body

    def test_unknown_versions_do_not_crash(self):
        guard = [
            _merged(
                _finding(
                    tool="trivy",
                    rule_id="CVE-2026-3",
                    remediation=Remediation(
                        kind="version_bump",
                        patch=None,
                        target_version=None,
                        lockfile_managed=False,
                        current_version=None,
                    ),
                )
            )
        ]
        body = self._build(guard)
        assert "(unknown)" in body


# ---------------------------------------------------------------------------
# All sections simultaneously
# ---------------------------------------------------------------------------


class TestAllSectionsSimultaneously:
    def _build(self) -> str:
        fixed_finding = _merged(_finding(rule_id="fixed-1"))
        llm_finding = _merged(_finding(rule_id="llm-fixed-1"))
        boundary_finding = _merged(
            _finding(
                tool="trivy",
                rule_id="boundary-1",
                remediation=Remediation(
                    kind="version_bump",
                    patch=None,
                    target_version="2.0.0",
                    lockfile_managed=True,
                    current_version="1.0.0",
                ),
            )
        )
        guard_finding = _merged(
            _finding(
                tool="trivy",
                rule_id="guard-1",
                remediation=_bump_remediation("1.0.0", "3.0.0"),
            )
        )
        unscannable_finding = _merged(_finding(rule_id="unscannable-1", severity=Severity.LOW))

        state = _state(
            findings_before=6,
            fixed=[fixed_finding, llm_finding],
            manual_remaining=[boundary_finding, guard_finding],
            unscannable_remaining=[unscannable_finding],
            dependency_update_boundary=[boundary_finding],
            major_version_guard=[guard_finding],
            llm_used=True,
            llm_fixed=[llm_finding],
            rescan_before_count=6,
            rescan_after_count=3,
        )
        return pr.build_pr_body(state)

    def test_every_section_present(self):
        body = self._build()
        assert "## Summary" in body
        assert "## Fixed Findings" in body
        assert "## Remaining Findings (Manual Review Required)" in body
        assert "Owned by `dependency-update` (D24 boundary)" in body
        assert "Major Version Required" in body
        assert "AI-Assisted Modifications" in body
        assert "Re-scan confirmation" in body

    def test_section_order(self):
        """Spec §8.9's pseudocode order: summary, fixed, remaining-manual,
        [boundary], [major-version-guard], [AI warning], re-scan line
        (always last)."""
        body = self._build()
        idx_summary = body.index("## Summary")
        idx_fixed = body.index("## Fixed Findings")
        idx_remaining = body.index("## Remaining Findings")
        idx_boundary = body.index("D24 boundary")
        idx_guard = body.index("Major Version Required")
        idx_ai = body.index("AI-Assisted Modifications")
        idx_rescan = body.index("Re-scan confirmation")
        assert (
            idx_summary < idx_fixed < idx_remaining < idx_boundary < idx_guard < idx_ai < idx_rescan
        )
        assert idx_rescan == max(
            idx_summary, idx_fixed, idx_remaining, idx_boundary, idx_guard, idx_ai, idx_rescan
        )

    def test_findings_named_in_each_section(self):
        body = self._build()
        assert "fixed-1" in body
        assert "boundary-1" in body
        assert "guard-1" in body
        assert "unscannable-1" in body
        assert "llm-fixed-1" in body
