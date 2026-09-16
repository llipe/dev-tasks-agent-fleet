"""
Component tests for ``run_gitleaks()`` (spec S8.5, PRD requirements 16/18/19,
story S-129 AC-23/AC-24-adjacent groundwork + AC-27) with the
``subprocess.run`` call mocked -- the actual ``gitleaks`` binary is never
invoked.

Covers:
  - Zero-findings path (clean report) -> ``ScanStatus.PASSED``.
  - Findings-bearing path -> ``ScanStatus.PASSED`` with normalized findings,
    severities always CRITICAL, remediation always ``None``.
  - Unparseable JSON report content -> non-fatal ``ScanStatus.FAILED`` (PRD
    requirement 18), findings excluded, no exception propagates.
  - Process timeout (``subprocess.TimeoutExpired``) -> non-fatal
    ``ScanStatus.FAILED`` (PRD requirement 19), findings excluded.
  - Binary-missing / crash-to-start (``OSError``) -> non-fatal
    ``ScanStatus.FAILED``.
  - The exact command shape: ``--report-format json``, ``--report-path
    /dev/stdout`` (this module's documented stdout-capture deviation --
    see ``gitleaks_runner.py``'s module docstring), ``--no-git``,
    ``--exit-code 0`` (a findings-bearing exit is not a crash, same
    reasoning as Semgrep's ignored exit code).
  - ``SCANNER_TIMEOUT`` passed through as ``timeout=`` on the subprocess
    call, independent of any other scanner's timeout.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scanners.gitleaks_runner import run_gitleaks
from scanners.types import ScanStatus

_FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text()


def _completed_process(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["gitleaks"], returncode=returncode, stdout=stdout, stderr=""
    )


class TestRunGitleaksZeroFindings:
    @patch("scanners.gitleaks_runner.subprocess.run")
    def test_clean_repo_returns_passed_with_no_findings(self, mock_run):
        mock_run.return_value = _completed_process(_load_fixture("gitleaks_clean.json"))

        result = run_gitleaks(Path("/workspace"), timeout=600)

        assert result.tool == "gitleaks"
        assert result.status is ScanStatus.PASSED
        assert result.findings == []
        assert result.reason is None


class TestRunGitleaksFindingsBearing:
    @patch("scanners.gitleaks_runner.subprocess.run")
    def test_findings_bearing_repo_returns_passed_with_normalized_findings(self, mock_run):
        # Gitleaks is invoked with --exit-code 0 (see module docstring), so a
        # findings-bearing run still exits 0 -- but this must hold even if a
        # non-zero code leaks through some other path, mirroring Semgrep's
        # "non-zero exit alone is not a failure" contract.
        mock_run.return_value = _completed_process(
            _load_fixture("gitleaks_findings.json"), returncode=1
        )

        result = run_gitleaks(Path("/workspace"), timeout=600)

        assert result.status is ScanStatus.PASSED
        assert len(result.findings) == 3
        assert result.reason is None
        assert all(f.severity.value == "critical" for f in result.findings)
        assert all(f.remediation is None for f in result.findings)


class TestRunGitleaksUnparseableOutput:
    @patch("scanners.gitleaks_runner.subprocess.run")
    def test_invalid_json_stdout_is_non_fatal_failed(self, mock_run):
        mock_run.return_value = _completed_process("not valid json{{{")

        result = run_gitleaks(Path("/workspace"), timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert result.reason is not None
        assert result.tool == "gitleaks"

    @patch("scanners.gitleaks_runner.subprocess.run")
    def test_structurally_unexpected_payload_is_non_fatal_failed(self, mock_run):
        mock_run.return_value = _completed_process(json.dumps({"unexpected": "shape"}))

        result = run_gitleaks(Path("/workspace"), timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert result.reason is not None

    @patch("scanners.gitleaks_runner.subprocess.run")
    def test_leak_missing_required_field_is_non_fatal_failed(self, mock_run):
        mock_run.return_value = _completed_process(json.dumps([{"RuleID": "x"}]))

        result = run_gitleaks(Path("/workspace"), timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert result.reason is not None


class TestRunGitleaksTimeout:
    @patch("scanners.gitleaks_runner.subprocess.run")
    def test_process_timeout_is_non_fatal_failed(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["gitleaks"], timeout=600)

        result = run_gitleaks(Path("/workspace"), timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert result.reason is not None
        assert "600" in result.reason


class TestRunGitleaksCrash:
    @patch("scanners.gitleaks_runner.subprocess.run")
    def test_binary_missing_is_non_fatal_failed(self, mock_run):
        mock_run.side_effect = OSError("gitleaks: command not found")

        result = run_gitleaks(Path("/workspace"), timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert result.reason is not None


class TestRunGitleaksCommandShape:
    @patch("scanners.gitleaks_runner.subprocess.run")
    def test_command_shape_matches_documented_invocation(self, mock_run):
        mock_run.return_value = _completed_process(_load_fixture("gitleaks_clean.json"))

        run_gitleaks(Path("/workspace/repo"), timeout=600)

        assert mock_run.call_count == 1
        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "gitleaks"
        assert "detect" in cmd
        assert "--report-format" in cmd
        assert cmd[cmd.index("--report-format") + 1] == "json"
        assert "--report-path" in cmd
        assert cmd[cmd.index("--report-path") + 1] == "/dev/stdout"
        assert "--no-git" in cmd
        assert "--exit-code" in cmd
        assert cmd[cmd.index("--exit-code") + 1] == "0"
        assert "--source" in cmd
        assert cmd[cmd.index("--source") + 1] == str(Path("/workspace/repo"))

    @patch("scanners.gitleaks_runner.subprocess.run")
    def test_scanner_timeout_is_passed_through_independently(self, mock_run):
        mock_run.return_value = _completed_process(_load_fixture("gitleaks_clean.json"))

        run_gitleaks(Path("/workspace"), timeout=42)

        _, kwargs = mock_run.call_args
        assert kwargs["timeout"] == 42


class TestRunGitleaksDoesNotRaiseOnAnyMockedPath:
    """No mocked scenario above may propagate an exception out of
    ``run_gitleaks`` -- PRD requirement 18 is a non-fatal, per-tool
    contract, never a crash of the overall run."""

    @pytest.mark.parametrize(
        "side_effect",
        [
            subprocess.TimeoutExpired(cmd=["gitleaks"], timeout=600),
            OSError("boom"),
        ],
    )
    @patch("scanners.gitleaks_runner.subprocess.run")
    def test_no_exception_propagates(self, mock_run, side_effect):
        mock_run.side_effect = side_effect
        result = run_gitleaks(Path("/workspace"), timeout=600)
        assert result is not None
