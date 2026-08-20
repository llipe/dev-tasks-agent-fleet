"""Tests for pure helper functions in main.py.

Coverage targets:
- diff_packages: compare two package snapshots
- count_vulns: sum vulnerability counts from audit JSON
- extract_advisories: extract CVE/advisory details from pnpm audit output
- _detect_pnpm_version: detect pnpm version from package.json or lockfile
"""

import json
from pathlib import Path
from typing import Any

from main import (
    _detect_pnpm_version,
    count_vulns,
    diff_packages,
    extract_advisories,
)

# ─────────────────────────────────────────────────────────────────
# diff_packages
# ─────────────────────────────────────────────────────────────────


class TestDiffPackages:
    """Tests for diff_packages(before, after)."""

    def test_no_changes(self) -> None:
        before = {"react": "18.2.0", "next": "14.0.0"}
        after = {"react": "18.2.0", "next": "14.0.0"}
        assert diff_packages(before, after) == []

    def test_version_upgrade(self) -> None:
        before = {"react": "18.2.0", "next": "14.0.0"}
        after = {"react": "18.3.0", "next": "14.0.0"}
        result = diff_packages(before, after)
        assert len(result) == 1
        assert result[0] == {"name": "react", "from": "18.2.0", "to": "18.3.0"}

    def test_package_added(self) -> None:
        before = {"react": "18.2.0"}
        after = {"react": "18.2.0", "lodash": "4.17.21"}
        result = diff_packages(before, after)
        assert len(result) == 1
        assert result[0] == {"name": "lodash", "from": "(new)", "to": "4.17.21"}

    def test_package_removed(self) -> None:
        before = {"react": "18.2.0", "lodash": "4.17.21"}
        after = {"react": "18.2.0"}
        result = diff_packages(before, after)
        assert len(result) == 1
        assert result[0] == {"name": "lodash", "from": "4.17.21", "to": "(removed)"}

    def test_multiple_changes_sorted(self) -> None:
        before = {"b-pkg": "1.0.0", "a-pkg": "2.0.0"}
        after = {"b-pkg": "1.1.0", "a-pkg": "2.1.0"}
        result = diff_packages(before, after)
        assert len(result) == 2
        # Results should be sorted by name
        assert result[0]["name"] == "a-pkg"
        assert result[1]["name"] == "b-pkg"

    def test_empty_snapshots(self) -> None:
        assert diff_packages({}, {}) == []

    def test_all_new_packages(self) -> None:
        before: dict[str, str] = {}
        after = {"react": "18.2.0", "next": "14.0.0"}
        result = diff_packages(before, after)
        assert len(result) == 2
        assert all(r["from"] == "(new)" for r in result)

    def test_all_removed_packages(self) -> None:
        before = {"react": "18.2.0", "next": "14.0.0"}
        after: dict[str, str] = {}
        result = diff_packages(before, after)
        assert len(result) == 2
        assert all(r["to"] == "(removed)" for r in result)


# ─────────────────────────────────────────────────────────────────
# count_vulns
# ─────────────────────────────────────────────────────────────────


class TestCountVulns:
    """Tests for count_vulns(audit)."""

    def test_typical_audit_output(self) -> None:
        audit = {
            "metadata": {
                "vulnerabilities": {
                    "info": 0,
                    "low": 2,
                    "moderate": 1,
                    "high": 3,
                    "critical": 0,
                }
            }
        }
        assert count_vulns(audit) == 6

    def test_no_vulnerabilities(self) -> None:
        audit = {
            "metadata": {
                "vulnerabilities": {
                    "info": 0,
                    "low": 0,
                    "moderate": 0,
                    "high": 0,
                    "critical": 0,
                }
            }
        }
        assert count_vulns(audit) == 0

    def test_empty_audit(self) -> None:
        assert count_vulns({}) == 0

    def test_missing_metadata(self) -> None:
        audit: dict[str, Any] = {"advisories": {}}
        assert count_vulns(audit) == 0

    def test_missing_vulnerabilities_key(self) -> None:
        audit: dict[str, Any] = {"metadata": {}}
        assert count_vulns(audit) == 0

    def test_non_integer_values_ignored(self) -> None:
        """Non-integer values (like 'total' key) should not be summed."""
        audit = {
            "metadata": {
                "vulnerabilities": {
                    "low": 2,
                    "high": 1,
                    "total": "3",  # string, not int
                }
            }
        }
        assert count_vulns(audit) == 3

    def test_parse_failed_audit(self) -> None:
        """When audit JSON parsing fails, count_vulns returns 0."""
        audit = {"parse_failed": True, "raw": "some raw output"}
        assert count_vulns(audit) == 0


# ─────────────────────────────────────────────────────────────────
# extract_advisories
# ─────────────────────────────────────────────────────────────────


