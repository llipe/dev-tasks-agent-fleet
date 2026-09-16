"""
Unit tests for `fix_agent._safe_path` -- the workspace-confinement resolver
ported from `dependency-update`'s `fix_agent.py` (spec §12, PRD acceptance
criterion 20, story S-138, task 14.5).

Ported near-verbatim from the sibling agent's own
`tests/unit/test_safe_path.py` (same resolver logic, byte-identical
semantics) plus additional adversarial/near-miss cases this story's
completion instructions call out explicitly: try to break it yourself with
near-miss/adversarial paths, not just the sibling's original test cases
(mirrors the rigor applied to S-137's re-scan gate audit).
"""

from __future__ import annotations

import os
import tempfile

import pytest

import fix_agent
from fix_agent import _safe_path


@pytest.fixture(autouse=True)
def workspace(tmp_path):
    """Create a temporary workspace and set it as the fix_agent workspace."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("import os\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg").mkdir()
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("")
    fix_agent._WORKSPACE = str(tmp_path)
    yield tmp_path
    fix_agent._WORKSPACE = ""


@pytest.mark.unit
class TestSafePathValid:
    """Valid paths that should resolve correctly."""

    def test_simple_relative_path(self, workspace):
        result = _safe_path("src/app.py")
        assert result == os.path.realpath(workspace / "src" / "app.py")

    def test_current_dir_prefix(self, workspace):
        result = _safe_path("./src/app.py")
        assert result == os.path.realpath(workspace / "src" / "app.py")

    def test_workspace_root_itself(self, workspace):
        result = _safe_path(".")
        assert result == os.path.realpath(workspace)

    def test_nested_file(self, workspace):
        (workspace / "src" / "lib").mkdir()
        (workspace / "src" / "lib" / "util.py").write_text("")
        result = _safe_path("src/lib/util.py")
        assert result == os.path.realpath(workspace / "src" / "lib" / "util.py")

    def test_node_modules_within_workspace(self, workspace):
        result = _safe_path("node_modules/pkg/index.js")
        assert result == os.path.realpath(workspace / "node_modules" / "pkg" / "index.js")


@pytest.mark.unit
class TestSafePathTraversal:
    """Path traversal attacks that must be rejected."""

    def test_parent_traversal(self, workspace):
        with pytest.raises(ValueError, match="escapes workspace"):
            _safe_path("../")

    def test_deep_parent_traversal(self, workspace):
        with pytest.raises(ValueError, match="escapes workspace"):
            _safe_path("../../etc/passwd")

    def test_traversal_through_node_modules(self, workspace):
        with pytest.raises(ValueError, match="escapes workspace"):
            _safe_path("node_modules/../../../etc/passwd")

    def test_traversal_after_valid_prefix(self, workspace):
        with pytest.raises(ValueError, match="escapes workspace"):
            _safe_path("src/../../etc/passwd")

    def test_multiple_parent_refs(self, workspace):
        with pytest.raises(ValueError, match="escapes workspace"):
            _safe_path("../../../../../../../tmp/evil")

    def test_traversal_disguised_with_trailing_valid_segment(self, workspace):
        """Adversarial: traversal followed by a real in-workspace-looking
        filename must still be caught -- the trailing segment must not
        distract from the overall resolved path."""
        with pytest.raises(ValueError, match="escapes workspace"):
            _safe_path("../src/app.py")

    def test_traversal_with_dot_segments_interleaved(self, workspace):
        """Adversarial: './..//../' interleaving of no-op and traversal
        segments must still resolve to an escape."""
        with pytest.raises(ValueError, match="escapes workspace"):
            _safe_path("./a/./..//../../etc/shadow")


@pytest.mark.unit
class TestSafePathAbsolute:
    """Absolute paths must be rejected."""

    def test_absolute_path_unix(self, workspace):
        with pytest.raises(ValueError, match="Absolute paths are not allowed"):
            _safe_path("/etc/passwd")

    def test_absolute_path_to_workspace(self, workspace):
        abs_path = str(workspace / "src" / "app.py")
        with pytest.raises(ValueError, match="Absolute paths are not allowed"):
            _safe_path(abs_path)

    def test_absolute_path_with_traversal(self, workspace):
        """Adversarial: an absolute path that ALSO contains traversal
        segments must still be rejected on the absolute-path check (the
        first, cheapest guard), not fall through to any weaker path."""
        with pytest.raises(ValueError, match="Absolute paths are not allowed"):
            _safe_path("/var/../etc/passwd")


@pytest.mark.unit
class TestSafePathSymlink:
    """Symlinks that resolve outside workspace must be rejected."""

    def test_symlink_escape(self, workspace):
        external_dir = tempfile.mkdtemp()
        link_path = workspace / "escape_link"
        try:
            os.symlink(external_dir, str(link_path))
            with pytest.raises(ValueError, match="escapes workspace"):
                _safe_path("escape_link/somefile.txt")
        finally:
            os.unlink(str(link_path))
            os.rmdir(external_dir)

    def test_symlink_within_workspace_ok(self, workspace):
        (workspace / "actual_dir").mkdir()
        (workspace / "actual_dir" / "file.txt").write_text("hello")
        os.symlink(str(workspace / "actual_dir"), str(workspace / "link_dir"))
        result = _safe_path("link_dir/file.txt")
        assert result == os.path.realpath(workspace / "actual_dir" / "file.txt")

    def test_nested_symlink_escape_deep_inside_tree(self, workspace):
        """Adversarial: a symlink escape several directories deep must
        still be caught, not just a top-level symlink."""
        (workspace / "src" / "vendor").mkdir()
        external_dir = tempfile.mkdtemp()
        link_path = workspace / "src" / "vendor" / "escape"
        try:
            os.symlink(external_dir, str(link_path))
            with pytest.raises(ValueError, match="escapes workspace"):
                _safe_path("src/vendor/escape/payload.py")
        finally:
            os.unlink(str(link_path))
            os.rmdir(external_dir)


@pytest.mark.unit
class TestSafePathEdgeCases:
    """Edge cases and boundary conditions."""

    def test_workspace_not_set(self):
        fix_agent._WORKSPACE = ""
        with pytest.raises(ValueError, match="Workspace not set"):
            _safe_path("anything")

    def test_empty_relative_path(self, workspace):
        result = _safe_path("")
        assert result == os.path.realpath(workspace)

    def test_path_with_null_byte(self, workspace):
        with pytest.raises((ValueError, OSError)):
            _safe_path("src/\x00evil.py")

    def test_sibling_directory_name_prefix_collision(self, workspace):
        """Adversarial: a sibling directory whose name is a superstring of
        the workspace's own basename (e.g. workspace 'proj' vs sibling
        'proj-evil') must not be treated as inside the workspace merely
        because of a naive string-prefix check."""
        parent = workspace.parent
        evil_sibling = parent / (workspace.name + "-evil")
        evil_sibling.mkdir()
        try:
            # A traversal that lands exactly on the sibling directory must
            # still be refused -- `resolved.startswith(workspace_real +
            # os.sep)` (not a bare `startswith(workspace_real)`) is what
            # protects against this class of false-accept.
            rel = os.path.join("..", evil_sibling.name, "x")
            with pytest.raises(ValueError, match="escapes workspace"):
                _safe_path(rel)
        finally:
            evil_sibling.rmdir()
