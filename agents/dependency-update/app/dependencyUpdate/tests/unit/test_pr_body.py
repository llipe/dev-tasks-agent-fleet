"""
Unit tests for the PR body builder (`pull_request.build_pr_body`) and its
section helpers (spec §8.9, req 55-56).

Covered:
  - All sections present when data is supplied.
  - Optional sections omitted when their inputs are empty.
  - Always-present sections (security summary, package changes, validation).
  - Package changes table capped at 30 rows with an overflow note.
  - AI warning present only when llm_used, and carries the attempt count.
  - Branch name format (deps/update-YYYYMMDD-HHMMSS).
  - Markdown cell escaping for pipe/newline in advisory titles.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pull_request as pr
from audit import PackageChange
from classifier import ClassifiedAdvisory
from validator import CheckStatus, ValidationResult

# ---------------------------------------------------------------------------
# Builders for test data
# ---------------------------------------------------------------------------


def _adv(
    module: str, bucket: str, title: str = "t", patched: str = ">=1.2.3"
) -> ClassifiedAdvisory:
    return ClassifiedAdvisory(
        id=1,
        module=module,
        severity="high",
        title=title,
        url="https://example.test/adv",
        patched_versions=patched,
        bucket=bucket,
    )


def _change(name: str, old: str | None, new: str | None, action: str = "updated") -> PackageChange:
    return PackageChange(name=name, action=action, old_version=old, new_version=new)


def _validation(**checks: CheckStatus) -> ValidationResult:
    result = ValidationResult()
    for name, status in checks.items():
        result.record(name, status, "")
    return result


def _full_validation() -> ValidationResult:
    return _validation(
        lint=CheckStatus.PASSED,
        format=CheckStatus.SKIPPED,
        typecheck=CheckStatus.PASSED,
        test=CheckStatus.PASSED,
    )


# ---------------------------------------------------------------------------
# Branch naming (req 53)
# ---------------------------------------------------------------------------


class TestBranchName:
    def test_format(self):
        dt = datetime(2026, 8, 27, 14, 2, 7, tzinfo=UTC)
        assert pr.branch_name(dt) == "deps/update-20260827-140207"

    def test_prefix(self):
        assert pr.branch_name().startswith("deps/update-")


# ---------------------------------------------------------------------------
# Full body — all sections present
# ---------------------------------------------------------------------------


class TestFullBody:
    def _build(self) -> str:
        return pr.build_pr_body(
            vuln_before=5,
            vuln_after=2,
            fixed_advisories=[_adv("lodash", "in_range")],
            major_required=[_adv("left-pad", "major_required")],
            unknown_advisories=[_adv("mystery", "unknown", patched="")],
            non_semver_changes=[_change("weirdpkg", "1.0.0", "git-abc123")],
            upgraded=[_change("lodash", "4.17.0", "4.17.21")],
            validation=_full_validation(),
            llm_used=True,
            fix_attempts=2,
        )

    def test_all_sections_present(self):
        body = self._build()
        assert "## Security Summary" in body
        assert "## Fixed Advisories" in body
        assert "Major Version Required" in body
        assert "## Unresolved Advisories" in body
        assert "## Non-semver Version Changes" in body
        assert "## Package Changes" in body
        assert "## Validation Results" in body
        assert "AI-Assisted Modifications" in body

    def test_security_counts_rendered(self):
        body = self._build()
        assert "| Vulnerabilities before | 5 |" in body
        assert "| Vulnerabilities after | 2 |" in body
        assert "| Advisories fixed | 1 |" in body

    def test_footer_present(self):
        body = self._build()
        assert body.rstrip().endswith("Review before merging.*")


# ---------------------------------------------------------------------------
# Optional sections omitted
# ---------------------------------------------------------------------------


class TestOmittedSections:
    def _minimal(self, **overrides) -> str:
        kwargs: dict = {
            "vuln_before": 0,
            "vuln_after": 0,
            "fixed_advisories": [],
            "major_required": [],
            "unknown_advisories": [],
            "non_semver_changes": [],
            "upgraded": [],
            "validation": _full_validation(),
            "llm_used": False,
            "fix_attempts": 0,
        }
        kwargs.update(overrides)
        return pr.build_pr_body(**kwargs)

    def test_no_optional_sections(self):
        body = self._minimal()
        assert "## Fixed Advisories" not in body
        assert "Major Version Required" not in body
        assert "## Unresolved Advisories" not in body
        assert "## Non-semver Version Changes" not in body
        assert "AI-Assisted Modifications" not in body

    def test_always_present_sections(self):
        body = self._minimal()
        assert "## Security Summary" in body
        assert "## Package Changes" in body
        assert "## Validation Results" in body

    def test_empty_package_changes_message(self):
        body = self._minimal()
        assert "_No package changes._" in body

    def test_fixed_section_appears_when_present(self):
        body = self._minimal(fixed_advisories=[_adv("lodash", "in_range")])
        assert "## Fixed Advisories" in body
        assert "lodash" in body

    def test_major_section_appears_when_present(self):
        body = self._minimal(major_required=[_adv("left-pad", "major_required")])
        assert "Major Version Required" in body
        assert "left-pad" in body


# ---------------------------------------------------------------------------
# Package changes cap (req 56)
# ---------------------------------------------------------------------------


class TestPackageChangesCap:
    def _many(self, n: int) -> str:
        changes = [_change(f"pkg{i}", "1.0.0", "1.0.1") for i in range(n)]
        return pr.build_pr_body(
            vuln_before=0,
            vuln_after=0,
            fixed_advisories=[],
            major_required=[],
            unknown_advisories=[],
            non_semver_changes=[],
            upgraded=changes,
            validation=_full_validation(),
            llm_used=False,
            fix_attempts=0,
        )

    def test_caps_at_30_rows(self):
        body = self._many(45)
        # pkg0..pkg29 shown, pkg30+ not shown
        assert "pkg29" in body
        assert "pkg30 " not in body and "| pkg30 |" not in body
        assert "and 15 more package change(s)" in body

    def test_exactly_30_no_overflow_note(self):
        body = self._many(30)
        assert "| pkg29 |" in body
        assert "more package change(s)" not in body

    def test_under_cap_all_shown(self):
        body = self._many(3)
        assert "| pkg0 |" in body
        assert "| pkg2 |" in body
        assert "more package change(s)" not in body


# ---------------------------------------------------------------------------
# AI warning (req 56)
# ---------------------------------------------------------------------------


class TestAiWarning:
    def _build(self, llm_used: bool, attempts: int) -> str:
        return pr.build_pr_body(
            vuln_before=1,
            vuln_after=0,
            fixed_advisories=[],
            major_required=[],
            unknown_advisories=[],
            non_semver_changes=[],
            upgraded=[_change("lodash", "4.0.0", "4.0.1")],
            validation=_full_validation(),
            llm_used=llm_used,
            fix_attempts=attempts,
        )

    def test_warning_present_when_llm_used(self):
        body = self._build(llm_used=True, attempts=3)
        assert "AI-Assisted Modifications" in body
        assert "**3**" in body

    def test_warning_absent_when_not_used(self):
        body = self._build(llm_used=False, attempts=0)
        assert "AI-Assisted Modifications" not in body


# ---------------------------------------------------------------------------
# Validation table
# ---------------------------------------------------------------------------


class TestValidationTable:
    def test_renders_each_status(self):
        validation = _validation(
            lint=CheckStatus.PASSED,
            format=CheckStatus.FAILED,
            typecheck=CheckStatus.SKIPPED,
            test=CheckStatus.PASSED,
        )
        table = pr._validation_table(validation)
        assert "| lint |" in table
        assert "passed" in table
        assert "failed" in table
        assert "skipped" in table

    def test_canonical_order(self):
        validation = _validation(
            test=CheckStatus.PASSED,
            lint=CheckStatus.PASSED,
        )
        table = pr._validation_table(validation)
        assert table.index("| lint |") < table.index("| test |")


# ---------------------------------------------------------------------------
# Markdown escaping
# ---------------------------------------------------------------------------


class TestMarkdownEscaping:
    def test_pipe_in_title_escaped(self):
        body = pr.build_pr_body(
            vuln_before=1,
            vuln_after=0,
            fixed_advisories=[_adv("pkg", "in_range", title="a | b")],
            major_required=[],
            unknown_advisories=[],
            non_semver_changes=[],
            upgraded=[],
            validation=_full_validation(),
            llm_used=False,
            fix_attempts=0,
        )
        assert "a \\| b" in body

    def test_newline_in_title_flattened(self):
        cell = pr._md_cell("line1\nline2")
        assert "\n" not in cell
        assert cell == "line1 line2"
