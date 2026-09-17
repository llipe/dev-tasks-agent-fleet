"""
Component tests for ``run_trivy()`` (spec §8.5, PRD requirements 16/17/18/19,
story S-130 AC1) with ``subprocess.run`` mocked -- the actual ``trivy``
binary is never invoked.

Covers the three-mode dispatch:
  - `fs` and `config` modes always run.
  - `image` mode runs only when a Dockerfile is present in the workspace
    (PRD requirement 17), targeting the base image parsed from the
    Dockerfile's first `FROM` line (a representative base image, not the
    fully-built image -- see ``scanners/trivy_runner.py`` module docstring).
  - `image` mode is *skipped*, not failed, when no Dockerfile is present --
    `run_trivy()` still returns ``ScanStatus.PASSED`` from the fs/config
    findings alone; the `trivy image` subprocess is never invoked at all.
  - Findings from all attempted modes are combined into one ``ScanResult``.
  - A crash/timeout/unparseable-output in any attempted mode is non-fatal to
    the overall run (PRD requirement 18) but does mark the aggregate
    ``ScanResult`` as ``FAILED`` (Trivy itself did not complete its mission),
    with `reason` naming which mode(s) failed.
  - `SCANNER_TIMEOUT` passed through to every subprocess call, independent
    per call (PRD requirement 19).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scanners.trivy_runner import run_trivy
from scanners.types import ScanStatus

_FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text()


def _completed_process(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["trivy"], returncode=returncode, stdout=stdout, stderr=""
    )


@pytest.fixture
def workspace_no_dockerfile(tmp_path: Path) -> Path:
    (tmp_path / "package-lock.json").write_text("{}")
    return tmp_path


@pytest.fixture
def workspace_with_dockerfile(tmp_path: Path) -> Path:
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / "Dockerfile").write_text("FROM python:3.13-slim\nCOPY . /app\n")
    return tmp_path


# ---------------------------------------------------------------------------
# Dispatch shape -- no Dockerfile: fs + config only, image never invoked.
# ---------------------------------------------------------------------------


class TestRunTrivyNoDockerfile:
    @patch("scanners.trivy_runner.subprocess.run")
    def test_image_mode_is_skipped_not_failed(self, mock_run, workspace_no_dockerfile):
        mock_run.return_value = _completed_process(_load_fixture("trivy_clean.json"))

        result = run_trivy(workspace_no_dockerfile, timeout=600)

        assert result.status is ScanStatus.PASSED
        assert result.tool == "trivy"
        # Exactly two subprocess calls -- fs and config. No `trivy image ...`
        # invocation at all when no Dockerfile is present (req 17).
        assert mock_run.call_count == 2
        invoked_subcommands = {call.args[0][1] for call in mock_run.call_args_list}
        assert invoked_subcommands == {"fs", "config"}


# ---------------------------------------------------------------------------
# Dispatch shape -- Dockerfile present: all three modes run.
# ---------------------------------------------------------------------------


class TestRunTrivyWithDockerfile:
    @patch("scanners.trivy_runner.subprocess.run")
    def test_image_mode_targets_the_base_image_from_the_dockerfile(
        self, mock_run, workspace_with_dockerfile
    ):
        mock_run.return_value = _completed_process(_load_fixture("trivy_clean.json"))

        run_trivy(workspace_with_dockerfile, timeout=600)

        assert mock_run.call_count == 3
        image_call = next(call for call in mock_run.call_args_list if call.args[0][1] == "image")
        assert image_call.args[0][-1] == "python:3.13-slim"

    @patch("scanners.trivy_runner.subprocess.run")
    def test_findings_from_all_three_modes_are_combined(self, mock_run, workspace_with_dockerfile):
        fixtures_by_mode = {
            "fs": _load_fixture("trivy_fs_npm.json"),
            "config": _load_fixture("trivy_config.json"),
            "image": _load_fixture("trivy_image.json"),
        }

        def _side_effect(cmd, **kwargs):
            mode = cmd[1]
            return _completed_process(fixtures_by_mode[mode])

        mock_run.side_effect = _side_effect

        result = run_trivy(workspace_with_dockerfile, timeout=600)

        assert result.status is ScanStatus.PASSED
        # 3 (fs npm) + 3 (config: 2 Dockerfile FAIL rows + 1 main.tf row,
        # PASS row excluded) + 3 (image) = 9.
        assert len(result.findings) == 9
        tools = {f.tool for f in result.findings}
        assert tools == {"trivy"}


# ---------------------------------------------------------------------------
# Command shape -- fs/config/image invocations.
# ---------------------------------------------------------------------------


class TestRunTrivyCommandShape:
    @patch("scanners.trivy_runner.subprocess.run")
    def test_fs_command_shape(self, mock_run, workspace_no_dockerfile):
        mock_run.return_value = _completed_process(_load_fixture("trivy_clean.json"))

        run_trivy(workspace_no_dockerfile, timeout=600)

        fs_call = next(call for call in mock_run.call_args_list if call.args[0][1] == "fs")
        cmd = fs_call.args[0]
        assert cmd[0] == "trivy"
        assert "--format" in cmd
        assert "json" in cmd
        assert cmd[-1] == str(workspace_no_dockerfile)

    @patch("scanners.trivy_runner.subprocess.run")
    def test_config_command_shape(self, mock_run, workspace_no_dockerfile):
        mock_run.return_value = _completed_process(_load_fixture("trivy_clean.json"))

        run_trivy(workspace_no_dockerfile, timeout=600)

        config_call = next(call for call in mock_run.call_args_list if call.args[0][1] == "config")
        cmd = config_call.args[0]
        assert cmd[0] == "trivy"
        assert "--format" in cmd
        assert "json" in cmd
        assert cmd[-1] == str(workspace_no_dockerfile)

    @patch("scanners.trivy_runner.subprocess.run")
    def test_scanner_timeout_passed_through_to_every_call(
        self, mock_run, workspace_with_dockerfile
    ):
        mock_run.return_value = _completed_process(_load_fixture("trivy_clean.json"))

        run_trivy(workspace_with_dockerfile, timeout=42)

        assert mock_run.call_count == 3
        for call in mock_run.call_args_list:
            assert call.kwargs["timeout"] == 42


# ---------------------------------------------------------------------------
# Failure paths -- non-fatal to the overall run, but reflected in the result.
# ---------------------------------------------------------------------------


class TestRunTrivyFailurePaths:
    @patch("scanners.trivy_runner.subprocess.run")
    def test_unparseable_output_from_one_mode_is_non_fatal_failed(
        self, mock_run, workspace_no_dockerfile
    ):
        def _side_effect(cmd, **kwargs):
            if cmd[1] == "fs":
                return _completed_process("not valid json{{{")
            return _completed_process(_load_fixture("trivy_clean.json"))

        mock_run.side_effect = _side_effect

        result = run_trivy(workspace_no_dockerfile, timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert result.reason is not None
        assert "fs" in result.reason

    @patch("scanners.trivy_runner.subprocess.run")
    def test_timeout_on_any_mode_is_non_fatal_failed(self, mock_run, workspace_no_dockerfile):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["trivy"], timeout=600)

        result = run_trivy(workspace_no_dockerfile, timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert result.reason is not None
        assert "600" in result.reason

    @patch("scanners.trivy_runner.subprocess.run")
    def test_binary_missing_is_non_fatal_failed(self, mock_run, workspace_no_dockerfile):
        mock_run.side_effect = OSError("trivy: command not found")

        result = run_trivy(workspace_no_dockerfile, timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert result.reason is not None

    @patch("scanners.trivy_runner.subprocess.run")
    def test_no_exception_propagates_out_of_run_trivy(self, mock_run, workspace_with_dockerfile):
        mock_run.side_effect = OSError("boom")
        result = run_trivy(workspace_with_dockerfile, timeout=600)
        assert result is not None
        assert result.status is ScanStatus.FAILED


# ---------------------------------------------------------------------------
# Dockerfile with no parseable FROM line -- image mode also skipped.
# ---------------------------------------------------------------------------


class TestRunTrivyMalformedDockerfile:
    @patch("scanners.trivy_runner.subprocess.run")
    def test_dockerfile_without_a_from_line_skips_image_mode(self, mock_run, tmp_path):
        (tmp_path / "Dockerfile").write_text("# just a comment, no FROM instruction\n")
        mock_run.return_value = _completed_process(_load_fixture("trivy_clean.json"))

        result = run_trivy(tmp_path, timeout=600)

        assert result.status is ScanStatus.PASSED
        assert mock_run.call_count == 2
        invoked_subcommands = {call.args[0][1] for call in mock_run.call_args_list}
        assert invoked_subcommands == {"fs", "config"}


class TestRunTrivyMultiStageDockerfile:
    @patch("scanners.trivy_runner.subprocess.run")
    def test_first_from_line_used_as_the_representative_image(self, mock_run, tmp_path):
        (tmp_path / "Dockerfile").write_text(
            "FROM node:20-slim AS builder\nRUN npm install\nFROM python:3.13-slim\nCOPY --from=builder /app /app\n"
        )
        mock_run.return_value = _completed_process(_load_fixture("trivy_clean.json"))

        run_trivy(tmp_path, timeout=600)

        image_call = next(call for call in mock_run.call_args_list if call.args[0][1] == "image")
        assert image_call.args[0][-1] == "node:20-slim"
