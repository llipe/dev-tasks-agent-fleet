"""
Component tests for `main.invoke()`'s `audit_only` mode pipeline (spec §8.8,
story S-135, task 11.12).

All five scanners are mocked at the `main.run_scanners` boundary — no real
subprocess/network I/O. Drives the full entrypoint: resolve_credentials ->
checkout -> scan -> classify -> audit_report -> determine_outcome, exactly
like a real AgentCore invocation, with Supabase/GitHub/filesystem all
stubbed (mirrors the sibling agent's `tests/component/test_pipeline.py`
heartbeat-wiring pattern).

Scenarios (PRD acceptance criteria, tasks 11.5-11.10):
  - AC-3  clean repo -> succeeded/no_findings, audit_report artifact, no PR
  - AC-4  findings + fail_on_findings=true -> failed/AUDIT_FINDINGS
  - AC-5  findings + fail_on_findings=false -> succeeded/needs_review
  - AC-12b min_severity gates status only, never the artifact's contents
  - AC-24 all scanners failing -> failed/ALL_SCANNERS_FAILED;
          one of five failing -> run continues normally
"""

from __future__ import annotations

import asyncio
import json

from normalize import Finding, Remediation
from scanners import AllScannersFailedError
from scanners.types import ScanResult, ScanStatus
from severity import Severity

ALL_FIVE = ["semgrep", "gitleaks", "trivy", "checkov", "codeql"]


def _collect_async_gen(agen):
    async def _drain():
        return [item async for item in agen]

    return asyncio.run(_drain())


def _scan_result(tool, status=ScanStatus.PASSED, findings=None, reason=None) -> ScanResult:
    return ScanResult(tool=tool, status=status, findings=findings or [], reason=reason)


def _finding(tool, severity, remediation=None, rule_id="R1", file_path=None) -> Finding:
    # Distinct file_path/category per tool by default so dedupe() (grouped by
    # (file_path, cwe_or_category) + line overlap) never merges these
    # deliberately-distinct findings into one MergedFinding -- that cross-tool
    # merge behavior has its own dedicated coverage in tests/unit/test_dedupe.py.
    return Finding(
        tool=tool,
        rule_id=rule_id,
        severity=severity,
        file_path=file_path or f"{tool}.py",
        line_start=1,
        line_end=1,
        message=f"{tool} finding",
        cwe_or_category=f"CWE-{tool}",
        remediation=remediation,
        raw_ref=f"{tool}:0",
    )


def _clean_results() -> list[ScanResult]:
    return [_scan_result(t) for t in ALL_FIVE]


def _mixed_bucket_results(
    severity_overrides: dict[str, Severity] | None = None,
) -> list[ScanResult]:
    """Findings across 3 tools, one per classifier bucket (mechanical/manual/
    unscannable), each with its own severity -- overridable per test."""
    sev = severity_overrides or {}
    mechanical = _finding(
        "semgrep",
        sev.get("semgrep", Severity.HIGH),
        remediation=Remediation(
            kind="semgrep_autofix", patch="x", target_version=None, lockfile_managed=False
        ),
    )
    unscannable = _finding("trivy", sev.get("trivy", Severity.MEDIUM), remediation=None)
    manual = _finding(
        "checkov",
        sev.get("checkov", Severity.LOW),
        remediation=Remediation(
            kind="structural", patch=None, target_version=None, lockfile_managed=False
        ),
    )
    return [
        _scan_result("semgrep", findings=[mechanical]),
        _scan_result("gitleaks"),
        _scan_result("trivy", findings=[unscannable]),
        _scan_result("checkov", findings=[manual]),
        _scan_result("codeql"),
    ]


class _NoopStep:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeRun:
    """RunReporter stand-in capturing succeed/fail/artifact calls."""

    def __init__(self):
        self.succeed_calls: list[dict] = []
        self.fail_calls: list[dict] = []
        self.artifacts: list[dict] = []
        self._terminal = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def step(self, key, title=None):
        return _NoopStep()

    def succeed(self, outcome, result=None, metrics=None):
        self._terminal = True
        self.succeed_calls.append({"outcome": outcome, "metrics": metrics})

    def fail(self, error_code, error_message, outcome=None, traceback_text=None, metrics=None):
        self._terminal = True
        self.fail_calls.append(
            {
                "error_code": error_code,
                "error_message": error_message,
                "outcome": outcome,
                "metrics": metrics,
            }
        )

    def artifact(self, type_, url=None, title=None, storage_path=None, **metadata):
        self.artifacts.append({"type": type_, "title": title, "metadata": metadata})

    def log(self, *a, **k):
        pass


