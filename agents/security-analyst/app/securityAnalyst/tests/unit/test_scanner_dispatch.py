"""
Tests for `scanners.run_scanners()` (spec §8.5, PRD requirement 18, story
S-135, task 11.1).

Pure dispatch-logic tests: every ``run_<tool>()`` is monkeypatched so no
subprocess/filesystem I/O occurs here (Layer 1, `tests/unit/`). Component-
level coverage (mocked scanners wired through the full `main.invoke()`
pipeline) lives in `tests/component/test_audit_only_pipeline.py` (task
11.12).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import scanners
from normalize import Finding
from scanners import AllScannersFailedError, relativize_path, run_scanners
from scanners.types import ScanResult, ScanStatus
from severity import Severity


def _result(
    tool: str,
    status: ScanStatus,
    reason: str | None = None,
    findings: list[Finding] | None = None,
) -> ScanResult:
    return ScanResult(tool=tool, status=status, findings=findings or [], reason=reason)


def _finding(tool: str, file_path: str) -> Finding:
    return Finding(
        tool=tool,
        rule_id="r1",
        severity=Severity.HIGH,
        file_path=file_path,
        line_start=1,
        line_end=1,
        message="m",
        cwe_or_category="CWE-1",
        remediation=None,
        raw_ref=f"{tool}#0",
    )


def _patch_all(monkeypatch, statuses: dict[str, ScanStatus]) -> None:
    """Monkeypatch `scanners._SCANNER_DISPATCH` entries for the given tools."""
    for tool, status in statuses.items():
        reason = None if status == ScanStatus.PASSED else f"{tool} {status.value}"
        monkeypatch.setitem(
            scanners._SCANNER_DISPATCH,
            tool,
            lambda workspace, timeout, _t=tool, _s=status, _r=reason: _result(_t, _s, _r),
        )


class TestRunScannersDispatch:
    """Basic dispatch: one call per requested tool, in requested order."""

    def test_calls_each_requested_tool_once(self, monkeypatch):
        calls: list[str] = []

        def _make(tool):
            def _run(workspace, timeout):
                calls.append(tool)
                return _result(tool, ScanStatus.PASSED)

            return _run

        for tool in ("semgrep", "gitleaks", "trivy"):
            monkeypatch.setitem(scanners._SCANNER_DISPATCH, tool, _make(tool))

        results = run_scanners(Path("/tmp/ws"), ["semgrep", "gitleaks", "trivy"], 600)

        assert calls == ["semgrep", "gitleaks", "trivy"]
        assert [r.tool for r in results] == ["semgrep", "gitleaks", "trivy"]

    def test_passes_workspace_and_timeout_through(self, monkeypatch):
        seen = {}

        def _run(workspace, timeout):
            seen["workspace"] = workspace
            seen["timeout"] = timeout
            return _result("semgrep", ScanStatus.PASSED)

        monkeypatch.setitem(scanners._SCANNER_DISPATCH, "semgrep", _run)

        run_scanners(Path("/some/ws"), ["semgrep"], 123)

        assert seen["workspace"] == Path("/some/ws")
        assert seen["timeout"] == 123

    def test_single_scanner_subset(self, monkeypatch):
        """Only the requested subset is dispatched, never the full five."""
        called: list[str] = []
        for tool in ("semgrep", "gitleaks", "trivy", "checkov", "codeql"):
            monkeypatch.setitem(
                scanners._SCANNER_DISPATCH,
                tool,
                lambda workspace, timeout, _t=tool: (
                    called.append(_t) or _result(_t, ScanStatus.PASSED)
                ),
            )

        run_scanners(Path("/tmp/ws"), ["checkov"], 600)

        assert called == ["checkov"]


class TestRelativizePath:
    """S-141 real-invocation finding: spec §8.1's `file_path` is repo-relative,
    but real Semgrep/Gitleaks echo the absolute workspace path they were
    invoked with, while Trivy/Checkov/CodeQL report relative paths."""

    def test_absolute_path_under_workspace_becomes_relative(self, tmp_path):
        ws = tmp_path / "security-analyst-memo-cli-abc123"
        ws.mkdir()
        assert relativize_path(str(ws / "src" / "index.ts"), ws) == "src/index.ts"

    def test_absolute_path_under_symlinked_workspace_root_still_matches(self, tmp_path):
        # macOS-style /tmp -> /private/tmp: the tool may report the resolved
        # real path while the pipeline holds the unresolved one (or vice versa).
        real = tmp_path / "real-ws"
        real.mkdir()
        (real / "a.py").write_text("x = 1")
        link = tmp_path / "link-ws"
        link.symlink_to(real)
        assert relativize_path(str(real / "a.py"), link) == "a.py"
        assert relativize_path(str(link / "a.py"), real) == "a.py"

    def test_relative_path_is_returned_posix_normalized(self, tmp_path):
        assert relativize_path("src/index.ts", tmp_path) == "src/index.ts"

    def test_absolute_path_outside_workspace_is_left_untouched(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        other = tmp_path / "elsewhere" / "file.py"
        assert relativize_path(str(other), ws) == str(other)

    def test_empty_path_is_left_untouched(self, tmp_path):
        # CodeQL whole-file-scope results can carry an empty file_path.
        assert relativize_path("", tmp_path) == ""

    def test_workspace_root_itself_relativizes_to_dot(self, tmp_path):
        assert relativize_path(str(tmp_path), tmp_path) == "."


class TestRunScannersRelativizesFindings:
    def test_absolute_workspace_paths_from_a_runner_are_relativized(self, monkeypatch, tmp_path):
        ws = tmp_path / "security-analyst-repo-xyz"
        ws.mkdir()
        absolute = str(ws / "workstream" / "spec.md")

        monkeypatch.setitem(
            scanners._SCANNER_DISPATCH,
            "gitleaks",
            lambda workspace, timeout: _result(
                "gitleaks", ScanStatus.PASSED, findings=[_finding("gitleaks", absolute)]
            ),
        )
        monkeypatch.setitem(
            scanners._SCANNER_DISPATCH,
            "codeql",
            lambda workspace, timeout: _result(
                "codeql", ScanStatus.PASSED, findings=[_finding("codeql", "workstream/spec.md")]
            ),
        )

        results = run_scanners(ws, ["gitleaks", "codeql"], 600)

        by_tool = {r.tool: r for r in results}
        assert by_tool["gitleaks"].findings[0].file_path == "workstream/spec.md"
        assert by_tool["codeql"].findings[0].file_path == "workstream/spec.md"
        # The whole point: the two tools now agree on the dedup key's path.
        assert by_tool["gitleaks"].findings[0].file_path == by_tool["codeql"].findings[0].file_path
        # And the ephemeral workspace prefix never survives into downstream surfaces.
        assert str(ws) not in by_tool["gitleaks"].findings[0].file_path

    def test_other_finding_fields_are_preserved(self, monkeypatch, tmp_path):
        original = _finding("semgrep", str(tmp_path / "app" / "x.py"))
        monkeypatch.setitem(
            scanners._SCANNER_DISPATCH,
            "semgrep",
            lambda workspace, timeout: _result("semgrep", ScanStatus.PASSED, findings=[original]),
        )

        (result,) = run_scanners(tmp_path, ["semgrep"], 600)

        relativized = result.findings[0]
        assert relativized.file_path == "app/x.py"
        assert relativized.rule_id == original.rule_id
        assert relativized.severity == original.severity
        assert relativized.line_start == original.line_start
        assert relativized.message == original.message
        assert relativized.raw_ref == original.raw_ref

    def test_failed_and_skipped_results_pass_through_unchanged(self, monkeypatch, tmp_path):
        failed = _result("trivy", ScanStatus.FAILED, reason="boom")
        skipped = _result("checkov", ScanStatus.SKIPPED, reason="no IaC")
        monkeypatch.setitem(scanners._SCANNER_DISPATCH, "trivy", lambda w, t: failed)
        monkeypatch.setitem(scanners._SCANNER_DISPATCH, "checkov", lambda w, t: skipped)

        results = run_scanners(tmp_path, ["trivy", "checkov"], 600)

        assert results == [failed, skipped]


class TestAllScannersFailedGating:
    """AC-24: total failure raises; partial failure does not (task 11.10)."""

    def test_all_failed_raises(self, monkeypatch):
        _patch_all(
            monkeypatch,
            {
                "semgrep": ScanStatus.FAILED,
                "gitleaks": ScanStatus.FAILED,
                "trivy": ScanStatus.FAILED,
                "checkov": ScanStatus.FAILED,
                "codeql": ScanStatus.FAILED,
            },
        )

        with pytest.raises(AllScannersFailedError) as excinfo:
            run_scanners(
                Path("/tmp/ws"),
                ["semgrep", "gitleaks", "trivy", "checkov", "codeql"],
                600,
            )
        assert len(excinfo.value.results) == 5
        assert all(r.status == ScanStatus.FAILED for r in excinfo.value.results)

    def test_one_of_five_failing_does_not_raise(self, monkeypatch):
        _patch_all(
            monkeypatch,
            {
                "semgrep": ScanStatus.PASSED,
                "gitleaks": ScanStatus.PASSED,
                "trivy": ScanStatus.PASSED,
                "checkov": ScanStatus.PASSED,
                "codeql": ScanStatus.FAILED,
            },
        )

        results = run_scanners(
            Path("/tmp/ws"), ["semgrep", "gitleaks", "trivy", "checkov", "codeql"], 600
        )

        assert len(results) == 5
        failed = [r for r in results if r.status == ScanStatus.FAILED]
        assert [r.tool for r in failed] == ["codeql"]

    def test_all_skipped_is_not_all_failed(self, monkeypatch):
        """SKIPPED is not FAILED -- all-skipped must not raise (req 17 vs 18)."""
        _patch_all(
            monkeypatch,
            {
                "semgrep": ScanStatus.SKIPPED,
                "gitleaks": ScanStatus.SKIPPED,
            },
        )

        results = run_scanners(Path("/tmp/ws"), ["semgrep", "gitleaks"], 600)
        assert len(results) == 2
        assert all(r.status == ScanStatus.SKIPPED for r in results)

    def test_mixed_failed_and_skipped_is_not_all_failed(self, monkeypatch):
        """Only an all-FAILED set raises -- SKIPPED entries do not count toward it."""
        _patch_all(
            monkeypatch,
            {
                "semgrep": ScanStatus.FAILED,
                "gitleaks": ScanStatus.SKIPPED,
            },
        )

        results = run_scanners(Path("/tmp/ws"), ["semgrep", "gitleaks"], 600)
        assert len(results) == 2

    def test_single_scanner_failing_raises(self, monkeypatch):
        """A single-tool request that fails is, by definition, 100% failed."""
        _patch_all(monkeypatch, {"semgrep": ScanStatus.FAILED})

        with pytest.raises(AllScannersFailedError):
            run_scanners(Path("/tmp/ws"), ["semgrep"], 600)

    def test_error_message_includes_each_tool_reason(self, monkeypatch):
        _patch_all(
            monkeypatch,
            {"semgrep": ScanStatus.FAILED, "gitleaks": ScanStatus.FAILED},
        )

        with pytest.raises(AllScannersFailedError) as excinfo:
            run_scanners(Path("/tmp/ws"), ["semgrep", "gitleaks"], 600)

        message = str(excinfo.value)
        assert "semgrep" in message
        assert "gitleaks" in message
