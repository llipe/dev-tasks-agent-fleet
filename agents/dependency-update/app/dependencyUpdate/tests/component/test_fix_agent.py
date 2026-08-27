"""
Component tests for the LLM fix agent (fix_agent.py).

Tests with mocked Bedrock/Strands responses:
  - Verify tool calls are invoked via Strands Agent
  - Retry budget is respected (max_attempts honored)
  - max_attempts=0 → zero LLM calls
  - Fix loop marks llm_used and fix_attempts correctly
  - Agent exception doesn't crash the loop
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from fix_agent import run_fix_loop, verify_no_mandate_violation
from toolchain import ScriptContract
from validator import CheckStatus, ValidationResult


@pytest.fixture
def workspace(tmp_path):
    """Create a workspace with a package.json and test script."""
    pkg = {
        "name": "test-project",
        "version": "1.0.0",
        "dependencies": {"react": "^18.2.0"},
        "devDependencies": {"typescript": "^5.3.0"},
        "scripts": {"test": "jest", "lint": "eslint ."},
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("export const x = 1;")
    return tmp_path


@pytest.fixture
def scripts():
    """Standard script contract."""
    return ScriptContract(
        test="test",
        lint="lint",
        format=None,
        typecheck=None,
        lint_fix=None,
        format_fix=None,
        missing_optional=["format", "typecheck"],
    )


@pytest.fixture
def failing_result():
    """A ValidationResult with a failed test check."""
    result = ValidationResult()
    result.record("lint", CheckStatus.PASSED, "all good")
    result.record("test", CheckStatus.FAILED, "FAIL src/index.test.ts\nTypeError: x is not a fn")
    return result


@pytest.fixture
def passing_result():
    """A ValidationResult where everything passes."""
    result = ValidationResult()
    result.record("lint", CheckStatus.PASSED, "")
    result.record("test", CheckStatus.PASSED, "Tests: 5 passed")
    return result


@pytest.mark.component
class TestMaxAttemptsZero:
    """max_attempts=0 should result in zero LLM calls."""

    @patch("fix_agent.Agent")
    def test_zero_attempts_no_agent_call(
        self, mock_agent_class, workspace, scripts, failing_result
    ):
        """With max_attempts=0, the Agent is never instantiated."""
        result = run_fix_loop(str(workspace), "pnpm", scripts, 0, failing_result)
        mock_agent_class.assert_not_called()
        assert result is failing_result
        assert result.llm_used is False
        assert result.fix_attempts == 0


@pytest.mark.component
class TestRetryBudget:
    """Fix loop respects the attempt budget."""

    @patch("fix_agent.run_validation")
    @patch("fix_agent.Agent")
    def test_exhausts_budget(
        self, mock_agent_class, mock_validation, workspace, scripts, failing_result
    ):
        """Agent is called max_attempts times when validation keeps failing."""
        mock_agent_instance = MagicMock()
        mock_agent_class.return_value = mock_agent_instance

        # Validation always fails
        mock_validation.return_value = failing_result

        result = run_fix_loop(str(workspace), "pnpm", scripts, 3, failing_result)

        assert mock_agent_instance.call_count == 3
        assert result.fix_attempts == 3
        assert result.llm_used is True
        assert not result.passed

    @patch("fix_agent.run_validation")
    @patch("fix_agent.Agent")
    def test_stops_early_on_success(
        self, mock_agent_class, mock_validation, workspace, scripts, failing_result, passing_result
    ):
        """Agent stops when validation passes (doesn't exhaust budget)."""
        mock_agent_instance = MagicMock()
        mock_agent_class.return_value = mock_agent_instance

        # First attempt: still failing; second attempt: passes
        mock_validation.side_effect = [failing_result, passing_result]

        result = run_fix_loop(str(workspace), "pnpm", scripts, 5, failing_result)

        # Agent called twice (not 5 times)
        assert mock_agent_instance.call_count == 2
        assert result.fix_attempts == 2
        assert result.llm_used is True
        assert result.passed


@pytest.mark.component
class TestAgentException:
    """Agent exception doesn't crash the loop — validation still runs."""

    @patch("fix_agent.run_validation")
    @patch("fix_agent.Agent")
    def test_agent_error_continues(
        self, mock_agent_class, mock_validation, workspace, scripts, failing_result
    ):
        """If the Agent raises, the loop continues and re-validates."""
        mock_agent_instance = MagicMock()
        mock_agent_instance.side_effect = RuntimeError("model unavailable")
        mock_agent_class.return_value = mock_agent_instance

        mock_validation.return_value = failing_result

        result = run_fix_loop(str(workspace), "pnpm", scripts, 2, failing_result)

        # Still runs 2 attempts despite errors
        assert result.fix_attempts == 2
        assert result.llm_used is True


@pytest.mark.component
class TestToolCalls:
    """Verify tools are passed to the Agent."""

    @patch("fix_agent.run_validation")
    @patch("fix_agent.Agent")
    def test_tools_passed_to_agent(
        self, mock_agent_class, mock_validation, workspace, scripts, failing_result, passing_result
    ):
        """Agent is created with exactly 5 tools."""
        mock_agent_instance = MagicMock()
        mock_agent_class.return_value = mock_agent_instance
        mock_validation.return_value = passing_result

        run_fix_loop(str(workspace), "pnpm", scripts, 1, failing_result)

        # Check the Agent constructor was called with tools kwarg
        call_kwargs = mock_agent_class.call_args[1]
        assert "tools" in call_kwargs
        assert len(call_kwargs["tools"]) == 5

        # Verify tool names
        tool_names = {t.__name__ for t in call_kwargs["tools"]}
        assert tool_names == {"shell", "read_file", "write_file", "find_files", "grep_code"}

    @patch("fix_agent.run_validation")
    @patch("fix_agent.Agent")
    def test_system_prompt_passed(
        self, mock_agent_class, mock_validation, workspace, scripts, failing_result, passing_result
    ):
        """Agent is created with the system prompt."""
        mock_agent_instance = MagicMock()
        mock_agent_class.return_value = mock_agent_instance
        mock_validation.return_value = passing_result

        run_fix_loop(str(workspace), "pnpm", scripts, 1, failing_result)

        call_kwargs = mock_agent_class.call_args[1]
        assert "system_prompt" in call_kwargs
        assert "MUST FOLLOW" in call_kwargs["system_prompt"]
        assert "Do NOT delete" in call_kwargs["system_prompt"]


@pytest.mark.component
class TestLlmUsedTracking:
    """Verify llm_used and fix_attempts are tracked correctly."""

    @patch("fix_agent.run_validation")
    @patch("fix_agent.Agent")
    def test_marks_llm_used(
        self, mock_agent_class, mock_validation, workspace, scripts, failing_result, passing_result
    ):
        """Result has llm_used=True after running."""
        mock_agent_instance = MagicMock()
        mock_agent_class.return_value = mock_agent_instance
        mock_validation.return_value = passing_result

        result = run_fix_loop(str(workspace), "pnpm", scripts, 1, failing_result)
        assert result.llm_used is True
        assert result.fix_attempts == 1


@pytest.mark.component
class TestMandateIntegration:
    """Test mandate check integration with the fix loop."""

    def test_no_violation_when_pkg_unchanged(self, workspace):
        """No violations when package.json is not modified."""
        before = {
            "dependencies": {"react": "^18.2.0"},
            "devDependencies": {"typescript": "^5.3.0"},
        }
        violations = verify_no_mandate_violation(str(workspace), before)
        assert violations == []

    def test_violation_detected_after_model_changes(self, workspace):
        """If model modifies package.json, violation is detected."""
        before = {
            "dependencies": {"react": "^18.2.0"},
            "devDependencies": {"typescript": "^5.3.0"},
        }
        # Simulate model widening a range
        pkg = json.loads((workspace / "package.json").read_text())
        pkg["dependencies"]["react"] = "^19.0.0"
        (workspace / "package.json").write_text(json.dumps(pkg))

        violations = verify_no_mandate_violation(str(workspace), before)
        assert len(violations) == 1
        assert violations[0].package == "react"
        assert violations[0].before == "^18.2.0"
        assert violations[0].after == "^19.0.0"