def _drive(monkeypatch, scan_results_or_side_effect, params: dict | None = None):
    """Drive `main.invoke()` through the audit_only pipeline with every
    external boundary stubbed. `scan_results_or_side_effect` is either a
    `list[ScanResult]` (returned as-is) or a callable
    `(workspace, requested, timeout) -> list[ScanResult]` (e.g. one that
    raises `AllScannersFailedError`).
    """
    import main

    monkeypatch.setattr(main, "fetch_supabase_key", lambda: "svc-key")

    class _Tok:
        token = "gh-token"

    monkeypatch.setattr(main, "resolve_github_credentials", lambda org: _Tok())
    monkeypatch.setattr(main, "install_termination_backstop", lambda *a, **k: None)

    fake_run = _FakeRun()
    monkeypatch.setattr(main.RunReporter, "from_env", classmethod(lambda cls, **k: fake_run))
    monkeypatch.setattr(main, "clone_repo", lambda org, name, tok, secrets: "/tmp/ws")

    if callable(scan_results_or_side_effect) and not isinstance(scan_results_or_side_effect, list):
        monkeypatch.setattr(main, "run_scanners", scan_results_or_side_effect)
    else:
        monkeypatch.setattr(
            main, "run_scanners", lambda workspace, requested, timeout: scan_results_or_side_effect
        )

    raw = {
        "run_id": "r-1",
        "repository_org": "org",
        "repository_name": "repo",
        "params": {"mode": "audit_only", **(params or {})},
    }
    results = _collect_async_gen(main.invoke(raw, None))
    return results, fake_run


def _terminal_payload(results) -> dict:
    from heartbeat import read_terminal_payload

    text = read_terminal_payload(results)
    assert text is not None
    return json.loads(text)


# ---------------------------------------------------------------------------
# AC-3 -- clean repo (task 11.5)
# ---------------------------------------------------------------------------


class TestCleanRepo:
    def test_clean_repo_succeeds_no_findings(self, monkeypatch):
        results, fake_run = _drive(monkeypatch, _clean_results())

        payload = _terminal_payload(results)
        assert payload["status"] == "succeeded"
        assert payload["outcome"] == "no_findings"
        assert payload["error_code"] is None
        assert payload["pr_url"] is None
        assert fake_run.succeed_calls == [
            {"outcome": "no_findings", "metrics": fake_run.succeed_calls[0]["metrics"]}
        ]

    def test_clean_repo_writes_audit_report_artifact(self, monkeypatch):
        results, fake_run = _drive(monkeypatch, _clean_results())

        assert len(fake_run.artifacts) == 1
        artifact = fake_run.artifacts[0]
        assert artifact["type"] == "audit_report"
        assert artifact["metadata"]["total_findings"] == 0
        assert artifact["metadata"]["by_bucket"] == {
            "mechanical": [],
            "manual": [],
            "unscannable": [],
        }

    def test_clean_repo_no_metadata_double_nesting(self, monkeypatch):
        """Guard: artifact metadata must be flat (spread, not nested)."""
        _results, fake_run = _drive(monkeypatch, _clean_results())
        assert "metadata" not in fake_run.artifacts[0]["metadata"]

    def test_clean_repo_all_five_scanners_run(self, monkeypatch):
        results, fake_run = _drive(monkeypatch, _clean_results())
        payload = _terminal_payload(results)
        assert set(payload["scanners_run"]) == set(ALL_FIVE)
        assert payload["scanners_skipped"] == []
        assert payload["scanners_failed"] == []


# ---------------------------------------------------------------------------
# AC-4 / AC-5 -- findings, fail_on_findings crossing (tasks 11.6/11.7)
# ---------------------------------------------------------------------------


class TestFindingsFailOnFindings:
    def test_findings_fail_on_true_fails_with_audit_findings(self, monkeypatch):
        results, fake_run = _drive(
            monkeypatch, _mixed_bucket_results(), params={"fail_on_findings": True}
        )

        payload = _terminal_payload(results)
        assert payload["status"] == "failed"
        assert payload["outcome"] == "needs_review"
        assert payload["error_code"] == "AUDIT_FINDINGS"
        assert len(fake_run.fail_calls) == 1
        assert fake_run.fail_calls[0]["error_code"] == "AUDIT_FINDINGS"

    def test_findings_fail_on_true_artifact_buckets_all_three(self, monkeypatch):
        _results, fake_run = _drive(
            monkeypatch, _mixed_bucket_results(), params={"fail_on_findings": True}
        )

        by_bucket = fake_run.artifacts[0]["metadata"]["by_bucket"]
        assert len(by_bucket["mechanical"]) == 1
        assert len(by_bucket["manual"]) == 1
        assert len(by_bucket["unscannable"]) == 1

    def test_findings_fail_on_false_succeeds_needs_review(self, monkeypatch):
        results, fake_run = _drive(
            monkeypatch, _mixed_bucket_results(), params={"fail_on_findings": False}
        )

        payload = _terminal_payload(results)
        assert payload["status"] == "succeeded"
        assert payload["outcome"] == "needs_review"
        assert payload["error_code"] is None
        assert fake_run.succeed_calls[0]["outcome"] == "needs_review"


