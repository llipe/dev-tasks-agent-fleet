"""
Unit tests for eligibility.py — version eligibility algorithm (D26).

Covers:
  - parse_semver: standard versions, v-prefix, pre-release, build metadata, non-semver
  - is_eligible: all 4 rows of the eligibility table + anti-loophole (req 34)
  - Edge cases: 0.x versions, pre-release strings, empty strings
"""

from __future__ import annotations

from eligibility import is_eligible, parse_semver

# ---------------------------------------------------------------------------
# parse_semver
# ---------------------------------------------------------------------------


class TestParseSemver:
    """Tests for parse_semver()."""

    def test_standard_version(self):
        assert parse_semver("1.2.3") == (1, 2, 3)

    def test_zero_major(self):
        assert parse_semver("0.1.2") == (0, 1, 2)

    def test_large_numbers(self):
        assert parse_semver("123.456.789") == (123, 456, 789)

    def test_v_prefix(self):
        assert parse_semver("v2.0.0") == (2, 0, 0)

    def test_v_prefix_lowercase(self):
        assert parse_semver("v1.5.10") == (1, 5, 10)

    def test_pre_release(self):
        assert parse_semver("2.0.0-beta.1") == (2, 0, 0)

    def test_pre_release_alpha(self):
        assert parse_semver("1.0.0-alpha.2") == (1, 0, 0)

    def test_build_metadata(self):
        assert parse_semver("1.0.0+build.123") == (1, 0, 0)

    def test_pre_release_and_build(self):
        assert parse_semver("1.0.0-rc.1+build.456") == (1, 0, 0)

    def test_non_semver_hash(self):
        assert parse_semver("abc123") is None

    def test_non_semver_date(self):
        assert parse_semver("20240101") is None

    def test_non_semver_partial(self):
        assert parse_semver("1.2") is None

    def test_non_semver_empty(self):
        assert parse_semver("") is None

    def test_non_semver_spaces_only(self):
        assert parse_semver("   ") is None

    def test_whitespace_trimmed(self):
        assert parse_semver("  1.2.3  ") == (1, 2, 3)

    def test_leading_zero_not_valid(self):
        """Leading zeros in numeric segments are not valid semver."""
        assert parse_semver("01.2.3") is None

    def test_zero_zero_zero(self):
        assert parse_semver("0.0.0") == (0, 0, 0)


# ---------------------------------------------------------------------------
# is_eligible — the 4-row eligibility table
# ---------------------------------------------------------------------------


class TestIsEligibleTable:
    """Tests for the core 4-row eligibility table (D26)."""

    def test_row1_patch_minor_eligible(self):
        """Patch/minor within same major → eligible."""
        eligible, reason = is_eligible("1.2.3", "1.3.0")
        assert eligible is True
        assert reason == "patch_or_minor"

    def test_row1_patch_only(self):
        eligible, reason = is_eligible("1.2.3", "1.2.4")
        assert eligible is True
        assert reason == "patch_or_minor"

    def test_row2_major_increase_ineligible(self):
        """Major increase → ineligible."""
        eligible, reason = is_eligible("1.2.3", "2.0.0")
        assert eligible is False
        assert reason == "major_increase"

    def test_row2_major_skip(self):
        """Major skip (1.x → 3.x) → ineligible."""
        eligible, reason = is_eligible("1.9.9", "3.0.0")
        assert eligible is False
        assert reason == "major_increase"

    def test_row3_zero_minor_increase_ineligible(self):
        """0.x minor increase = major-equivalent → ineligible."""
        eligible, reason = is_eligible("0.1.2", "0.2.0")
        assert eligible is False
        assert reason == "zero_minor_increase"

    def test_row3_zero_minor_skip(self):
        """0.x minor skip (0.1 → 0.5) → ineligible."""
        eligible, reason = is_eligible("0.1.9", "0.5.0")
        assert eligible is False
        assert reason == "zero_minor_increase"

    def test_row3_zero_patch_eligible(self):
        """0.x patch within same minor → eligible."""
        eligible, reason = is_eligible("0.1.2", "0.1.5")
        assert eligible is True
        assert reason == "patch_or_minor"

    def test_row4_both_non_semver(self):
        """Both non-semver → eligible (test suite is the gate)."""
        eligible, reason = is_eligible("abc123", "def456")
        assert eligible is True
        assert reason == "both_non_semver"


# ---------------------------------------------------------------------------
# is_eligible — anti-loophole (req 34)
# ---------------------------------------------------------------------------


class TestIsEligibleAntiLoophole:
    """Anti-loophole tests — req 34 edge cases."""

    def test_installed_non_semver_target_semver_accept(self):
        """Non-semver installed, semver target → cannot determine major, accept."""
        eligible, reason = is_eligible("abc123", "2.0.0")
        assert eligible is True
        assert reason == "installed_non_semver"

    def test_target_non_semver_installed_semver_accept(self):
        """Semver installed, non-semver target → accept."""
        eligible, reason = is_eligible("1.2.3", "abc456")
        assert eligible is True
        assert reason == "target_non_semver"

    def test_installed_non_semver_target_zero_major(self):
        """Non-semver installed, target 0.x → cannot determine, accept."""
        eligible, reason = is_eligible("xyz", "0.5.0")
        assert eligible is True
        assert reason == "installed_non_semver"


# ---------------------------------------------------------------------------
# is_eligible — edge cases
# ---------------------------------------------------------------------------


class TestIsEligibleEdgeCases:
    """Edge cases for is_eligible."""

    def test_same_version(self):
        """Same version → eligible (no-op update)."""
        eligible, reason = is_eligible("1.2.3", "1.2.3")
        assert eligible is True
        assert reason == "patch_or_minor"

    def test_downgrade_same_major(self):
        """Downgrade within same major → eligible (still patch_or_minor)."""
        eligible, reason = is_eligible("1.5.0", "1.2.0")
        assert eligible is True
        assert reason == "patch_or_minor"

    def test_pre_release_target(self):
        """Pre-release on target still parsed as semver for major comparison."""
        eligible, reason = is_eligible("1.2.3", "2.0.0-beta.1")
        assert eligible is False
        assert reason == "major_increase"

    def test_v_prefix_both(self):
        """v-prefix on both sides still works."""
        eligible, reason = is_eligible("v1.2.3", "v1.3.0")
        assert eligible is True
        assert reason == "patch_or_minor"

    def test_v_prefix_major_increase(self):
        eligible, reason = is_eligible("v1.9.0", "v2.0.0")
        assert eligible is False
        assert reason == "major_increase"

    def test_zero_to_one_major_increase(self):
        """0.x → 1.x is a major increase."""
        eligible, reason = is_eligible("0.9.9", "1.0.0")
        assert eligible is False
        assert reason == "major_increase"
