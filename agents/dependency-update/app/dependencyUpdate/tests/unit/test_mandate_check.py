"""
Unit tests for verify_no_mandate_violation — package.json integrity check (req 50).

Tests:
  - No changes passes
  - Widened range fails
  - New dependency fails
  - Removed dependency fails
  - Changed pin (by pm) passes — only if not in package.json
  - Multiple violations detected
"""

from __future__ import annotations

import json
import os

import pytest

from fix_agent import verify_no_mandate_violation


@pytest.fixture
def workspace(tmp_path):
    """Create a workspace with a basic package.json."""
    return tmp_path


def _write_pkg(workspace, deps=None, dev_deps=None):
    """Write a package.json to the workspace."""
    data = {"name": "test-project", "version": "1.0.0"}
    if deps is not None:
        data["dependencies"] = deps
    if dev_deps is not None:
        data["devDependencies"] = dev_deps
    pkg_path = os.path.join(str(workspace), "package.json")
    with open(pkg_path, "w", encoding="utf-8") as f:
        json.dump(data, f)


@pytest.mark.unit
class TestNoChange:
    """No changes should pass mandate check."""

    def test_identical_deps(self, workspace):
        """Identical package.json before and after → no violations."""
        deps = {"react": "^18.2.0", "next": "^14.0.0"}
        dev_deps = {"typescript": "^5.3.0", "eslint": "^8.0.0"}
        _write_pkg(workspace, deps, dev_deps)

        before = {"dependencies": dict(deps), "devDependencies": dict(dev_deps)}
        violations = verify_no_mandate_violation(str(workspace), before)
        assert violations == []

    def test_empty_deps_both(self, workspace):
        """Empty deps on both sides → no violations."""
        _write_pkg(workspace, {}, {})
        before = {"dependencies": {}, "devDependencies": {}}
        violations = verify_no_mandate_violation(str(workspace), before)
        assert violations == []

    def test_no_deps_section(self, workspace):
        """package.json without deps sections → no violations."""
        pkg_path = os.path.join(str(workspace), "package.json")
        with open(pkg_path, "w") as f:
            json.dump({"name": "test"}, f)
        before = {"dependencies": {}, "devDependencies": {}}
        violations = verify_no_mandate_violation(str(workspace), before)
        assert violations == []


@pytest.mark.unit
class TestWidenedRange:
    """Widened semver range must be caught."""

    def test_caret_major_bump(self, workspace):
        """^1.0.0 → ^2.0.0 is a violation."""
        _write_pkg(workspace, {"react": "^2.0.0"})
        before = {"dependencies": {"react": "^1.0.0"}, "devDependencies": {}}
        violations = verify_no_mandate_violation(str(workspace), before)
        assert len(violations) == 1
        assert violations[0].package == "react"
        assert violations[0].before == "^1.0.0"
        assert violations[0].after == "^2.0.0"
        assert "changed" in violations[0].reason

    def test_tilde_to_caret(self, workspace):
        """~1.2.3 → ^1.2.3 is a change (widened range)."""
        _write_pkg(workspace, {"lodash": "^1.2.3"})
        before = {"dependencies": {"lodash": "~1.2.3"}, "devDependencies": {}}
        violations = verify_no_mandate_violation(str(workspace), before)
        assert len(violations) == 1
        assert violations[0].reason == "version specifier changed"

    def test_exact_to_range(self, workspace):
        """1.2.3 → ^1.2.3 is a change."""
        _write_pkg(workspace, {"express": "^1.2.3"})
        before = {"dependencies": {"express": "1.2.3"}, "devDependencies": {}}
        violations = verify_no_mandate_violation(str(workspace), before)
        assert len(violations) == 1


