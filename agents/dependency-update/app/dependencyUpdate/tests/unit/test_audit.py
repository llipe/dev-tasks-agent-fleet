"""
Unit tests for audit.py — audit runner, parser, snapshot, and diff.

Covers:
  - count_vulns: both pnpm and npm JSON shapes
  - extract_advisories: both pnpm and npm formats, deduplication
  - _parse_list_json: pnpm (array) and npm (object) list output
  - diff_packages: added, removed, updated, unchanged
  - run_audit: mocked subprocess (success, failure, unparseable)
  - snapshot_lockfile_packages: mocked subprocess
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from audit import (
    _parse_list_json,
    count_advisories_fixed,
    count_vulns,
    diff_packages,
    extract_advisories,
    run_audit,
    snapshot_lockfile_packages,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixture loading helpers
# ---------------------------------------------------------------------------


def _load_fixture(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# count_vulns
# ---------------------------------------------------------------------------


class TestCountVulns:
    """Tests for count_vulns()."""

    def test_pnpm_clean(self):
        data = _load_fixture("audit_pnpm_clean.json")
        counts = count_vulns(data, "pnpm")
        assert counts == {"info": 0, "low": 0, "moderate": 0, "high": 0, "critical": 0}

    def test_pnpm_vulns(self):
        data = _load_fixture("audit_pnpm_vulns.json")
        counts = count_vulns(data, "pnpm")
        assert counts["high"] == 1
        assert counts["critical"] == 1
        assert counts["moderate"] == 1

    def test_npm_clean(self):
        data = _load_fixture("audit_npm_clean.json")
        counts = count_vulns(data, "npm")
        assert all(v == 0 for v in counts.values())

    def test_npm_vulns(self):
        data = _load_fixture("audit_npm_vulns.json")
        counts = count_vulns(data, "npm")
        assert counts["high"] == 1
        assert counts["moderate"] == 1
        assert counts["low"] == 1

    def test_empty_result(self):
        counts = count_vulns({}, "pnpm")
        assert counts == {}

    def test_missing_metadata(self):
        counts = count_vulns({"metadata": {}}, "npm")
        assert counts == {}

    def test_npm_nested_total_format(self):
        """npm sometimes nests counts as {severity: {total: N}}."""
        data = {
            "metadata": {
                "vulnerabilities": {
                    "high": {"total": 3, "fixAvailable": 2},
                    "low": {"total": 1, "fixAvailable": 0},
                }
            }
        }
        counts = count_vulns(data, "npm")
        assert counts == {"high": 3, "low": 1}


# ---------------------------------------------------------------------------
# extract_advisories
# ---------------------------------------------------------------------------


class TestExtractAdvisories:
    """Tests for extract_advisories()."""

    def test_pnpm_format(self):
        data = _load_fixture("audit_pnpm_vulns.json")
        advisories = extract_advisories(data, "pnpm")
        assert len(advisories) == 3

        # Check first advisory
        lodash = next(a for a in advisories if a["module_name"] == "lodash")
        assert lodash["id"] == 1065
        assert lodash["severity"] == "high"
        assert "CVE-2021-23337" in lodash["cves"]
        assert lodash["patched_versions"] == ">=4.17.21"

    def test_npm_format(self):
        data = _load_fixture("audit_npm_vulns.json")
        advisories = extract_advisories(data, "npm")
        # express via is a string ("qs") so it should be skipped
        assert len(advisories) == 2

        lodash = next(a for a in advisories if a["module_name"] == "lodash")
        assert lodash["id"] == 1065
        assert lodash["severity"] == "high"
        assert lodash["patched_versions"] == ">=4.17.21"

    def test_npm_deduplication(self):
        """Same source ID appearing in multiple packages is deduplicated."""
        data = {
            "vulnerabilities": {
                "pkg-a": {
                    "name": "pkg-a",
                    "severity": "high",
                    "via": [
                        {
                            "source": 100,
                            "name": "shared",
                            "severity": "high",
                            "title": "Bug",
                            "url": "",
                            "cves": [],
                            "range": ">=2.0.0",
                        }
                    ],
                },
                "pkg-b": {
                    "name": "pkg-b",
                    "severity": "high",
                    "via": [
                        {
                            "source": 100,
                            "name": "shared",
                            "severity": "high",
                            "title": "Bug",
                            "url": "",
                            "cves": [],
                            "range": ">=2.0.0",
                        }
                    ],
                },
            }
        }
        advisories = extract_advisories(data, "npm")
        assert len(advisories) == 1

    def test_npm_string_via_skipped(self):
        """String entries in 'via' (transitive refs) are skipped."""
        data = {
            "vulnerabilities": {
                "express": {
                    "name": "express",
                    "severity": "low",
                    "via": ["qs", "body-parser"],
                }
            }
        }
        advisories = extract_advisories(data, "npm")
        assert len(advisories) == 0

    def test_pnpm_empty_advisories(self):
        data = _load_fixture("audit_pnpm_clean.json")
        advisories = extract_advisories(data, "pnpm")
        assert advisories == []

    def test_npm_empty_vulnerabilities(self):
        data = _load_fixture("audit_npm_clean.json")
        advisories = extract_advisories(data, "npm")
        assert advisories == []


# ---------------------------------------------------------------------------
# _parse_list_json
# ---------------------------------------------------------------------------


class TestParseListJson:
    """Tests for _parse_list_json()."""

    def test_pnpm_format(self):
        data = _load_fixture("list_pnpm.json")
        packages = _parse_list_json(data, "pnpm")
        assert packages["lodash"] == "4.17.0"
        assert packages["express"] == "4.18.2"
        assert packages["axios"] == "1.2.0"
        # devDependencies also included
        assert packages["vitest"] == "1.6.0"
        assert packages["typescript"] == "5.4.5"

    def test_npm_format(self):
        data = _load_fixture("list_npm.json")
        packages = _parse_list_json(data, "npm")
        assert packages["lodash"] == "4.17.0"
        assert packages["express"] == "4.18.2"
        assert packages["axios"] == "1.2.0"

    def test_empty_list(self):
        assert _parse_list_json([], "pnpm") == {}

    def test_empty_object(self):
        assert _parse_list_json({}, "npm") == {}

    def test_missing_dependencies(self):
        assert _parse_list_json({"name": "proj"}, "npm") == {}

    def test_pnpm_no_deps_entry(self):
        assert _parse_list_json([{"name": "proj"}], "pnpm") == {}

    # --- workspace / monorepo recursion (issue #90) ---

    def test_pnpm_monorepo_captures_all_workspace_and_transitive(self):
        """
        Recursive parse of a `pnpm list -r` monorepo listing must capture
        packages from every workspace entry AND nested transitive dependencies
        — not just the root's top-level deps (issue #90).
        """
        data = _load_fixture("list_pnpm_monorepo.json")
        packages = _parse_list_json(data, "pnpm")

        # root devDependency
        assert packages["turbo"] == "1.13.0"
        # workspace @app/web direct deps
        assert packages["react"] == "18.2.0"
        assert packages["chokidar"] == "3.5.3"
        # transitive under react
        assert packages["loose-envify"] == "1.4.0"
        assert packages["js-tokens"] == "4.0.0"
        # transitive under chokidar
        assert packages["glob-parent"] == "5.1.2"
        # workspace @app/api deps + devDeps
        assert packages["express"] == "4.18.2"
        assert packages["typescript"] == "5.4.5"

    def test_npm_nested_dependencies_recursion(self):
        """npm `list --all` nests transitive deps under each dependency."""
        data = {
            "name": "proj",
            "dependencies": {
                "a": {
                    "version": "1.0.0",
                    "dependencies": {"b": {"version": "2.0.0"}},
                }
            },
        }
        packages = _parse_list_json(data, "npm")
        assert packages["a"] == "1.0.0"
        assert packages["b"] == "2.0.0"


# ---------------------------------------------------------------------------
# diff_packages
# ---------------------------------------------------------------------------


class TestDiffPackages:
    """Tests for diff_packages()."""

    def test_no_changes(self):
        snapshot = {"a": "1.0.0", "b": "2.0.0"}
        changes = diff_packages(snapshot, snapshot.copy())
        assert changes == []

    def test_added_package(self):
        before = {"a": "1.0.0"}
        after = {"a": "1.0.0", "b": "2.0.0"}
        changes = diff_packages(before, after)
        assert len(changes) == 1
        assert changes[0].name == "b"
        assert changes[0].action == "added"
        assert changes[0].new_version == "2.0.0"
        assert changes[0].old_version is None

    def test_removed_package(self):
        before = {"a": "1.0.0", "b": "2.0.0"}
        after = {"a": "1.0.0"}
        changes = diff_packages(before, after)
        assert len(changes) == 1
        assert changes[0].name == "b"
        assert changes[0].action == "removed"
        assert changes[0].old_version == "2.0.0"
        assert changes[0].new_version is None

    def test_updated_package(self):
        before = {"a": "1.0.0", "b": "2.0.0"}
        after = {"a": "1.0.0", "b": "2.1.0"}
        changes = diff_packages(before, after)
        assert len(changes) == 1
        assert changes[0].name == "b"
        assert changes[0].action == "updated"
        assert changes[0].old_version == "2.0.0"
        assert changes[0].new_version == "2.1.0"

    def test_multiple_changes(self):
        before = {"a": "1.0.0", "b": "2.0.0", "c": "3.0.0"}
        after = {"a": "1.1.0", "c": "3.0.0", "d": "4.0.0"}
        changes = diff_packages(before, after)
        # a updated, b removed, d added (sorted by name)
        assert len(changes) == 3
        names = [c.name for c in changes]
        assert names == ["a", "b", "d"]
        assert changes[0].action == "updated"
        assert changes[1].action == "removed"
        assert changes[2].action == "added"

    def test_empty_snapshots(self):
        assert diff_packages({}, {}) == []

    def test_from_empty(self):
        after = {"a": "1.0.0"}
        changes = diff_packages({}, after)
        assert len(changes) == 1
        assert changes[0].action == "added"

    def test_to_empty(self):
        before = {"a": "1.0.0"}
        changes = diff_packages(before, {})
        assert len(changes) == 1
        assert changes[0].action == "removed"


# ---------------------------------------------------------------------------
# count_advisories_fixed (advisory ID-set diff — issue #90)
# ---------------------------------------------------------------------------


class TestCountAdvisoriesFixed:
    """
    Tests for count_advisories_fixed() — the ID-set diff (issue #90).

    The number of advisories fixed is the count of advisory IDs present in the
    before-audit but absent in the after-audit. This must NOT be derived by
    subtracting `in_range` bucket counts: on a repo where nothing classifies as
    `in_range` (all `unknown`), bucket subtraction yields 0 even though real
    advisories disappeared.
    """

    def test_id_set_diff_on_unknown_bucket_fixtures(self):
        """
        Regression for #90: before={2001,2002,2003}, after={2003}, all with
        empty patched_versions (→ unknown bucket). Two advisories were fixed.
        """
        before = extract_advisories(_load_fixture("audit_pnpm_before.json"), "pnpm")
        after = extract_advisories(_load_fixture("audit_pnpm_after.json"), "pnpm")
        assert count_advisories_fixed(before, after) == 2

    def test_nothing_fixed_when_sets_equal(self):
        before = extract_advisories(_load_fixture("audit_pnpm_before.json"), "pnpm")
        assert count_advisories_fixed(before, list(before)) == 0

    def test_all_fixed_when_after_empty(self):
        before = extract_advisories(_load_fixture("audit_pnpm_before.json"), "pnpm")
        assert count_advisories_fixed(before, []) == 3

    def test_empty_before_is_zero(self):
        after = extract_advisories(_load_fixture("audit_pnpm_after.json"), "pnpm")
        assert count_advisories_fixed([], after) == 0

    def test_new_advisories_after_do_not_go_negative(self):
        """Advisories that appear only after the update are not 'fixed'."""
        before = [{"id": 1, "module_name": "a"}]
        after = [{"id": 1, "module_name": "a"}, {"id": 2, "module_name": "b"}]
        assert count_advisories_fixed(before, after) == 0

    def test_dedupes_repeated_ids(self):
        """The same advisory ID appearing twice counts once."""
        before = [{"id": 5, "module_name": "x"}, {"id": 5, "module_name": "x"}]
        after: list[dict] = []
        assert count_advisories_fixed(before, after) == 1

    def test_npm_shape_id_set_diff_url_fallback(self):
        """
        npm advisories lacking a numeric `source` fall back to their URL as the
        id (issue #90 drift fix), so distinct URL-only advisories are counted
        distinctly rather than collapsing to a single empty id.
        """
        data_before = {
            "vulnerabilities": {
                "pkg-a": {
                    "name": "pkg-a",
                    "severity": "high",
                    "via": [
                        {
                            "name": "pkg-a",
                            "severity": "high",
                            "title": "A",
                            "url": "https://github.com/advisories/GHSA-aaaa",
                            "range": "<1.0.0",
                        }
                    ],
                },
                "pkg-b": {
                    "name": "pkg-b",
                    "severity": "moderate",
                    "via": [
                        {
                            "name": "pkg-b",
                            "severity": "moderate",
                            "title": "B",
                            "url": "https://github.com/advisories/GHSA-bbbb",
                            "range": "<2.0.0",
                        }
                    ],
                },
            }
        }
        data_after = {
            "vulnerabilities": {
                "pkg-b": {
                    "name": "pkg-b",
                    "severity": "moderate",
                    "via": [
                        {
                            "name": "pkg-b",
                            "severity": "moderate",
                            "title": "B",
                            "url": "https://github.com/advisories/GHSA-bbbb",
                            "range": "<2.0.0",
                        }
                    ],
                }
            }
        }
        before = extract_advisories(data_before, "npm")
        after = extract_advisories(data_after, "npm")
        # GHSA-aaaa disappeared; GHSA-bbbb remains → exactly one fixed.
        assert count_advisories_fixed(before, after) == 1


# ---------------------------------------------------------------------------
# run_audit (mocked subprocess)
# ---------------------------------------------------------------------------


class TestRunAudit:
    """Tests for run_audit() with mocked subprocess."""

    @patch("audit.subprocess.run")
    def test_pnpm_audit_with_vulns(self, mock_run):
        fixture = _load_fixture("audit_pnpm_vulns.json")
        mock_run.return_value = _mock_completed(json.dumps(fixture), returncode=1)

        result = run_audit("/fake/workspace", "pnpm")
        assert result.total_vulns == 3
        assert len(result.advisories) == 3
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["pnpm", "audit", "--json"]

    @patch("audit.subprocess.run")
    def test_npm_audit_clean(self, mock_run):
        fixture = _load_fixture("audit_npm_clean.json")
        mock_run.return_value = _mock_completed(json.dumps(fixture), returncode=0)

        result = run_audit("/fake/workspace", "npm")
        assert result.total_vulns == 0
        assert result.advisories == []
        cmd = mock_run.call_args[0][0]
        assert cmd == ["npm", "audit", "--json"]

    @patch("audit.subprocess.run")
    def test_empty_stdout(self, mock_run):
        mock_run.return_value = _mock_completed("", returncode=0)
        result = run_audit("/fake", "pnpm")
        assert result.total_vulns == 0
        assert result.advisories == []

    @patch("audit.subprocess.run")
    def test_invalid_json(self, mock_run):
        mock_run.return_value = _mock_completed("not json{{{", returncode=1)
        result = run_audit("/fake", "npm")
        assert result.total_vulns == 0
        assert result.raw == {}

    @patch("audit.subprocess.run")
    def test_command_failure(self, mock_run):
        mock_run.side_effect = OSError("command not found")
        with pytest.raises(RuntimeError, match="Failed to run pnpm audit"):
            run_audit("/fake", "pnpm")


# ---------------------------------------------------------------------------
# snapshot_lockfile_packages (mocked subprocess)
# ---------------------------------------------------------------------------


class TestSnapshotLockfilePackages:
    """Tests for snapshot_lockfile_packages() with mocked subprocess."""

    @patch("audit.subprocess.run")
    def test_pnpm_snapshot(self, mock_run):
        fixture = _load_fixture("list_pnpm.json")
        mock_run.return_value = _mock_completed(json.dumps(fixture), returncode=0)

        packages = snapshot_lockfile_packages("/fake", "pnpm")
        assert packages["lodash"] == "4.17.0"
        assert packages["express"] == "4.18.2"
        cmd = mock_run.call_args[0][0]
        # Workspace-aware + recursive so monorepo/transitive changes are seen (#90)
        assert cmd == ["pnpm", "list", "-r", "--depth", "Infinity", "--json"]

    @patch("audit.subprocess.run")
    def test_npm_snapshot(self, mock_run):
        fixture = _load_fixture("list_npm.json")
        mock_run.return_value = _mock_completed(json.dumps(fixture), returncode=0)

        packages = snapshot_lockfile_packages("/fake", "npm")
        assert packages["lodash"] == "4.17.0"
        cmd = mock_run.call_args[0][0]
        assert cmd == ["npm", "list", "--all", "--json"]

    @patch("audit.subprocess.run")
    def test_pnpm_monorepo_snapshot(self, mock_run):
        """A monorepo listing yields workspace + transitive packages (#90)."""
        fixture = _load_fixture("list_pnpm_monorepo.json")
        mock_run.return_value = _mock_completed(json.dumps(fixture), returncode=0)

        packages = snapshot_lockfile_packages("/fake", "pnpm")
        assert packages["react"] == "18.2.0"
        assert packages["glob-parent"] == "5.1.2"
        assert len(packages) == 8

    @patch("audit.subprocess.run")
    def test_empty_stdout(self, mock_run):
        mock_run.return_value = _mock_completed("", returncode=0)
        packages = snapshot_lockfile_packages("/fake", "pnpm")
        assert packages == {}

    @patch("audit.subprocess.run")
    def test_command_failure(self, mock_run):
        mock_run.side_effect = OSError("command not found")
        with pytest.raises(RuntimeError, match="Failed to run npm list"):
            snapshot_lockfile_packages("/fake", "npm")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _mock_completed:
    """Minimal mock for subprocess.CompletedProcess."""

    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode
