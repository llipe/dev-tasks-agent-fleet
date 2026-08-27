"""Unit tests for the validation runner."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from toolchain import ScriptContract
from validator import (
    CheckStatus,
    ValidationResult,
    run_format,
    run_lint,
    run_tests,
    run_typecheck,
    run_validation,
)


def _ok(stdout: str = "ok") -> MagicMock:
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stdout = stdout
    proc.stderr = ""
    return proc


def _fail(stdout: str = "", stderr: str = "boom") -> subprocess.CalledProcessError:
    exc = subprocess.CalledProcessError(1, ["cmd"])
    exc.stdout = stdout
    exc.stderr = stderr
    return exc


class TestValidationResultDataclass:
    def test_defaults_passed_true_when_no_failures(self):
        result = ValidationResult()
        result.record("test", CheckStatus.PASSED, "ok")
        assert result.passed is True

    def test_failed_check_marks_not_passed(self):
        result = ValidationResult()
        result.record("test", CheckStatus.FAILED, "err")
        assert result.passed is False

    def test_skipped_check_does_not_fail(self):
        result = ValidationResult()
        result.record("lint", CheckStatus.SKIPPED, "no lint script")
        result.record("test", CheckStatus.PASSED, "ok")
        assert result.passed is True

    def test_per_check_status_recorded(self):
        result = ValidationResult()
        result.record("lint", CheckStatus.PASSED, "lint ok")
        assert result.checks["lint"].status == CheckStatus.PASSED
        assert result.checks["lint"].output == "lint ok"


class TestIndividualRunners:
    @patch("validator._run")
    def test_run_lint_passes(self, mock_run):
        mock_run.return_value = _ok()
        contract = ScriptContract(test="test", lint="lint")
        result = ValidationResult()
        run_lint("/ws", "pnpm", contract, result)
        assert result.checks["lint"].status == CheckStatus.PASSED

    def test_run_lint_skipped_when_absent(self):
        contract = ScriptContract(test="test", lint=None)
        result = ValidationResult()
        run_lint("/ws", "pnpm", contract, result)
        assert result.checks["lint"].status == CheckStatus.SKIPPED

    @patch("validator._run")
    def test_run_lint_fix_and_retry_success(self, mock_run):
        # First lint fails, fix succeeds, re-check passes.
        contract = ScriptContract(test="test", lint="lint", lint_fix="lint:fix")
        mock_run.side_effect = [_fail(), _ok("fixed"), _ok("clean")]
        result = ValidationResult()
        run_lint("/ws", "pnpm", contract, result)
        assert result.checks["lint"].status == CheckStatus.PASSED
        assert mock_run.call_count == 3

    @patch("validator._run")
    def test_run_lint_fails_when_no_fix_variant(self, mock_run):
        contract = ScriptContract(test="test", lint="lint", lint_fix=None)
        mock_run.side_effect = _fail()
        result = ValidationResult()
        run_lint("/ws", "pnpm", contract, result)
        assert result.checks["lint"].status == CheckStatus.FAILED

    @patch("validator._run")
    def test_run_lint_fails_when_fix_does_not_help(self, mock_run):
        contract = ScriptContract(test="test", lint="lint", lint_fix="lint:fix")
        # lint fails, fix runs, re-check still fails.
        mock_run.side_effect = [_fail(), _ok("fixed"), _fail(stderr="still broken")]
        result = ValidationResult()
        run_lint("/ws", "pnpm", contract, result)
        assert result.checks["lint"].status == CheckStatus.FAILED

    @patch("validator._run")
    def test_run_format_fix_and_retry(self, mock_run):
        contract = ScriptContract(test="test", format="format", format_fix="format:fix")
        mock_run.side_effect = [_fail(), _ok(), _ok()]
        result = ValidationResult()
        run_format("/ws", "pnpm", contract, result)
        assert result.checks["format"].status == CheckStatus.PASSED

    @patch("validator._run")
    def test_run_typecheck_no_fix_retry(self, mock_run):
        # typecheck has no fix variant; a failure stays failed.
        contract = ScriptContract(test="test", typecheck="typecheck")
        mock_run.side_effect = _fail()
        result = ValidationResult()
        run_typecheck("/ws", "pnpm", contract, result)
        assert result.checks["typecheck"].status == CheckStatus.FAILED
        assert mock_run.call_count == 1

    @patch("validator._run")
    def test_run_tests_uses_test_timeout(self, mock_run):
        mock_run.return_value = _ok()
        contract = ScriptContract(test="test")
        result = ValidationResult()
        run_tests("/ws", "npm", contract, result)
        assert result.checks["test"].status == CheckStatus.PASSED
        # test runner uses the longer TEST_TIMEOUT, not the default tool timeout
        from config import TEST_TIMEOUT

        assert mock_run.call_args[0][2] == TEST_TIMEOUT

    @patch("validator._run")
    def test_command_uses_npm_run(self, mock_run):
        mock_run.return_value = _ok()
        contract = ScriptContract(test="test", lint="lint")
        result = ValidationResult()
        run_lint("/ws", "npm", contract, result)
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["npm", "run", "lint"]

    @patch("validator._run")
    def test_command_uses_pnpm(self, mock_run):
        mock_run.return_value = _ok()
        contract = ScriptContract(test="test", lint="lint")
        result = ValidationResult()
        run_lint("/ws", "pnpm", contract, result)
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "pnpm"
        assert "lint" in cmd


class TestRunValidation:
    @patch("validator._run")
    def test_all_pass(self, mock_run):
        mock_run.return_value = _ok()
        contract = ScriptContract(test="test", lint="lint", format="format", typecheck="typecheck")
        result = run_validation("/ws", "pnpm", contract)
        assert result.passed is True
        assert all(
            result.checks[c].status == CheckStatus.PASSED
            for c in ("lint", "format", "typecheck", "test")
        )

    @patch("validator._run")
    def test_optional_absent_are_skipped_run_continues(self, mock_run):
        mock_run.return_value = _ok()
        contract = ScriptContract(test="test")  # no optional scripts
        result = run_validation("/ws", "pnpm", contract)
        assert result.passed is True
        assert result.checks["lint"].status == CheckStatus.SKIPPED
        assert result.checks["format"].status == CheckStatus.SKIPPED
        assert result.checks["typecheck"].status == CheckStatus.SKIPPED
        assert result.checks["test"].status == CheckStatus.PASSED

    @patch("validator._run")
    def test_test_failure_fails_overall(self, mock_run):
        contract = ScriptContract(test="test")

        def side_effect(cmd, cwd, timeout):
            if "test" in cmd:
                raise _fail(stderr="test broke")
            return _ok()

        mock_run.side_effect = side_effect
        result = run_validation("/ws", "pnpm", contract)
        assert result.passed is False
        assert result.checks["test"].status == CheckStatus.FAILED

    @patch("validator._run")
    def test_order_lint_format_typecheck_test(self, mock_run):
        called_scripts: list[str] = []

        def side_effect(cmd, cwd, timeout):
            # capture the script name (last positional token for pnpm run form)
            called_scripts.append(cmd[-1])
            return _ok()

        mock_run.side_effect = side_effect
        contract = ScriptContract(test="test", lint="lint", format="format", typecheck="typecheck")
        run_validation("/ws", "pnpm", contract)
        # lint before format before typecheck before test
        assert called_scripts.index("lint") < called_scripts.index("format")
        assert called_scripts.index("format") < called_scripts.index("typecheck")
        assert called_scripts.index("typecheck") < called_scripts.index("test")
