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
from scanners import AllScannersFailedError, run_scanners
from scanners.types import ScanResult, ScanStatus


def _result(tool: str, status: ScanStatus, reason: str | None = None) -> ScanResult:
    return ScanResult(tool=tool, status=status, findings=[], reason=reason)


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
