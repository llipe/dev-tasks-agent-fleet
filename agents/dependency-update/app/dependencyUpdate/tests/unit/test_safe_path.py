"""
Unit tests for _safe_path — path safety validation (req 46).

Tests traversal attacks, absolute paths, symlinks, and node_modules escapes.
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
    # Create some files/dirs for resolution
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("export default 1;")
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
        """A plain file in the workspace resolves correctly."""
        result = _safe_path("src/index.ts")
        assert result == os.path.realpath(workspace / "src" / "index.ts")

    def test_current_dir_prefix(self, workspace):
        """./file resolves correctly."""
        result = _safe_path("./src/index.ts")
        assert result == os.path.realpath(workspace / "src" / "index.ts")

    def test_workspace_root_itself(self, workspace):
        """Empty-ish path '.' resolves to workspace itself."""
        result = _safe_path(".")
        assert result == os.path.realpath(workspace)

    def test_nested_file(self, workspace):
        """Deeply nested relative path works."""
        (workspace / "src" / "lib").mkdir()
        (workspace / "src" / "lib" / "util.ts").write_text("")
        result = _safe_path("src/lib/util.ts")
        assert result == os.path.realpath(workspace / "src" / "lib" / "util.ts")

    def test_node_modules_within_workspace(self, workspace):
        """Paths into node_modules within workspace are allowed."""
        result = _safe_path("node_modules/pkg/index.js")
        assert result == os.path.realpath(workspace / "node_modules" / "pkg" / "index.js")


@pytest.mark.unit
class TestSafePathTraversal:
    """Path traversal attacks that must be rejected."""

    def test_parent_traversal(self, workspace):
        """../something escapes workspace."""
        with pytest.raises(ValueError, match="escapes workspace"):
            _safe_path("../")

    def test_deep_parent_traversal(self, workspace):
        """../../etc/passwd escapes workspace."""
        with pytest.raises(ValueError, match="escapes workspace"):
            _safe_path("../../etc/passwd")

    def test_traversal_through_node_modules(self, workspace):
        """node_modules/../../../etc/passwd escapes workspace."""
        with pytest.raises(ValueError, match="escapes workspace"):
            _safe_path("node_modules/../../../etc/passwd")

    def test_traversal_after_valid_prefix(self, workspace):
        """src/../../etc/passwd escapes workspace."""
        with pytest.raises(ValueError, match="escapes workspace"):
            _safe_path("src/../../etc/passwd")

    def test_multiple_parent_refs(self, workspace):
        """Many ../ levels escape."""
        with pytest.raises(ValueError, match="escapes workspace"):
            _safe_path("../../../../../../../tmp/evil")


@pytest.mark.unit
class TestSafePathAbsolute:
    """Absolute paths must be rejected."""

    def test_absolute_path_unix(self, workspace):
        """Absolute unix path is rejected."""
        with pytest.raises(ValueError, match="Absolute paths are not allowed"):
            _safe_path("/etc/passwd")

    def test_absolute_path_to_workspace(self, workspace):
        """Even an absolute path pointing INTO the workspace is rejected."""
        # We reject all absolute paths regardless of destination
        abs_path = str(workspace / "src" / "index.ts")
        with pytest.raises(ValueError, match="Absolute paths are not allowed"):
            _safe_path(abs_path)


@pytest.mark.unit
class TestSafePathSymlink:
    """Symlinks that resolve outside workspace must be rejected."""

    def test_symlink_escape(self, workspace):
        """A symlink pointing outside workspace is caught via realpath."""
        # Create a symlink inside workspace pointing outside
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
        """A symlink pointing within workspace is allowed."""
        (workspace / "actual_dir").mkdir()
        (workspace / "actual_dir" / "file.txt").write_text("hello")
        os.symlink(str(workspace / "actual_dir"), str(workspace / "link_dir"))
        result = _safe_path("link_dir/file.txt")
        assert result == os.path.realpath(workspace / "actual_dir" / "file.txt")


@pytest.mark.unit
class TestSafePathEdgeCases:
    """Edge cases and boundary conditions."""

    def test_workspace_not_set(self):
        """Raises when workspace is empty."""
        fix_agent._WORKSPACE = ""
        with pytest.raises(ValueError, match="Workspace not set"):
            _safe_path("anything")

    def test_empty_relative_path(self, workspace):
        """Empty string resolves to workspace root (normpath makes it '.')."""
        # os.path.normpath("") returns ".", joined with workspace = workspace
        result = _safe_path("")
        assert result == os.path.realpath(workspace)

    def test_path_with_null_byte(self, workspace):
        """Path with null byte raises (OS rejects it)."""
        with pytest.raises((ValueError, OSError)):
            _safe_path("src/\x00evil.ts")