@pytest.mark.unit
class TestNewDependency:
    """New dependency added must be caught."""

    def test_new_dep_added(self, workspace):
        """A package that wasn't there before is a violation."""
        _write_pkg(workspace, {"react": "^18.0.0", "evil-pkg": "^1.0.0"})
        before = {"dependencies": {"react": "^18.0.0"}, "devDependencies": {}}
        violations = verify_no_mandate_violation(str(workspace), before)
        assert len(violations) == 1
        assert violations[0].package == "evil-pkg"
        assert violations[0].before is None
        assert "added" in violations[0].reason

    def test_new_dev_dep_added(self, workspace):
        """A new devDependency is also a violation."""
        _write_pkg(workspace, dev_deps={"jest": "^29.0.0", "new-thing": "^1.0.0"})
        before = {"dependencies": {}, "devDependencies": {"jest": "^29.0.0"}}
        violations = verify_no_mandate_violation(str(workspace), before)
        assert len(violations) == 1
        assert violations[0].field == "devDependencies"


@pytest.mark.unit
class TestRemovedDependency:
    """Removed dependency must be caught."""

    def test_dep_removed(self, workspace):
        """A package that existed before but is now missing is a violation."""
        _write_pkg(workspace, {"react": "^18.0.0"})
        before = {
            "dependencies": {"react": "^18.0.0", "lodash": "^4.0.0"},
            "devDependencies": {},
        }
        violations = verify_no_mandate_violation(str(workspace), before)
        assert len(violations) == 1
        assert violations[0].package == "lodash"
        assert violations[0].after is None
        assert "removed" in violations[0].reason


@pytest.mark.unit
class TestPmPinPassesThrough:
    """Changes by the package manager (in lockfile only) don't appear in package.json."""

    def test_unchanged_specifier_passes(self, workspace):
        """
        If PM pins to a specific version in the lockfile but package.json
        specifier stays ^1.2.0, there's no violation.
        """
        # The point is: we only compare package.json, not lockfile.
        # If the PM resolves ^1.2.0 to 1.2.5 instead of 1.2.3, package.json is unchanged.
        _write_pkg(workspace, {"react": "^18.2.0"})
        before = {"dependencies": {"react": "^18.2.0"}, "devDependencies": {}}
        violations = verify_no_mandate_violation(str(workspace), before)
        assert violations == []


@pytest.mark.unit
class TestMultipleViolations:
    """Multiple violations detected at once."""

    def test_multiple_changes(self, workspace):
        """Changed + added + removed all detected."""
        _write_pkg(
            workspace,
            deps={"react": "^19.0.0", "new-pkg": "^1.0.0"},
            dev_deps={"typescript": "^5.3.0"},
        )
        before = {
            "dependencies": {"react": "^18.0.0", "removed-pkg": "^1.0.0"},
            "devDependencies": {"typescript": "^5.3.0"},
        }
        violations = verify_no_mandate_violation(str(workspace), before)
        # react changed, new-pkg added, removed-pkg removed = 3 violations
        assert len(violations) == 3
        packages = {v.package for v in violations}
        assert packages == {"react", "new-pkg", "removed-pkg"}


@pytest.mark.unit
class TestEdgeCases:
    """Edge cases for mandate check."""

    def test_missing_package_json(self, workspace):
        """If package.json doesn't exist after fix, all original deps are 'removed'."""
        # Don't create a package.json
        before = {"dependencies": {"react": "^18.0.0"}, "devDependencies": {}}
        violations = verify_no_mandate_violation(str(workspace), before)
        # react is 'removed' because current package.json can't be read
        assert len(violations) == 1
        assert violations[0].reason == "dependency removed"

    def test_malformed_package_json(self, workspace):
        """Malformed JSON in package.json → treated as empty deps."""
        pkg_path = os.path.join(str(workspace), "package.json")
        with open(pkg_path, "w") as f:
            f.write("not valid json{{{")
        before = {"dependencies": {"react": "^18.0.0"}, "devDependencies": {}}
        violations = verify_no_mandate_violation(str(workspace), before)
        assert len(violations) == 1