class TestExtractAdvisories:
    """Tests for extract_advisories(audit)."""

    def test_typical_advisories(self) -> None:
        audit = {
            "advisories": {
                "1234": {
                    "id": 1234,
                    "module_name": "lodash",
                    "severity": "high",
                    "title": "Prototype Pollution",
                    "url": "https://github.com/advisories/GHSA-xxxx",
                    "cves": ["CVE-2021-12345"],
                    "patched_versions": ">=4.17.21",
                },
                "5678": {
                    "id": 5678,
                    "module_name": "minimist",
                    "severity": "critical",
                    "title": "Prototype Pollution in minimist",
                    "url": "https://github.com/advisories/GHSA-yyyy",
                    "cves": ["CVE-2020-67890"],
                    "patched_versions": ">=1.2.6",
                },
            }
        }
        result = extract_advisories(audit)
        assert len(result) == 2
        # Check first advisory fields
        lodash_adv = next(a for a in result if a["module"] == "lodash")
        assert lodash_adv["id"] == 1234
        assert lodash_adv["severity"] == "high"
        assert lodash_adv["title"] == "Prototype Pollution"
        assert lodash_adv["cves"] == ["CVE-2021-12345"]
        assert lodash_adv["patched_versions"] == ">=4.17.21"

    def test_no_advisories(self) -> None:
        audit: dict[str, Any] = {"advisories": {}}
        assert extract_advisories(audit) == []

    def test_missing_advisories_key(self) -> None:
        audit: dict[str, Any] = {"metadata": {"vulnerabilities": {"high": 1}}}
        assert extract_advisories(audit) == []

    def test_advisory_with_missing_fields(self) -> None:
        """Advisories with missing fields should use defaults."""
        audit = {
            "advisories": {
                "9999": {
                    "id": 9999,
                }
            }
        }
        result = extract_advisories(audit)
        assert len(result) == 1
        assert result[0]["module"] == "unknown"
        assert result[0]["severity"] == "unknown"
        assert result[0]["title"] == ""
        assert result[0]["url"] == ""
        assert result[0]["cves"] == []
        assert result[0]["patched_versions"] == ""

    def test_advisory_uses_key_as_fallback_id(self) -> None:
        """When advisory has no 'id' field, the dict key is used."""
        audit = {
            "advisories": {
                "my-key": {
                    "module_name": "foo",
                    "severity": "low",
                    "title": "Some issue",
                }
            }
        }
        result = extract_advisories(audit)
        assert result[0]["id"] == "my-key"


# ─────────────────────────────────────────────────────────────────
# _detect_pnpm_version
# ─────────────────────────────────────────────────────────────────


class TestDetectPnpmVersion:
    """Tests for _detect_pnpm_version(workspace)."""

    def test_from_package_manager_field(self, tmp_path: Path) -> None:
        """Detects version from packageManager field in package.json."""
        pkg = {"name": "test", "packageManager": "pnpm@9.15.4"}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert _detect_pnpm_version(str(tmp_path)) == "9.15.4"

    def test_from_package_manager_field_major_only(self, tmp_path: Path) -> None:
        """packageManager with major.minor.patch returns full version."""
        pkg = {"name": "test", "packageManager": "pnpm@8.6.0"}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert _detect_pnpm_version(str(tmp_path)) == "8.6.0"

    def test_from_lockfile_version_9(self, tmp_path: Path) -> None:
        """lockfileVersion 9.0 maps to pnpm 9."""
        pkg = {"name": "test"}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
        assert _detect_pnpm_version(str(tmp_path)) == "9"

    def test_from_lockfile_version_6(self, tmp_path: Path) -> None:
        """lockfileVersion 6.0 maps to pnpm 8."""
        pkg = {"name": "test"}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '6.0'\n")
        assert _detect_pnpm_version(str(tmp_path)) == "8"

    def test_from_lockfile_version_5(self, tmp_path: Path) -> None:
        """lockfileVersion 5.4 maps to pnpm 7."""
        pkg = {"name": "test"}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '5.4'\n")
        assert _detect_pnpm_version(str(tmp_path)) == "7"

    def test_no_package_json(self, tmp_path: Path) -> None:
        """Returns None when no package.json exists."""
        assert _detect_pnpm_version(str(tmp_path)) is None

    def test_no_pnpm_lock_no_package_manager(self, tmp_path: Path) -> None:
        """Returns None when package.json has no packageManager and no lockfile."""
        pkg = {"name": "test"}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert _detect_pnpm_version(str(tmp_path)) is None

    def test_package_manager_not_pnpm(self, tmp_path: Path) -> None:
        """Returns None when packageManager is npm, not pnpm."""
        pkg = {"name": "test", "packageManager": "npm@10.0.0"}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        assert _detect_pnpm_version(str(tmp_path)) is None

    def test_invalid_json_in_package_json(self, tmp_path: Path) -> None:
        """Returns None when package.json is invalid JSON."""
        (tmp_path / "package.json").write_text("not valid json {{{")
        assert _detect_pnpm_version(str(tmp_path)) is None

    def test_unknown_lockfile_version(self, tmp_path: Path) -> None:
        """Returns None when lockfileVersion is not in the mapping."""
        pkg = {"name": "test"}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '3.0'\n")
        assert _detect_pnpm_version(str(tmp_path)) is None

    def test_package_manager_takes_precedence(self, tmp_path: Path) -> None:
        """packageManager field takes precedence over lockfileVersion."""
        pkg = {"name": "test", "packageManager": "pnpm@9.1.0"}
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '6.0'\n")
        # packageManager says 9.1.0, lockfile would say 8 — packageManager wins
        assert _detect_pnpm_version(str(tmp_path)) == "9.1.0"
