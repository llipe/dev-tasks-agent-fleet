"""
Component tests for ``run_semgrep()`` (spec §8.5, PRD requirements 16/18/19,
story S-128 AC3-AC4) with the ``subprocess.run`` call mocked -- the actual
``semgrep`` binary is never invoked.

Covers:
  - Zero-findings path (clean fixture stdout) -> ``ScanStatus.PASSED``.
  - Findings-bearing path -> ``ScanStatus.PASSED`` with normalized findings.
  - Unparseable JSON stdout -> non-fatal ``ScanStatus.FAILED`` (PRD
    requirement 18), findings excluded, no exception propagates.
  - Process timeout (``subprocess.TimeoutExpired``) -> non-fatal
    ``ScanStatus.FAILED`` (PRD requirement 19), findings excluded.
  - Binary-missing / crash-to-start (``OSError``) -> non-fatal
    ``ScanStatus.FAILED``.
  - The exact pinned-ruleset command shape (PRD requirement 52) -- one
    ``--config <id>`` pair per ``RULESET`` entry, never a single joined
    string and never ``--config auto``.
  - ``SCANNER_TIMEOUT`` passed through as ``timeout=`` on the subprocess
    call, independent of any other scanner's timeout.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scanners.semgrep_runner import RULESET, run_semgrep
from scanners.types import ScanStatus

_FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text()


def _completed_process(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["semgrep"], returncode=returncode, stdout=stdout, stderr=""
    )


class TestRunSemgrepZeroFindings:
    @patch("scanners.semgrep_runner.subprocess.run")
    def test_clean_repo_returns_passed_with_no_findings(self, mock_run):
        mock_run.return_value = _completed_process(_load_fixture("semgrep_clean.json"))

        result = run_semgrep(Path("/workspace"), timeout=600)

        assert result.tool == "semgrep"
        assert result.status is ScanStatus.PASSED
        assert result.findings == []
        assert result.reason is None


class TestRunSemgrepFindingsBearing:
    @patch("scanners.semgrep_runner.subprocess.run")
    def test_findings_bearing_repo_returns_passed_with_normalized_findings(self, mock_run):
        # Semgrep exits 1 when findings are present -- this is not a crash,
        # so it MUST NOT be treated as FAILED (only unparseable/timeout/crash
        # are, per PRD requirement 18).
        mock_run.return_value = _completed_process(
            _load_fixture("semgrep_findings.json"), returncode=1
        )

        result = run_semgrep(Path("/workspace"), timeout=600)

        assert result.status is ScanStatus.PASSED
        assert len(result.findings) == 4
        assert result.reason is None


class TestRunSemgrepUnparseableOutput:
    @patch("scanners.semgrep_runner.subprocess.run")
    def test_invalid_json_stdout_is_non_fatal_failed(self, mock_run):
        mock_run.return_value = _completed_process("not valid json{{{")

        result = run_semgrep(Path("/workspace"), timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert result.reason is not None
        assert result.tool == "semgrep"

    @patch("scanners.semgrep_runner.subprocess.run")
    def test_missing_results_key_is_non_fatal_failed(self, mock_run):
        mock_run.return_value = _completed_process(json.dumps({"errors": []}))

        result = run_semgrep(Path("/workspace"), timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert result.reason is not None


class TestRunSemgrepTimeout:
    @patch("scanners.semgrep_runner.subprocess.run")
    def test_process_timeout_is_non_fatal_failed(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["semgrep"], timeout=600)

        result = run_semgrep(Path("/workspace"), timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert result.reason is not None
        assert "600" in result.reason


class TestRunSemgrepCrash:
    @patch("scanners.semgrep_runner.subprocess.run")
    def test_binary_missing_is_non_fatal_failed(self, mock_run):
        mock_run.side_effect = OSError("semgrep: command not found")

        result = run_semgrep(Path("/workspace"), timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert result.reason is not None


class TestRunSemgrepCommandShape:
    @patch("scanners.semgrep_runner.subprocess.run")
    def test_command_emits_one_config_flag_per_ruleset_entry(self, mock_run):
        mock_run.return_value = _completed_process(_load_fixture("semgrep_clean.json"))

        run_semgrep(Path("/workspace/repo"), timeout=600)

        assert mock_run.call_count == 1
        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "semgrep"
        assert "--json" in cmd
        for ruleset_id in RULESET:
            idx = cmd.index(ruleset_id)
            assert cmd[idx - 1] == "--config"
        assert "auto" not in cmd
        assert cmd[-1] == str(Path("/workspace/repo"))

    @patch("scanners.semgrep_runner.subprocess.run")
    def test_scanner_timeout_is_passed_through_independently(self, mock_run):
        mock_run.return_value = _completed_process(_load_fixture("semgrep_clean.json"))

        run_semgrep(Path("/workspace"), timeout=42)

        _, kwargs = mock_run.call_args
        assert kwargs["timeout"] == 42


class TestRunSemgrepDoesNotRaiseOnAnyMockedPath:
    """No mocked scenario above may propagate an exception out of
    ``run_semgrep`` -- PRD requirement 18 is a non-fatal, per-tool
    contract, never a crash of the overall run."""

    @pytest.mark.parametrize(
        "side_effect",
        [
            subprocess.TimeoutExpired(cmd=["semgrep"], timeout=600),
            OSError("boom"),
        ],
    )
    @patch("scanners.semgrep_runner.subprocess.run")
    def test_no_exception_propagates(self, mock_run, side_effect):
        mock_run.side_effect = side_effect
        result = run_semgrep(Path("/workspace"), timeout=600)
        assert result is not None