# ---------------------------------------------------------------------------
# AC-12b -- min_severity gates status only (tasks 11.8/11.9)
# ---------------------------------------------------------------------------


class TestMinSeverityGating:
    def test_high_floor_with_only_low_medium_is_no_findings(self, monkeypatch):
        scan_results = _mixed_bucket_results(
            {"semgrep": Severity.MEDIUM, "trivy": Severity.LOW, "checkov": Severity.LOW}
        )
        results, fake_run = _drive(
            monkeypatch,
            scan_results,
            params={"fail_on_findings": True, "min_severity": "high"},
        )

        payload = _terminal_payload(results)
        assert payload["status"] == "succeeded"
        assert payload["outcome"] == "no_findings"

        # But the artifact still lists every finding, low-severity included.
        artifact_meta = fake_run.artifacts[0]["metadata"]
        assert artifact_meta["total_findings"] == 3

    def test_high_floor_plus_one_high_finding_fails(self, monkeypatch):
        scan_results = _mixed_bucket_results(
            {"semgrep": Severity.HIGH, "trivy": Severity.LOW, "checkov": Severity.LOW}
        )
        results, fake_run = _drive(
            monkeypatch,
            scan_results,
            params={"fail_on_findings": True, "min_severity": "high"},
        )

        payload = _terminal_payload(results)
        assert payload["status"] == "failed"
        assert payload["outcome"] == "needs_review"
        assert payload["error_code"] == "AUDIT_FINDINGS"

        # Still every finding listed, not just the gating one.
        artifact_meta = fake_run.artifacts[0]["metadata"]
        assert artifact_meta["total_findings"] == 3


# ---------------------------------------------------------------------------
# AC-24 -- scanner failure non-fatal unless total (task 11.10)
# ---------------------------------------------------------------------------


class TestScannerFailureHandling:
    def test_all_five_failing_terminates_all_scanners_failed(self, monkeypatch):
        failed_results = [
            _scan_result(t, status=ScanStatus.FAILED, reason=f"{t} crashed") for t in ALL_FIVE
        ]

        def _raise(workspace, requested, timeout):
            raise AllScannersFailedError(failed_results)

        results, fake_run = _drive(monkeypatch, _raise)

        payload = _terminal_payload(results)
        assert payload["status"] == "failed"
        assert payload["outcome"] == "not_applicable"
        assert payload["error_code"] == "ALL_SCANNERS_FAILED"
        assert set(payload["scanners_failed"]) == set(ALL_FIVE)
        # No audit_report artifact when the run never reaches classify.
        assert fake_run.artifacts == []

    def test_one_of_five_failing_continues_normally(self, monkeypatch):
        """CodeQL fails, other four succeed with a clean scan -> run completes."""
        scan_results = _clean_results()
        codeql_index = next(i for i, r in enumerate(scan_results) if r.tool == "codeql")
        scan_results[codeql_index] = _scan_result(
            "codeql", status=ScanStatus.FAILED, reason="unsupported language forced into scope"
        )

        results, fake_run = _drive(monkeypatch, scan_results)

        payload = _terminal_payload(results)
        assert payload["status"] == "succeeded"
        assert payload["outcome"] == "no_findings"
        assert payload["scanners_failed"] == ["codeql"]
        assert "codeql" not in payload["scanners_run"]
        # The run still completes and writes its audit_report artifact.
        assert len(fake_run.artifacts) == 1

    def test_one_of_five_failing_with_findings_from_others_still_reported(self, monkeypatch):
        """Partial results from the 4 working tools are still used (AC-24)."""
        scan_results = _mixed_bucket_results()
        codeql_index = next(i for i, r in enumerate(scan_results) if r.tool == "codeql")
        scan_results[codeql_index] = _scan_result(
            "codeql", status=ScanStatus.FAILED, reason="crashed"
        )

        results, fake_run = _drive(monkeypatch, scan_results, params={"fail_on_findings": True})

        payload = _terminal_payload(results)
        assert payload["status"] == "failed"
        assert payload["outcome"] == "needs_review"
        assert payload["error_code"] == "AUDIT_FINDINGS"
        assert payload["scanners_failed"] == ["codeql"]
        assert fake_run.artifacts[0]["metadata"]["total_findings"] == 3
