"""
Component tests for ``run_codeql()`` (spec S4.3/S8.5, PRD requirements
14/17/18/19/51, story S-132 AC bullets, task 8.11) with ``subprocess.run``
mocked -- the actual ``codeql`` binary is never invoked.

Covers:
  - The skip path: a repository matching neither JS/TS nor Python triggers
    `ScanStatus.SKIPPED` with no subprocess call made at all (requirement
    17/51, test plan SC-42).
  - The two-phase call per language (`database create` -> `database
    analyze`), both bounded independently by `timeout`.
  - Both-languages dispatch: CodeQL runs twice, findings merged, no
    duplicate double-count (test plan SC-41).
  - Non-zero exit from either phase is treated as failure (module docstring
    Deviation 3, unlike the other four scanners' returncode-agnostic
    pattern).
  - Crash/timeout/unparseable-SARIF in one language is non-fatal to the
    overall run but marks the aggregate `ScanResult` `FAILED` (PRD
    requirement 18, test plan SC-34) -- including the one-language-succeeds-
    one-fails case in the both-languages dispatch (module docstring
    Deviation 4).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scanners.codeql_runner import run_codeql
from scanners.types import ScanStatus

_FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text()


def _completed_process(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["codeql"], returncode=returncode, stdout=stdout, stderr=stderr
    )


@pytest.fixture
def workspace_js_ts(tmp_path: Path) -> Path:
    (tmp_path / "index.ts").write_text("export {};")
    return tmp_path


@pytest.fixture
def workspace_python(tmp_path: Path) -> Path:
    (tmp_path / "main.py").write_text("print('hi')")
    return tmp_path


@pytest.fixture
def workspace_both(tmp_path: Path) -> Path:
    (tmp_path / "index.ts").write_text("export {};")
    (tmp_path / "main.py").write_text("print('hi')")
    return tmp_path


@pytest.fixture
def workspace_neither(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# hello")
    return tmp_path


def _is_create_call(call) -> bool:
    return call.args[0][1:3] == ["database", "create"]


def _is_analyze_call(call) -> bool:
    return call.args[0][1:3] == ["database", "analyze"]


# ---------------------------------------------------------------------------
# Skip path -- neither language present.
# ---------------------------------------------------------------------------


class TestRunCodeqlSkipPath:
    @patch("scanners.codeql_runner.subprocess.run")
    def test_no_subprocess_call_at_all_when_neither_language_detected(
        self, mock_run, workspace_neither
    ):
        result = run_codeql(workspace_neither, timeout=600)

        assert result.status is ScanStatus.SKIPPED
        assert result.tool == "codeql"
        assert result.findings == []
        assert result.reason is not None
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Single-language dispatch -- two-phase call shape.
# ---------------------------------------------------------------------------


class TestRunCodeqlSingleLanguageDispatch:
    @patch("scanners.codeql_runner.subprocess.run")
    def test_js_ts_only_runs_exactly_two_subprocess_calls(self, mock_run, workspace_js_ts):
        mock_run.return_value = _completed_process(_load_fixture("codeql_clean.json"))

        result = run_codeql(workspace_js_ts, timeout=600)

        assert result.status is ScanStatus.PASSED
        assert mock_run.call_count == 2
        assert _is_create_call(mock_run.call_args_list[0])
        assert _is_analyze_call(mock_run.call_args_list[1])

    @patch("scanners.codeql_runner.subprocess.run")
    def test_create_command_shape(self, mock_run, workspace_js_ts):
        mock_run.return_value = _completed_process(_load_fixture("codeql_clean.json"))

        run_codeql(workspace_js_ts, timeout=600)

        create_cmd = mock_run.call_args_list[0].args[0]
        assert create_cmd[0] == "codeql"
        assert "--language=javascript" in create_cmd
        assert f"--source-root={workspace_js_ts}" in create_cmd
        # S-141 real-repo finding: without this flag, `database create`
        # defaults to running the language's autobuild script (JS/TS: npm
        # install + build), which fails against a real repo with no npm
        # registry access from the sandboxed runtime -- neither language
        # this module supports needs a build step to extract from.
        assert "--build-mode=none" in create_cmd

    @patch("scanners.codeql_runner.subprocess.run")
    def test_analyze_command_shape_references_the_js_ts_query_pack(self, mock_run, workspace_js_ts):
        mock_run.return_value = _completed_process(_load_fixture("codeql_clean.json"))

        run_codeql(workspace_js_ts, timeout=600)

        analyze_cmd = mock_run.call_args_list[1].args[0]
        assert "codeql/javascript-queries" in analyze_cmd
        assert "--format=sarif-latest" in analyze_cmd
        assert "--output=/dev/stdout" in analyze_cmd

    @patch("scanners.codeql_runner.subprocess.run")
    def test_python_only_uses_the_python_query_pack(self, mock_run, workspace_python):
        mock_run.return_value = _completed_process(_load_fixture("codeql_clean.json"))

        run_codeql(workspace_python, timeout=600)

        create_cmd = mock_run.call_args_list[0].args[0]
        analyze_cmd = mock_run.call_args_list[1].args[0]
        assert "--language=python" in create_cmd
        assert "codeql/python-queries" in analyze_cmd

    @patch("scanners.codeql_runner.subprocess.run")
    def test_timeout_passed_through_independently_to_both_phases(self, mock_run, workspace_js_ts):
        mock_run.return_value = _completed_process(_load_fixture("codeql_clean.json"))

        run_codeql(workspace_js_ts, timeout=42)

        assert mock_run.call_count == 2
        for call in mock_run.call_args_list:
            assert call.kwargs["timeout"] == 42

    @patch("scanners.codeql_runner.subprocess.run")
    def test_findings_from_analyze_stdout_are_normalized(self, mock_run, workspace_js_ts):
        def _side_effect(cmd, **kwargs):
            if cmd[1:3] == ["database", "create"]:
                return _completed_process()
            return _completed_process(_load_fixture("codeql_js_ts.json"))

        mock_run.side_effect = _side_effect

        result = run_codeql(workspace_js_ts, timeout=600)

        assert result.status is ScanStatus.PASSED
        assert len(result.findings) == 2
        assert all(f.tool == "codeql" for f in result.findings)


# ---------------------------------------------------------------------------
# Both-languages dispatch -- runs twice, findings merged (test plan SC-41).
# ---------------------------------------------------------------------------


class TestRunCodeqlBothLanguagesDispatch:
    @patch("scanners.codeql_runner.subprocess.run")
    def test_both_languages_run_codeql_twice(self, mock_run, workspace_both):
        mock_run.return_value = _completed_process(_load_fixture("codeql_clean.json"))

        result = run_codeql(workspace_both, timeout=600)

        assert result.status is ScanStatus.PASSED
        # 2 languages x 2 phases (create, analyze) = 4 subprocess calls.
        assert mock_run.call_count == 4
        create_calls = [c for c in mock_run.call_args_list if _is_create_call(c)]
        assert len(create_calls) == 2
        languages_created = {
            arg for call in create_calls for arg in call.args[0] if arg.startswith("--language=")
        }
        assert languages_created == {"--language=javascript", "--language=python"}

    @patch("scanners.codeql_runner.subprocess.run")
    def test_findings_from_both_languages_are_merged_no_double_count(
        self, mock_run, workspace_both
    ):
        fixtures_by_language = {
            "javascript-typescript": _load_fixture("codeql_js_ts.json"),
            "python": _load_fixture("codeql_python.json"),
        }

        def _side_effect(cmd, **kwargs):
            if cmd[1:3] == ["database", "create"]:
                return _completed_process()
            # The analyze command references the language's query pack --
            # use that to decide which fixture to return.
            for language, pack in {
                "javascript-typescript": "codeql/javascript-queries",
                "python": "codeql/python-queries",
            }.items():
                if pack in cmd:
                    return _completed_process(fixtures_by_language[language])
            raise AssertionError(f"unexpected analyze command: {cmd}")

        mock_run.side_effect = _side_effect

        result = run_codeql(workspace_both, timeout=600)

        assert result.status is ScanStatus.PASSED
        # 2 JS/TS findings + 2 Python findings = 4, no duplication.
        assert len(result.findings) == 4
        raw_refs = {f.raw_ref for f in result.findings}
        assert raw_refs == {
            "codeql:javascript-typescript#0",
            "codeql:javascript-typescript#1",
            "codeql:python#0",
            "codeql:python#1",
        }


# ---------------------------------------------------------------------------
# Failure paths -- non-fatal to the overall run, but reflected in the result.
# ---------------------------------------------------------------------------


class TestRunCodeqlFailurePaths:
    @patch("scanners.codeql_runner.subprocess.run")
    def test_non_zero_exit_from_database_create_is_failure(self, mock_run, workspace_js_ts):
        # Deviation 3 -- unlike the other 4 scanners, a non-zero exit code IS
        # treated as failure here (CodeQL's own conventional success/failure
        # signal, not gitleaks' inverted one).
        def _side_effect(cmd, **kwargs):
            if cmd[1:3] == ["database", "create"]:
                return _completed_process(returncode=1, stderr="No source code was seen.")
            raise AssertionError("analyze should never be called after a failed create")

        mock_run.side_effect = _side_effect

        result = run_codeql(workspace_js_ts, timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert "database create" in result.reason

    @patch("scanners.codeql_runner.subprocess.run")
    def test_non_zero_exit_from_database_analyze_is_failure(self, mock_run, workspace_js_ts):
        def _side_effect(cmd, **kwargs):
            if cmd[1:3] == ["database", "create"]:
                return _completed_process()
            return _completed_process(returncode=1, stderr="analysis failed")

        mock_run.side_effect = _side_effect

        result = run_codeql(workspace_js_ts, timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert "database analyze" in result.reason

    @patch("scanners.codeql_runner.subprocess.run")
    def test_timeout_on_create_is_non_fatal_failed(self, mock_run, workspace_js_ts):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["codeql"], timeout=600)

        result = run_codeql(workspace_js_ts, timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert "600" in result.reason
        assert "database create" in result.reason

    @patch("scanners.codeql_runner.subprocess.run")
    def test_timeout_on_analyze_is_non_fatal_failed(self, mock_run, workspace_js_ts):
        def _side_effect(cmd, **kwargs):
            if cmd[1:3] == ["database", "create"]:
                return _completed_process()
            raise subprocess.TimeoutExpired(cmd=["codeql"], timeout=600)

        mock_run.side_effect = _side_effect

        result = run_codeql(workspace_js_ts, timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert "database analyze" in result.reason

    @patch("scanners.codeql_runner.subprocess.run")
    def test_binary_missing_is_non_fatal_failed(self, mock_run, workspace_js_ts):
        mock_run.side_effect = OSError("codeql: command not found")

        result = run_codeql(workspace_js_ts, timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert result.reason is not None

    @patch("scanners.codeql_runner.subprocess.run")
    def test_analyze_failing_to_start_is_non_fatal_failed(self, mock_run, workspace_js_ts):
        def _side_effect(cmd, **kwargs):
            if cmd[1:3] == ["database", "create"]:
                return _completed_process()
            raise OSError("codeql: command not found")

        mock_run.side_effect = _side_effect

        result = run_codeql(workspace_js_ts, timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert "database analyze" in result.reason

    @patch("scanners.codeql_runner.subprocess.run")
    def test_unparseable_sarif_is_non_fatal_failed(self, mock_run, workspace_js_ts):
        def _side_effect(cmd, **kwargs):
            if cmd[1:3] == ["database", "create"]:
                return _completed_process()
            return _completed_process("not valid json{{{")

        mock_run.side_effect = _side_effect

        result = run_codeql(workspace_js_ts, timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert result.reason is not None

    @patch("scanners.codeql_runner.subprocess.run")
    def test_no_exception_propagates_out_of_run_codeql(self, mock_run, workspace_js_ts):
        mock_run.side_effect = OSError("boom")
        result = run_codeql(workspace_js_ts, timeout=600)
        assert result is not None
        assert result.status is ScanStatus.FAILED

    @patch("scanners.codeql_runner.subprocess.run")
    def test_one_language_fails_the_other_succeeds_is_all_or_nothing_failed(
        self, mock_run, workspace_both
    ):
        # Module docstring Deviation 4 -- mirrors trivy_runner.py's identical
        # all-or-nothing aggregation: the successfully-scanned language's
        # findings are not returned alongside a FAILED status.
        def _side_effect(cmd, **kwargs):
            if cmd[1:3] == ["database", "create"]:
                if "--language=python" in cmd:
                    return _completed_process(returncode=1, stderr="python extraction crashed")
                return _completed_process()
            return _completed_process(_load_fixture("codeql_js_ts.json"))

        mock_run.side_effect = _side_effect

        result = run_codeql(workspace_both, timeout=600)

        assert result.status is ScanStatus.FAILED
        assert result.findings == []
        assert "python" in result.reason
