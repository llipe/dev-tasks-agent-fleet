"""
Unit tests for the fix agent's 5 bounded tools (spec §12, PRD AC20, story
S-138). Ported near-verbatim from the sibling agent's own
`tests/unit/test_fix_tools.py` -- not named in this story's task list
explicitly, but added proactively (this story's completion instructions:
"apply proactively" the same rigor as prior stories) to exercise the tool
bodies directly rather than leaving `_safe_path`'s only exercised call site
the standalone unit tests -- the tools are the actual attack surface the
LLM's tool calls go through in production.

These test the underlying tool functions directly (via `__wrapped__`) to
verify path safety, output handling, and truncation. The tools are
decorated with Strands' `@tool`, so the original callable is accessed via
`__wrapped__`.
"""

from __future__ import annotations

import pytest

import fix_agent

_shell = fix_agent.shell.__wrapped__  # type: ignore[attr-defined]
_read_file = fix_agent.read_file.__wrapped__  # type: ignore[attr-defined]
_write_file = fix_agent.write_file.__wrapped__  # type: ignore[attr-defined]
_find_files = fix_agent.find_files.__wrapped__  # type: ignore[attr-defined]
_grep_code = fix_agent.grep_code.__wrapped__  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def workspace(tmp_path):
    """Create a workspace and set it on the fix_agent module."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("answer = 42\n")
    (tmp_path / "README.md").write_text("# Test project\nhello world\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("module.exports = {};")
    fix_agent._WORKSPACE = str(tmp_path)
    yield tmp_path
    fix_agent._WORKSPACE = ""


@pytest.mark.unit
class TestShellTool:
    def test_runs_command(self, workspace):
        out = _shell("echo hello")
        assert "hello" in out

    def test_runs_in_workspace_cwd(self, workspace):
        out = _shell("pwd")
        assert str(workspace) in out or workspace.name in out

    def test_nonzero_exit_reported(self, workspace):
        out = _shell("exit 3")
        assert "EXIT CODE 3" in out

    def test_workspace_not_set(self):
        fix_agent._WORKSPACE = ""
        out = _shell("echo hi")
        assert "ERROR: Workspace not set" in out

    def test_no_output_command(self, workspace):
        out = _shell("true")
        assert out == "(no output)"


@pytest.mark.unit
class TestReadFileTool:
    def test_reads_file(self, workspace):
        out = _read_file("src/app.py")
        assert "answer = 42" in out

    def test_rejects_traversal(self, workspace):
        out = _read_file("../../etc/passwd")
        assert out.startswith("ERROR:")
        assert "escapes workspace" in out

    def test_rejects_absolute(self, workspace):
        out = _read_file("/etc/passwd")
        assert out.startswith("ERROR:")
        assert "Absolute" in out

    def test_missing_file(self, workspace):
        out = _read_file("does/not/exist.txt")
        assert out.startswith("ERROR: Cannot read file")


@pytest.mark.unit
class TestWriteFileTool:
    def test_writes_file(self, workspace):
        out = _write_file("src/new.py", "x = 1\n")
        assert out.startswith("OK:")
        assert (workspace / "src" / "new.py").read_text() == "x = 1\n"

    def test_creates_parent_dirs(self, workspace):
        out = _write_file("deep/nested/file.py", "hi")
        assert out.startswith("OK:")
        assert (workspace / "deep" / "nested" / "file.py").read_text() == "hi"

    def test_rejects_traversal(self, workspace):
        out = _write_file("../escape.py", "evil")
        assert out.startswith("ERROR:")
        assert "escapes workspace" in out
        assert not (workspace.parent / "escape.py").exists()

    def test_rejects_absolute(self, workspace):
        out = _write_file("/tmp/evil.py", "evil")
        assert out.startswith("ERROR:")
        assert "Absolute" in out

    def test_overwrites_existing(self, workspace):
        _write_file("src/app.py", "changed = True\n")
        assert (workspace / "src" / "app.py").read_text() == "changed = True\n"


@pytest.mark.unit
class TestFindFilesTool:
    def test_finds_by_glob(self, workspace):
        out = _find_files("**/*.py")
        assert "src/app.py" in out

    def test_excludes_node_modules(self, workspace):
        out = _find_files("**/*.js")
        assert "node_modules" not in out

    def test_no_matches(self, workspace):
        out = _find_files("**/*.rs")
        assert out == "(no files matched)"

    def test_workspace_not_set(self):
        fix_agent._WORKSPACE = ""
        out = _find_files("*.py")
        assert "ERROR: Workspace not set" in out


@pytest.mark.unit
class TestGrepCodeTool:
    def test_finds_pattern(self, workspace):
        out = _grep_code("answer", "*.py")
        assert "app.py" in out
        assert "answer" in out

    def test_no_matches(self, workspace):
        out = _grep_code("this_string_does_not_exist_anywhere")
        assert out == "(no matches)"

    def test_workspace_not_set(self):
        fix_agent._WORKSPACE = ""
        out = _grep_code("anything")
        assert "ERROR: Workspace not set" in out


@pytest.mark.unit
class TestSystemPromptAndPrompt:
    def test_forbids_out_of_scope_edits(self):
        prompt = fix_agent.FIX_AGENT_SYSTEM_PROMPT
        assert "only" in prompt.lower()
        assert "one" in prompt.lower() or "single" in prompt.lower()

    def test_forbids_test_file_edits(self):
        prompt = fix_agent.FIX_AGENT_SYSTEM_PROMPT
        assert "test" in prompt.lower()
