"""
Component tests for ``run_checkov()`` (spec §8.5, PRD requirements 17/18/19,
story S-131 AC1) with ``subprocess.run`` mocked -- the actual ``checkov``
binary is never invoked.

Covers:
  - The requirement 17 / AC-23 skip path: a workspace with no IaC files
    present is `ScanStatus.SKIPPED`, non-fatal, with a named `reason` --
    NOT `ScanStatus.FAILED`, and the `checkov` subprocess is never invoked
    at all (mirrors `run_trivy()`'s image-mode skip pattern, spec §8.5's
    canonical example for requirement 17).
  - The happy path: IaC present -> `checkov` invoked with `--output json`,
    output normalized into findings, `ScanStatus.PASSED`.
  - Failure paths -- crash-to-start, timeout, unparseable output -- are all
    non-fatal to the overall run (PRD requirement 18) but do mark this
    tool's own `ScanResult` as `FAILED`.
  - `SCANNER_TIMEOUT` passed through to the subprocess call (PRD
    requirement 19).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scanners.checkov_runner import run_checkov
from scanners.types import ScanStatus

_FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text()


def _completed_process(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["checkov"], returncode=returncode, stdout=stdout, stderr=""
    )


@pytest.fixture
def workspace_no_iac(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# hello\n")
    (tmp_path / "app.py").write_text("print('hi')\n")
    return tmp_path


@pytest.fixture
def workspace_with_terraform(tmp_path: Path) -> Path:
    (tmp_path / "main.tf").write_text('resource "aws_s3_bucket" "example" {}\n')
    return tmp_path


@pytest.fixture
def workspace_with_terraform_and_dockerfile(tmp_path: Path) -> Path:
    (tmp_path / "main.tf").write_text('resource "aws_s3_bucket" "example" {}\n')
    (tmp_path / "Dockerfile").write_text("FROM python:3.13-slim\n")
    return tmp_path


# ---------------------------------------------------------------------------
# AC-23 / requirement 17 -- no IaC files present -> SKIPPED, not FAILED.
# ---------------------------------------------------------------------------


class TestRunCheckovSkip:
    @patch("scanners.checkov_runner.subprocess.run")
    def test_skip_no_iac(self, mock_run, workspace_no_iac):
        result = run_checkov(workspace_no_iac, timeout=600)

        assert result.tool == "checkov"
        assert result.status is ScanStatus.SKIPPED
        assert result.findings == []
        assert result.reason is not None
        # Non-fatal, distinctly named -- never conflated with FAILED.
        assert result.status is not ScanStatus.FAILED
        # No subprocess call at all when IaC is absent.
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Happy path -- IaC present, subprocess invoked, output normalized.
# ---------------------------------------------------------------------------


class TestRunCheckovHappyPath:
    @patch("scanners.checkov_runner.subprocess.run")
    def test_runs_and_normalizes_findings(self, mock_run, workspace_with_terraform):
        mock_run.return_value = _completed_process(_load_fixture("checkov_no_severity.json"))

        result = run_checkov(workspace_with_terraform, timeout=600)

        assert result.status is ScanStatus.PASSED
        assert result.reason is None
        assert len(result.findings) == 2
        assert all(f.tool == "checkov" for f in result.findings)
        mock_run.assert_called_once()

    @patch("scanners.checkov_runner.subprocess.run")
    def test_mixed_terraform_and_dockerfile_workspace_runs(
        self, mock_run, workspace_with_terraform_and_dockerfile
    ):
        mock_run.return_value = _completed_process(_load_fixture("checkov_findings.json"))

        result = run_checkov(workspace_with_terraform_and_dockerfile, timeout=600)

        assert result.status is ScanStatus.PASSED
        assert len(result.findings) == 3

    @patch("scanners.checkov_runner.subprocess.run")
    def test_command_shape_uses_output_json_and_targets_workspace(
        self, mock_run, workspace_with_terraform
    ):
        mock_run.return_value = _completed_process(_load_fixture("checkov_clean.json"))

        run_checkov(workspace_with_terraform, timeout=600)

        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "checkov"
        assert "--output" in cmd
        assert "json" in cmd
        assert str(workspace_with_terraform) in cmd

    @patch("scanners.checkov_runner.subprocess.run")
    def test_scanner_timeout_passed_through(self, mock_run, workspace_with_terraform):
        mock_run.return_value = _completed_process(_load_fixture("checkov_clean.json"))

        run_checkov(workspace_with_terraform, timeout=42)

        assert mock_run.call_args.kwargs["timeout"] == 42

    @patch("scanners.checkov_runner.subprocess.run")
    def test_clean_scan_yields_no_findings_and_passed_status(
        self, mock_run, workspace_with_terraform
    ):
        mock_run.return_value = _completed_process(_load_fixture("checkov_clean.json"))

        result = run_checkov(workspace_with_terraform, timeout=600)

        assert result.status is ScanStatus.PASSED
        assert result.findings == []


# ---------------------------------------------------------------------------
# Failure paths -- non-fatal to the overall run, but reflected in the result.
# ---------------------------------------------------------------------------


class TestRunCheckovFailurePaths:
    @patch("scanners.checkov_runner.subprocess.run")
    def test_unparseable_output_is_non_fatal_failed(self, mock_run, workspace_with_terraform):
        mock_run.return_value = _completed_process("not valid json{{{")

        result = run_checkov(workspace_with_terraform, timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert result.reason is not None

    @patch("scanners.checkov_runner.subprocess.run")
    def test_timeout_is_non_fatal_failed(self, mock_run, workspace_with_terraform):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["checkov"], timeout=600)

        result = run_checkov(workspace_with_terraform, timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert result.reason is not None
        assert "600" in result.reason

    @patch("scanners.checkov_runner.subprocess.run")
    def test_binary_missing_is_non_fatal_failed(self, mock_run, workspace_with_terraform):
        mock_run.side_effect = OSError("checkov: command not found")

        result = run_checkov(workspace_with_terraform, timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert result.reason is not None

    @patch("scanners.checkov_runner.subprocess.run")
    def test_no_exception_propagates_out_of_run_checkov(self, mock_run, workspace_with_terraform):
        mock_run.side_effect = OSError("boom")
        result = run_checkov(workspace_with_terraform, timeout=600)
        assert result is not None
        assert result.status is ScanStatus.FAILED
