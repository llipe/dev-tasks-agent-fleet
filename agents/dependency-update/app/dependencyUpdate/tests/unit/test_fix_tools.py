"""
Unit tests for the fix agent's 5 bounded tools (req 45, 46).

These test the underlying tool functions directly (via __wrapped__) to verify
path safety, output handling, and truncation. The tools are decorated with
Strands' @tool, so we access the original callable via __wrapped__.
"""

from __future__ import annotations

import pytest

import fix_agent

# Access the raw callables behind the @tool decorator.
# The Strands @tool decorator preserves the original function on __wrapped__;
# the attribute is not in the tool's type stub, hence the type: ignore.
_shell = fix_agent.shell.__wrapped__  # type: ignore[attr-defined]
_read_file = fix_agent.read_file.__wrapped__  # type: ignore[attr-defined]
_write_file = fix_agent.write_file.__wrapped__  # type: ignore[attr-defined]
_find_files = fix_agent.find_files.__wrapped__  # type: ignore[attr-defined]
_grep_code = fix_agent.grep_code.__wrapped__  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def workspace(tmp_path):
    """Create a workspace and set it on the fix_agent module."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("export const answer = 42;\n")
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
        out = _read_file("src/index.ts")
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
        out = _write_file("src/new.ts", "const x = 1;")
        assert out.startswith("OK:")
        assert (workspace / "src" / "new.ts").read_text() == "const x = 1;"

    def test_creates_parent_dirs(self, workspace):
        out = _write_file("deep/nested/file.ts", "hi")
        assert out.startswith("OK:")
        assert (workspace / "deep" / "nested" / "file.ts").read_text() == "hi"

    def test_rejects_traversal(self, workspace):
        out = _write_file("../escape.txt", "evil")
        assert out.startswith("ERROR:")
        assert "escapes workspace" in out
        assert not (workspace.parent / "escape.txt").exists()

    def test_rejects_absolute(self, workspace):
        out = _write_file("/tmp/evil.txt", "evil")
        assert out.startswith("ERROR:")
        assert "Absolute" in out

    def test_overwrites_existing(self, workspace):
        _write_file("src/index.ts", "changed")
        assert (workspace / "src" / "index.ts").read_text() == "changed"


@pytest.mark.unit
class TestFindFilesTool:
    def test_finds_by_glob(self, workspace):
        out = _find_files("**/*.ts")
        assert "src/index.ts" in out

    def test_excludes_node_modules(self, workspace):
        out = _find_files("**/*.js")
        assert "node_modules" not in out

    def test_no_matches(self, workspace):
        out = _find_files("**/*.rs")
        assert out == "(no files matched)"

    def test_workspace_not_set(self):
        fix_agent._WORKSPACE = ""
        out = _find_files("*.ts")
        assert "ERROR: Workspace not set" in out


@pytest.mark.unit
class TestGrepCodeTool:
    def test_finds_pattern(self, workspace):
        out = _grep_code("answer", "*.ts")
        assert "index.ts" in out
        assert "answer" in out

    def test_no_matches(self, workspace):
        out = _grep_code("this_string_does_not_exist_anywhere")
        assert out == "(no matches)"

    def test_workspace_not_set(self):
        fix_agent._WORKSPACE = ""
        out = _grep_code("anything")
        assert "ERROR: Workspace not set" in out


@pytest.mark.unit
class TestSystemPrompt:
    def test_forbids_test_weakening(self):
        """req 47: prompt must forbid weakening tests."""
        prompt = fix_agent.FIX_AGENT_SYSTEM_PROMPT
        assert "weaken" in prompt.lower()
        assert "test" in prompt.lower()

    def test_forbids_range_widening(self):
        """req 47: prompt must forbid widening semver ranges / major bumps."""
        prompt = fix_agent.FIX_AGENT_SYSTEM_PROMPT
        assert "widen" in prompt.lower()
        assert "major" in prompt.lower()

    def test_forbids_dep_rollback(self):
        """req 47: prompt must forbid rolling back dependency versions."""
        prompt = fix_agent.FIX_AGENT_SYSTEM_PROMPT
        assert "roll" in prompt.lower() or "package.json" in prompt.lower()
