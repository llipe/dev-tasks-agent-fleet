"""
Unit tests for classifier.py — advisory classification (D25).

Covers:
  - _extract_lowest_version: >=X.Y.Z patterns, fallback, empty, complex ranges
  - ClassifiedAdvisory dataclass
  - classify_advisory: major_required, in_range, unknown (all reasons)
  - 0.x cases, complex patched ranges, no CVEs
"""

from __future__ import annotations

from classifier import _extract_lowest_version, classify_advisory

# ---------------------------------------------------------------------------
# _extract_lowest_version
# ---------------------------------------------------------------------------


class TestExtractLowestVersion:
    """Tests for naive version extraction from patched ranges."""

    def test_simple_gte(self):
        assert _extract_lowest_version(">=5.0.0") == "5.0.0"

    def test_gte_with_upper_bound(self):
        assert _extract_lowest_version(">=4.17.21 <5.0.0") == "4.17.21"

    def test_gt_without_equals(self):
        """Greater-than without equals still matches."""
        assert _extract_lowest_version(">3.0.0") == "3.0.0"

    def test_multiple_ranges_or(self):
        """Multiple OR ranges — picks the first."""
        assert _extract_lowest_version(">=2.0.0 || >=3.0.0") == "2.0.0"

    def test_pre_release_in_bound(self):
        assert _extract_lowest_version(">=1.0.0-alpha.1") == "1.0.0-alpha.1"

    def test_fallback_plain_version(self):
        """No >= prefix but version-like string present."""
        assert _extract_lowest_version("~4.17.21") == "4.17.21"

    def test_empty_string(self):
        assert _extract_lowest_version("") is None

    def test_no_version_at_all(self):
        assert _extract_lowest_version("no fix available") is None

    def test_less_than_only(self):
        """<0.0.0 style range — fallback to version-like string."""
        assert _extract_lowest_version("<0.0.0") == "0.0.0"

    def test_complex_npm_range(self):
        """Complex range from npm: >=4.17.21 <5.0.0 || >=5.0.1."""
        assert _extract_lowest_version(">=4.17.21 <5.0.0 || >=5.0.1") == "4.17.21"

    def test_whitespace_around_version(self):
        assert _extract_lowest_version(">= 2.3.4") == "2.3.4"


# ---------------------------------------------------------------------------
# classify_advisory — major_required bucket
# ---------------------------------------------------------------------------


class TestClassifyMajorRequired:
    """Advisory classified as major_required."""

    def test_major_increase(self):
        """patched >=5.0.0, installed 4.x → major_required."""
        adv = _make_advisory(patched=">=5.0.0")
        result = classify_advisory(adv, "4.17.21")
        assert result.bucket == "major_required"
        assert result.reason == "major_increase"
        assert result.lowest_patched == "5.0.0"

    def test_major_skip(self):
        """patched >=3.0.0, installed 1.x → major_required."""
        adv = _make_advisory(patched=">=3.0.0")
        result = classify_advisory(adv, "1.5.0")
        assert result.bucket == "major_required"
        assert result.reason == "major_increase"

    def test_zero_minor_increase(self):
        """0.x minor increase treated as major-equivalent."""
        adv = _make_advisory(patched=">=0.5.0")
        result = classify_advisory(adv, "0.3.2")
        assert result.bucket == "major_required"
        assert result.reason == "zero_minor_increase"

    def test_zero_to_one(self):
        """0.x → 1.x is a major increase."""
        adv = _make_advisory(patched=">=1.0.0")
        result = classify_advisory(adv, "0.9.9")
        assert result.bucket == "major_required"
        assert result.reason == "major_increase"


# ---------------------------------------------------------------------------
# classify_advisory — in_range bucket
# ---------------------------------------------------------------------------


class TestClassifyInRange:
    """Advisory classified as in_range."""

    def test_patch_bump(self):
        """patched >=4.17.21, installed 4.17.0 → in_range."""
        adv = _make_advisory(patched=">=4.17.21")
        result = classify_advisory(adv, "4.17.0")
        assert result.bucket == "in_range"
        assert result.reason == "patch_or_minor"
        assert result.lowest_patched == "4.17.21"

    def test_minor_bump(self):
        """patched >=1.3.0, installed 1.2.0 → in_range."""
        adv = _make_advisory(patched=">=1.3.0")
        result = classify_advisory(adv, "1.2.0")
        assert result.bucket == "in_range"
        assert result.reason == "patch_or_minor"

    def test_zero_patch_bump(self):
        """0.x patch bump (0.1.2 → 0.1.5) → in_range."""
        adv = _make_advisory(patched=">=0.1.5")
        result = classify_advisory(adv, "0.1.2")
        assert result.bucket == "in_range"
        assert result.reason == "patch_or_minor"

    def test_complex_range_in_range(self):
        """Complex range >=4.17.21 <5.0.0 with installed 4.16.0 → in_range."""
        adv = _make_advisory(patched=">=4.17.21 <5.0.0")
        result = classify_advisory(adv, "4.16.0")
        assert result.bucket == "in_range"
        assert result.reason == "patch_or_minor"


