"""
Unit tests for `fix_agent._assert_diff_confined_to` -- the post-fix
mandate-violation-equivalent check (spec §12, story S-138, task 14.3/14.8).

After an LLM fix-agent attempt, the resulting working-tree diff MUST touch
only the single targeted finding's own `file_path`. This module verifies
that guarantee directly against a real git working tree (not mocked), per
this story's "verify, don't just constrain via prompt" philosophy (mirrors
S-137's re-scan gate rigor) -- and covers the deliberate widening beyond the
sibling agent's `git diff --name-only` (modified-tracked-files only)
pattern to also catch a brand-new untracked file the LLM's `write_file` tool
could create anywhere `_safe_path` alone would still permit (module
docstring in `fix_agent.py`; flagged as a pre-authorized "apply proactively"
correctness fix in this story's completion report).
"""

from __future__ import annotations

import subprocess

import pytest

from fix_agent import MandateViolationError, _assert_diff_confined_to, _changed_files


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)


def _commit_all(path, message="initial"):
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=path, check=True)


@pytest.fixture
def git_workspace(tmp_path):
    """A real git working tree with an initial committed file."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("import os\n")
    (tmp_path / "src" / "other.py").write_text("x = 1\n")
    _init_git_repo(tmp_path)
    _commit_all(tmp_path)
    return tmp_path


@pytest.mark.unit
class TestChangedFiles:
    """`_changed_files` covers both modified-tracked and untracked-new paths."""

    def test_no_changes_returns_empty_set(self, git_workspace):
        assert _changed_files(str(git_workspace)) == set()

    def test_modified_tracked_file_detected(self, git_workspace):
        (git_workspace / "src" / "app.py").write_text("import os\nimport sys\n")
        assert _changed_files(str(git_workspace)) == {"src/app.py"}

    def test_untracked_new_file_detected(self, git_workspace):
        """A brand-new file the LLM's write_file tool created (never
        committed, never previously tracked) must still be reported --
        `git diff --name-only` alone would silently miss this."""
        (git_workspace / "src" / "new_helper.py").write_text("y = 2\n")
        assert _changed_files(str(git_workspace)) == {"src/new_helper.py"}

    def test_multiple_changes_all_detected(self, git_workspace):
        (git_workspace / "src" / "app.py").write_text("import os\nimport sys\n")
        (git_workspace / "src" / "evil.py").write_text("z = 3\n")
        assert _changed_files(str(git_workspace)) == {"src/app.py", "src/evil.py"}

    def test_non_git_workspace_returns_empty_set(self, tmp_path):
        """A non-git workspace degrades to an empty set, never raises."""
        (tmp_path / "app.py").write_text("x = 1\n")
        assert _changed_files(str(tmp_path)) == set()

    def test_missing_workspace_path_returns_empty_set(self, tmp_path):
        """A workspace path that does not exist degrades to an empty set."""
        assert _changed_files(str(tmp_path / "does-not-exist")) == set()


@pytest.mark.unit
class TestAssertDiffConfinedTo:
    """`_assert_diff_confined_to` raises MandateViolationError on any
    out-of-scope change, and is a no-op when the diff is confined."""

    def test_no_changes_passes(self, git_workspace):
        _assert_diff_confined_to(str(git_workspace), "src/app.py")

    def test_change_confined_to_target_file_passes(self, git_workspace):
        (git_workspace / "src" / "app.py").write_text("import os\nimport sys\n")
        _assert_diff_confined_to(str(git_workspace), "src/app.py")

    def test_change_to_other_tracked_file_raises(self, git_workspace):
        """The finding names src/app.py; the LLM instead (or additionally)
        edited src/other.py -- out of scope, must raise."""
        (git_workspace / "src" / "other.py").write_text("x = 2\n")
        with pytest.raises(MandateViolationError, match="src/other.py"):
            _assert_diff_confined_to(str(git_workspace), "src/app.py")

    def test_change_to_target_plus_extra_file_raises(self, git_workspace):
        """Even when the target file IS correctly touched, an additional
        out-of-scope change still raises -- partial compliance is not
        trusted."""
        (git_workspace / "src" / "app.py").write_text("import os\nimport sys\n")
        (git_workspace / "src" / "other.py").write_text("x = 2\n")
        with pytest.raises(MandateViolationError, match="src/other.py"):
            _assert_diff_confined_to(str(git_workspace), "src/app.py")

    def test_new_untracked_file_outside_scope_raises(self, git_workspace):
        """A hallucinated/confused write_file call creating a brand-new
        file outside the finding's path must be caught -- this is the
        scenario spec §12 and task 14.8 explicitly call out."""
        (git_workspace / "src" / "unexpected_new_file.py").write_text("q = 1\n")
        with pytest.raises(MandateViolationError, match="unexpected_new_file.py"):
            _assert_diff_confined_to(str(git_workspace), "src/app.py")

    def test_error_message_names_every_out_of_scope_path(self, git_workspace):
        """Multiple out-of-scope files are all named in the error, not just
        the first one found."""
        (git_workspace / "src" / "other.py").write_text("x = 2\n")
        (git_workspace / "src" / "third.py").write_text("w = 3\n")
        with pytest.raises(MandateViolationError) as exc_info:
            _assert_diff_confined_to(str(git_workspace), "src/app.py")
        message = str(exc_info.value)
        assert "src/other.py" in message
        assert "src/third.py" in message