# ---------------------------------------------------------------------------
# classify_advisory — unknown bucket
# ---------------------------------------------------------------------------


class TestClassifyUnknown:
    """Advisory classified as unknown."""

    def test_empty_patched_range(self):
        """Empty patched range → unknown, not major_required."""
        adv = _make_advisory(patched="")
        result = classify_advisory(adv, "1.0.0")
        assert result.bucket == "unknown"
        assert result.reason == "no_patched_range"

    def test_less_than_zero(self):
        """<0.0.0 (no fix available) → unknown."""
        adv = _make_advisory(patched="<0.0.0")
        result = classify_advisory(adv, "1.0.0")
        assert result.bucket == "unknown"
        assert result.reason == "no_patched_range"

    def test_non_semver_installed(self):
        """Non-semver installed → unknown."""
        adv = _make_advisory(patched=">=2.0.0")
        result = classify_advisory(adv, "abc123")
        assert result.bucket == "unknown"
        assert result.reason == "installed_not_semver"

    def test_unparseable_patched_range(self):
        """Patched range with no version-like string → unknown."""
        adv = _make_advisory(patched="no fix available")
        result = classify_advisory(adv, "1.0.0")
        assert result.bucket == "unknown"
        assert result.reason == "patched_range_unparseable"

    def test_patched_version_not_semver(self):
        """Patched range contains version but it's not valid semver after extraction."""
        # This is hard to trigger since our regex is generous, but we test the path
        # by providing something that _extract_lowest_version returns but parse_semver rejects
        adv = _make_advisory(patched=">=01.2.3")
        result = classify_advisory(adv, "1.0.0")
        # _extract_lowest_version will find "01.2.3" as a fallback (version-like string)
        # but parse_semver rejects leading zeros
        # Actually >=01.2.3 → _LOWER_BOUND_RE finds "01.2.3" → parse_semver("01.2.3") → None
        assert result.bucket == "unknown"
        assert result.reason == "patched_version_not_semver"


# ---------------------------------------------------------------------------
# classify_advisory — metadata preservation
# ---------------------------------------------------------------------------


class TestClassifyMetadata:
    """Verify advisory metadata is correctly preserved."""

    def test_preserves_all_fields(self):
        adv = {
            "id": 1065,
            "module_name": "lodash",
            "severity": "high",
            "title": "Prototype Pollution",
            "url": "https://github.com/advisories/GHSA-test",
            "cves": ["CVE-2021-23337", "CVE-2021-23338"],
            "patched_versions": ">=4.17.21",
        }
        result = classify_advisory(adv, "4.17.0")
        assert result.id == 1065
        assert result.module == "lodash"
        assert result.severity == "high"
        assert result.title == "Prototype Pollution"
        assert result.url == "https://github.com/advisories/GHSA-test"
        assert result.cves == ["CVE-2021-23337", "CVE-2021-23338"]
        assert result.patched_versions == ">=4.17.21"

    def test_missing_fields_default(self):
        adv = {"patched_versions": ">=1.0.0"}
        result = classify_advisory(adv, "0.9.0")
        assert result.id == ""
        assert result.module == "unknown"
        assert result.severity == "unknown"
        assert result.title == ""
        assert result.url == ""
        assert result.cves == []

    def test_npm_via_format_fields(self):
        """npm format uses 'name' instead of 'module_name'."""
        adv = {
            "name": "axios",
            "github_advisory_id": "GHSA-abc",
            "severity": "moderate",
            "title": "SSRF",
            "url": "https://example.com",
            "cves": [],
            "patched_versions": ">=1.3.2",
        }
        result = classify_advisory(adv, "1.2.0")
        assert result.module == "axios"
        assert result.id == "GHSA-abc"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_advisory(
    *,
    patched: str = ">=1.0.0",
    module: str = "test-pkg",
    severity: str = "high",
    advisory_id: int | str = 9999,
) -> dict:
    """Create a minimal advisory dict for testing."""
    return {
        "id": advisory_id,
        "module_name": module,
        "severity": severity,
        "title": f"Test advisory for {module}",
        "url": f"https://example.com/advisory/{advisory_id}",
        "cves": ["CVE-2024-0001"],
        "patched_versions": patched,
    }
