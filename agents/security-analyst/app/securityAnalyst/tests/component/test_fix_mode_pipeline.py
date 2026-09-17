"""
Component tests for `main.invoke()`'s `fix` mode pipeline (spec §8.8, PRD
§8.1 / D23, story S-140, task 16.13).

Drives the full entrypoint exactly like a real AgentCore invocation:
resolve_credentials -> checkout -> scan -> classify -> fix -> rescan ->
open_pr -> determine_outcome, with every external boundary mocked --
`main.run_scanners`, `main.apply_semgrep_autofix`, `main.apply_trivy_bump`,
`main.run_fix_loop_for_finding`, `main.open_pr_if_needed`, Supabase/GitHub/
filesystem (mirrors `test_audit_only_pipeline.py`'s pattern, S-135). No real
subprocess/network/LLM call is ever made.

Scenarios (PRD acceptance criteria, story S-140's task list):
  - AC13  happy path, zero LLM: exactly one PR, succeeded/fixed|partial,
          metrics.llm_used=false
  - AC14  re-scan gate blocks an unverified fix even after the LLM escape
          hatch exhausts its budget -> failed/RESCAN_NOT_CLEAN, no PR,
          despite a local working-tree change existing
  - AC15  re-scan gate blocks a regression-introducing fix the same way
  - AC21  no mechanical findings at all -> no_findings/needs_review, no PR
  - AC22  idempotency: an existing open PR short-circuits to
          succeeded/not_applicable
  - AC29  all 7 run_steps present, in order, each terminal
  - requirement 47: runs.metrics carries fix_attempts_deterministic/_llm,
    finding counts, scanners_run/skipped/failed
  - heartbeat: a deliberately slow scan fixture proves the stream stays
    alive (heartbeat chunks observed) under `run_with_heartbeat` wrapping
  - multi-tool: mechanical findings from Semgrep AND Trivy simultaneously
"""

from __future__ import annotations

import asyncio
import json

from dedupe import MergedFinding
from fingerprint import fingerprint
from fix_agent import FixAttemptResult
from fixers.types import FixOutcome
from normalize import Finding, Remediation
from pull_request import PullRequestResult
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


def _mechanical_semgrep(severity=Severity.HIGH, rule_id="SG1", file_path="a/app.py") -> Finding:
    return _finding(
        "semgrep",
        severity,
        rule_id=rule_id,
        file_path=file_path,
        remediation=Remediation(
            kind="semgrep_autofix", patch="x", target_version=None, lockfile_managed=False
        ),
    )


def _mechanical_trivy(
    severity=Severity.HIGH, rule_id="CVE-1", file_path="requirements.txt"
) -> Finding:
    # A minor-version bump (1.0.0 -> 1.2.0), deliberately NOT a major bump --
    # classifier.py's major-version guard (req 27) would otherwise reclassify
    # this MANUAL, since a same-major bump is the only way a `version_bump`
    # remediation reaches MECHANICAL.
    return _finding(
        "trivy",
        severity,
        rule_id=rule_id,
        file_path=file_path,
        remediation=Remediation(
            kind="version_bump",
            patch=None,
            target_version="1.2.0",
            lockfile_managed=False,
            current_version="1.0.0",
            package_name="somepkg",
        ),
    )


def _manual_finding(severity=Severity.MEDIUM) -> Finding:
    return _finding(
        "checkov",
        severity,
        remediation=Remediation(
            kind="structural", patch=None, target_version=None, lockfile_managed=False
        ),
    )


def _unscannable_finding(severity=Severity.LOW) -> Finding:
    return _finding("gitleaks", severity, remediation=None)


def _clean_results() -> list[ScanResult]:
    return [_scan_result(t) for t in ALL_FIVE]


class _NoopStep:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeRun:
    """RunReporter stand-in capturing succeed/fail/artifact/step calls."""

    def __init__(self):
        self.succeed_calls: list[dict] = []
        self.fail_calls: list[dict] = []
        self.artifacts: list[dict] = []
        self.step_calls: list[str] = []
        self._terminal = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def step(self, key, title=None):
        self.step_calls.append(key)
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
        self.artifacts.append({"type": type_, "url": url, "title": title, "metadata": metadata})

    def log(self, *a, **k):
        pass


def _drive(
    monkeypatch,
    scan_results_or_side_effect,
    *,
    params: dict | None = None,
    semgrep_outcome: FixOutcome | None = None,
    trivy_outcome: FixOutcome | None = None,
    llm_side_effect=None,
    rescan_results_or_side_effect=None,
    pr_result: PullRequestResult | None = None,
    pr_side_effect=None,
):
    """Drive `main.invoke()` through the fix-mode pipeline with every
    external boundary stubbed.

    `scan_results_or_side_effect` drives the FIRST scan call; if
    `rescan_results_or_side_effect` is given it drives the SECOND (re-scan)
    call, otherwise the initial scan's results are reused for the re-scan
    (a stable, already-clean re-scan is the common case for fixture
    brevity). Each may be a `list[ScanResult]` or a callable
    `(workspace, requested, timeout) -> list[ScanResult]`.
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

    calls = {"n": 0}

    def _scanners_dispatch(workspace, requested, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            src = scan_results_or_side_effect
        else:
            src = rescan_results_or_side_effect or scan_results_or_side_effect
        if callable(src) and not isinstance(src, list):
            return src(workspace, requested, timeout)
        return src

    monkeypatch.setattr(main, "run_scanners", _scanners_dispatch)

    monkeypatch.setattr(
        main,
        "apply_semgrep_autofix",
        lambda workspace, findings: (
            semgrep_outcome
            or FixOutcome(applied_fingerprints=frozenset(), unresolved=(), output="")
        ),
    )
    monkeypatch.setattr(
        main,
        "apply_trivy_bump",
        lambda workspace, findings: (
            trivy_outcome or FixOutcome(applied_fingerprints=frozenset(), unresolved=(), output="")
        ),
    )

    if llm_side_effect is not None:
        monkeypatch.setattr(main, "run_fix_loop_for_finding", llm_side_effect)
    else:

        def _no_llm_call(*a, **k):
            raise AssertionError("run_fix_loop_for_finding must not be called (AC13)")

        monkeypatch.setattr(main, "run_fix_loop_for_finding", _no_llm_call)

    if pr_side_effect is not None:
        monkeypatch.setattr(main, "open_pr_if_needed", pr_side_effect)
    else:
        default_pr = pr_result or PullRequestResult(
            url="https://github.com/org/repo/pull/1",
            created=True,
            existed=False,
            branch="security/fix-20260101-000000",
        )
        monkeypatch.setattr(main, "open_pr_if_needed", lambda *a, **k: default_pr)

    raw = {
        "run_id": "r-1",
        "repository_org": "org",
        "repository_name": "repo",
        "params": {"mode": "fix", **(params or {})},
    }
    results = _collect_async_gen(main.invoke(raw, None))
    return results, fake_run


def _terminal_payload(results) -> dict:
    from heartbeat import read_terminal_payload

    text = read_terminal_payload(results)
    assert text is not None
    return json.loads(text)


# ---------------------------------------------------------------------------
# AC13 -- happy path, zero LLM
# ---------------------------------------------------------------------------


class TestHappyPathZeroLLM:
    def test_single_mechanical_finding_opens_exactly_one_pr(self, monkeypatch):
        mech = _mechanical_semgrep()
        scan_results = [_scan_result("semgrep", findings=[mech])] + [
            _scan_result(t) for t in ALL_FIVE if t != "semgrep"
        ]
        semgrep_fp = fingerprint(mech)
        semgrep_outcome = FixOutcome(applied_fingerprints=frozenset({semgrep_fp}), unresolved=())

        results, fake_run = _drive(
            monkeypatch,
            scan_results,
            semgrep_outcome=semgrep_outcome,
            rescan_results_or_side_effect=_clean_results(),
        )

        payload = _terminal_payload(results)
        assert payload["status"] == "succeeded"
        assert payload["outcome"] == "fixed"
        assert payload["pr_url"] == "https://github.com/org/repo/pull/1"
        assert payload["llm_used"] is False
        assert payload["fix_attempts_llm"] == 0
        assert len(fake_run.succeed_calls) == 1
        assert fake_run.succeed_calls[0]["outcome"] == "fixed"
        pr_artifacts = [a for a in fake_run.artifacts if a["type"] == "pull_request"]
        assert len(pr_artifacts) == 1
        assert pr_artifacts[0]["url"] == "https://github.com/org/repo/pull/1"
        # Spec §6: fix-mode audit_report with before/after counts, recorded
        # before open_pr so it exists even if PR creation fails.
        reports = [a for a in fake_run.artifacts if a["type"] == "audit_report"]
        assert len(reports) == 1
        assert reports[0]["metadata"]["findings_before"]["mechanical"] == 1
        assert reports[0]["metadata"]["findings_after"]["mechanical"] == 0
        assert [a["type"] for a in fake_run.artifacts].index("audit_report") < [
            a["type"] for a in fake_run.artifacts
        ].index("pull_request")

    def test_multi_tool_simultaneous_findings_semgrep_and_trivy(self, monkeypatch):
        """Edge-case matrix: mechanical findings from Semgrep AND Trivy in the
        same run -- both deterministic fixers invoked, both cleared."""
        sg = _mechanical_semgrep(file_path="a/app.py")
        tv = _mechanical_trivy(file_path="requirements.txt")
        scan_results = [
            _scan_result("semgrep", findings=[sg]),
            _scan_result("gitleaks"),
            _scan_result("trivy", findings=[tv]),
            _scan_result("checkov"),
            _scan_result("codeql"),
        ]
        semgrep_outcome = FixOutcome(
            applied_fingerprints=frozenset({fingerprint(sg)}), unresolved=()
        )
        trivy_outcome = FixOutcome(applied_fingerprints=frozenset({fingerprint(tv)}), unresolved=())

        results, fake_run = _drive(
            monkeypatch,
            scan_results,
            semgrep_outcome=semgrep_outcome,
            trivy_outcome=trivy_outcome,
            rescan_results_or_side_effect=_clean_results(),
        )

        payload = _terminal_payload(results)
        assert payload["status"] == "succeeded"
        assert payload["outcome"] == "fixed"
        assert payload["fix_attempts_deterministic"] == 2
        assert payload["findings_fixed"] == 2
        assert payload["llm_used"] is False

    def test_partial_when_manual_findings_remain(self, monkeypatch):
        mech = _mechanical_semgrep()
        manual = _manual_finding()
        scan_results = [
            _scan_result("semgrep", findings=[mech]),
            _scan_result("gitleaks"),
            _scan_result("trivy"),
            _scan_result("checkov", findings=[manual]),
            _scan_result("codeql"),
        ]
        semgrep_outcome = FixOutcome(
            applied_fingerprints=frozenset({fingerprint(mech)}), unresolved=()
        )
        # Re-scan still reports the (never-touched, correctly-so) manual finding.
        rescan_results = [
            _scan_result("semgrep"),
            _scan_result("gitleaks"),
            _scan_result("trivy"),
            _scan_result("checkov", findings=[manual]),
            _scan_result("codeql"),
        ]

        results, fake_run = _drive(
            monkeypatch,
            scan_results,
            semgrep_outcome=semgrep_outcome,
            rescan_results_or_side_effect=rescan_results,
        )

        payload = _terminal_payload(results)
        assert payload["status"] == "succeeded"
        assert payload["outcome"] == "partial"
        assert payload["pr_url"] is not None


# ---------------------------------------------------------------------------
# AC14 -- re-scan gate blocks an unverified fix, even after LLM budget
# exhausted -- full end-to-end, no PR despite a local working-tree change
# ---------------------------------------------------------------------------


class TestRescanGateBlocksUnverifiedFix:
    def test_still_present_after_llm_exhausted_blocks_pr(self, monkeypatch):
        mech = _mechanical_semgrep()
        scan_results = [_scan_result("semgrep", findings=[mech])] + [
            _scan_result(t) for t in ALL_FIVE if t != "semgrep"
        ]
        # Deterministic fixer could not resolve it -> handed to the LLM.
        semgrep_outcome = FixOutcome(
            applied_fingerprints=frozenset(),
            unresolved=(MergedFinding(finding=mech, reported_by=("semgrep",)),),
        )

        def _llm_exhausts_budget(workspace, finding, max_attempts):
            return FixAttemptResult(resolved=False, attempts=max_attempts, llm_used=True)

        # Re-scan still reports the targeted finding -- the fix never
        # actually cleared it, despite the LLM having made local edits
        # (mandate-confined) to the workspace.
        rescan_results = [_scan_result("semgrep", findings=[mech])] + [
            _scan_result(t) for t in ALL_FIVE if t != "semgrep"
        ]

        def _pr_must_not_be_called(*a, **k):
            raise AssertionError("open_pr_if_needed must not be called when the gate is not clean")

        results, fake_run = _drive(
            monkeypatch,
            scan_results,
            semgrep_outcome=semgrep_outcome,
            llm_side_effect=_llm_exhausts_budget,
            rescan_results_or_side_effect=rescan_results,
            pr_side_effect=_pr_must_not_be_called,
        )

        payload = _terminal_payload(results)
        assert payload["status"] == "failed"
        assert payload["outcome"] == "needs_review"
        assert payload["error_code"] == "RESCAN_NOT_CLEAN"
        assert payload["pr_url"] is None
        assert payload["llm_used"] is True
        assert len(fake_run.fail_calls) == 1
        assert fake_run.fail_calls[0]["error_code"] == "RESCAN_NOT_CLEAN"
        # No PR artifact was ever recorded.
        assert not any(a["type"] == "pull_request" for a in fake_run.artifacts)
        # "open_pr" step is only reached on a clean gate (spec §8.8 diagram).
        assert "open_pr" not in fake_run.step_calls
        # Requirement 36 (S-141): the after-scan's full result MUST be
        # recorded as an artifact so the operator can see what remained.
        reports = [a for a in fake_run.artifacts if a["type"] == "audit_report"]
        assert len(reports) == 1
        assert reports[0]["metadata"]["total_findings"] == 1
        assert reports[0]["metadata"]["findings_before"] == {
            "mechanical": 1,
            "manual": 0,
            "unscannable": 0,
        }
        assert reports[0]["metadata"]["findings_after"] == {
            "mechanical": 1,
            "manual": 0,
            "unscannable": 0,
        }


# ---------------------------------------------------------------------------
# AC15 -- re-scan gate blocks a regression-introducing fix, unless
# allow-listed
# ---------------------------------------------------------------------------


class TestRescanGateBlocksRegression:
    def test_unexplained_new_finding_blocks_pr(self, monkeypatch):
        mech = _mechanical_semgrep()
        scan_results = [_scan_result("semgrep", findings=[mech])] + [
            _scan_result(t) for t in ALL_FIVE if t != "semgrep"
        ]
        semgrep_outcome = FixOutcome(
            applied_fingerprints=frozenset({fingerprint(mech)}), unresolved=()
        )

        # The fix cleared the target, but a brand-new, non-allow-listed
        # finding appeared in the same file -- a regression.
        new_finding = _finding(
            "semgrep",
            Severity.HIGH,
            rule_id="SG-NEW",
            file_path="a/app.py",
            remediation=Remediation(
                kind="semgrep_autofix", patch="y", target_version=None, lockfile_managed=False
            ),
        )
        rescan_results = [_scan_result("semgrep", findings=[new_finding])] + [
            _scan_result(t) for t in ALL_FIVE if t != "semgrep"
        ]

        def _pr_must_not_be_called(*a, **k):
            raise AssertionError("open_pr_if_needed must not be called when the gate is not clean")

        results, fake_run = _drive(
            monkeypatch,
            scan_results,
            semgrep_outcome=semgrep_outcome,
            rescan_results_or_side_effect=rescan_results,
            pr_side_effect=_pr_must_not_be_called,
        )

        payload = _terminal_payload(results)
        assert payload["status"] == "failed"
        assert payload["outcome"] == "needs_review"
        assert payload["error_code"] == "RESCAN_NOT_CLEAN"
        assert payload["pr_url"] is None

    def test_allow_listed_new_finding_does_not_block_pr(self, monkeypatch):
        mech = _mechanical_trivy(file_path="requirements.txt")
        scan_results = [_scan_result("trivy", findings=[mech])] + [
            _scan_result(t) for t in ALL_FIVE if t != "trivy"
        ]
        trivy_outcome = FixOutcome(
            applied_fingerprints=frozenset({fingerprint(mech)}), unresolved=()
        )

        # A Trivy advisory briefly flags an intermediate patch version --
        # the enumerated allow-list exception (rescan.py's own table).
        allowed_new = _finding(
            "trivy",
            Severity.LOW,
            rule_id="intermediate-patch-advisory",
            file_path="requirements.txt",
            remediation=Remediation(
                kind="version_bump",
                patch=None,
                target_version="2.0.1",
                lockfile_managed=False,
                current_version="2.0.0",
                package_name="somepkg",
            ),
        )
        rescan_results = [_scan_result("trivy", findings=[allowed_new])] + [
            _scan_result(t) for t in ALL_FIVE if t != "trivy"
        ]

        results, fake_run = _drive(
            monkeypatch,
            scan_results,
            trivy_outcome=trivy_outcome,
            rescan_results_or_side_effect=rescan_results,
        )

        payload = _terminal_payload(results)
        assert payload["status"] == "succeeded"
        assert payload["pr_url"] is not None


# ---------------------------------------------------------------------------
# AC16 -- LLM escape hatch succeeds where the deterministic fixer could not
# ---------------------------------------------------------------------------


class TestLlmEscapeHatchSuccess:
    def test_llm_resolves_finding_deterministic_fixer_could_not(self, monkeypatch):
        mech = _mechanical_semgrep()
        merged_mech = MergedFinding(finding=mech, reported_by=("semgrep",))
        scan_results = [_scan_result("semgrep", findings=[mech])] + [
            _scan_result(t) for t in ALL_FIVE if t != "semgrep"
        ]
        semgrep_outcome = FixOutcome(applied_fingerprints=frozenset(), unresolved=(merged_mech,))

        llm_calls = []

        def _llm_resolves(workspace, finding, max_attempts):
            llm_calls.append(finding)
            return FixAttemptResult(resolved=True, attempts=1, llm_used=True)

        # The LLM's edit cleared the finding -- clean re-scan.
        results, fake_run = _drive(
            monkeypatch,
            scan_results,
            semgrep_outcome=semgrep_outcome,
            llm_side_effect=_llm_resolves,
            rescan_results_or_side_effect=_clean_results(),
        )

        payload = _terminal_payload(results)
        assert payload["status"] == "succeeded"
        assert payload["outcome"] == "fixed"
        assert payload["llm_used"] is True
        assert payload["fix_attempts_llm"] == 1
        # The LLM was invoked with only the single targeted finding's record.
        assert len(llm_calls) == 1
        assert llm_calls[0] is merged_mech


# ---------------------------------------------------------------------------
# AC21 -- no mechanical findings at all
# ---------------------------------------------------------------------------


class TestNoMechanicalFindings:
    def test_zero_findings_everywhere_is_no_findings_no_pr(self, monkeypatch):
        def _pr_must_not_be_called(*a, **k):
            raise AssertionError("open_pr_if_needed must not be called (AC21)")

        results, fake_run = _drive(
            monkeypatch, _clean_results(), pr_side_effect=_pr_must_not_be_called
        )

        payload = _terminal_payload(results)
        assert payload["status"] == "succeeded"
        assert payload["outcome"] == "no_findings"
        assert payload["pr_url"] is None
        assert "rescan" not in fake_run.step_calls
        assert "open_pr" not in fake_run.step_calls
        assert not any(a["type"] == "pull_request" for a in fake_run.artifacts)
        reports = [a for a in fake_run.artifacts if a["type"] == "audit_report"]
        assert len(reports) == 1
        assert reports[0]["metadata"]["total_findings"] == 0

    def test_only_manual_and_unscannable_findings_is_needs_review_no_pr(self, monkeypatch):
        manual = _manual_finding()
        unscannable = _unscannable_finding()
        scan_results = [
            _scan_result("semgrep"),
            _scan_result("gitleaks", findings=[unscannable]),
            _scan_result("trivy"),
            _scan_result("checkov", findings=[manual]),
            _scan_result("codeql"),
        ]

        def _pr_must_not_be_called(*a, **k):
            raise AssertionError("open_pr_if_needed must not be called (AC21)")

        results, fake_run = _drive(monkeypatch, scan_results, pr_side_effect=_pr_must_not_be_called)

        payload = _terminal_payload(results)
        assert payload["status"] == "succeeded"
        assert payload["outcome"] == "needs_review"
        assert payload["pr_url"] is None
        # S-141 real-invocation finding (user story 4): with no PR body to
        # carry them, the remaining findings MUST still be visible -- the
        # real memo-cli fix run terminated here with two unscannable Gitleaks
        # findings visible nowhere but a metrics count.
        reports = [a for a in fake_run.artifacts if a["type"] == "audit_report"]
        assert len(reports) == 1
        meta = reports[0]["metadata"]
        assert meta["total_findings"] == 2
        assert len(meta["by_bucket"]["manual"]) == 1
        assert len(meta["by_bucket"]["unscannable"]) == 1
        assert (
            meta["findings_before"]
            == meta["findings_after"]
            == {"mechanical": 0, "manual": 1, "unscannable": 1}
        )


# ---------------------------------------------------------------------------
# AC22 -- idempotency (existing open PR)
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_existing_pr_short_circuits_not_applicable(self, monkeypatch):
        mech = _mechanical_semgrep()
        scan_results = [_scan_result("semgrep", findings=[mech])] + [
            _scan_result(t) for t in ALL_FIVE if t != "semgrep"
        ]
        semgrep_outcome = FixOutcome(
            applied_fingerprints=frozenset({fingerprint(mech)}), unresolved=()
        )
        existing = PullRequestResult(
            url="https://github.com/org/repo/pull/7", created=False, existed=True
        )

        results, fake_run = _drive(
            monkeypatch,
            scan_results,
            semgrep_outcome=semgrep_outcome,
            rescan_results_or_side_effect=_clean_results(),
            pr_result=existing,
        )

        payload = _terminal_payload(results)
        assert payload["status"] == "succeeded"
        assert payload["outcome"] == "not_applicable"
        assert payload["pr_url"] == "https://github.com/org/repo/pull/7"
        pr_artifacts = [a for a in fake_run.artifacts if a["type"] == "pull_request"]
        assert len(pr_artifacts) == 1
        assert pr_artifacts[0]["metadata"]["existed"] is True
        # The audit_report is written before open_pr, so the short-circuit
        # path gets one too (verifier F-1 on PR #242: guard against a future
        # refactor moving the write after open_pr_if_needed()).
        assert sum(a["type"] == "audit_report" for a in fake_run.artifacts) == 1


# ---------------------------------------------------------------------------
# AC29 -- all 7 run_steps present, in order, each terminal
# ---------------------------------------------------------------------------


class TestRunStepsComplete:
    def test_happy_path_has_all_seven_steps_in_order(self, monkeypatch):
        mech = _mechanical_semgrep()
        scan_results = [_scan_result("semgrep", findings=[mech])] + [
            _scan_result(t) for t in ALL_FIVE if t != "semgrep"
        ]
        semgrep_outcome = FixOutcome(
            applied_fingerprints=frozenset({fingerprint(mech)}), unresolved=()
        )

        results, fake_run = _drive(
            monkeypatch,
            scan_results,
            semgrep_outcome=semgrep_outcome,
            rescan_results_or_side_effect=_clean_results(),
        )

        _terminal_payload(results)
        assert fake_run.step_calls == [
            "resolve_credentials",
            "checkout",
            "scan",
            "classify",
            "fix",
            "rescan",
            "open_pr",
        ]
        # Exactly one terminal call (succeed xor fail), not both.
        assert len(fake_run.succeed_calls) + len(fake_run.fail_calls) == 1


# ---------------------------------------------------------------------------
# requirement 47 -- runs.metrics contract
# ---------------------------------------------------------------------------


class TestMetricsContract:
    def test_metrics_carries_fix_attempt_counts_and_scanner_lists(self, monkeypatch):
        mech = _mechanical_semgrep()
        scan_results = [_scan_result("semgrep", findings=[mech])] + [
            _scan_result(t) for t in ALL_FIVE if t != "semgrep"
        ]
        semgrep_outcome = FixOutcome(
            applied_fingerprints=frozenset({fingerprint(mech)}), unresolved=()
        )

        results, fake_run = _drive(
            monkeypatch,
            scan_results,
            semgrep_outcome=semgrep_outcome,
            rescan_results_or_side_effect=_clean_results(),
        )

        _terminal_payload(results)
        metrics = fake_run.succeed_calls[0]["metrics"]
        assert "fix_attempts_deterministic" in metrics
        assert "fix_attempts_llm" in metrics
        assert "findings_before" in metrics
        assert "findings_after" in metrics
        assert set(metrics["scanners_run"]) == set(ALL_FIVE)
        assert metrics["scanners_skipped"] == []
        assert metrics["scanners_failed"] == []
        assert metrics["fix_attempts_deterministic"] == 1
        assert metrics["fix_attempts_llm"] == 0


# ---------------------------------------------------------------------------
# Heartbeat under load -- a deliberately slow scan fixture proves the
# stream stays alive past IDLE_SESSION_TIMEOUT (mirrors ADR-006's approach)
# ---------------------------------------------------------------------------


class TestHeartbeatUnderLoad:
    def test_slow_scan_emits_heartbeat_chunks_before_terminal(self, monkeypatch):
        """A deliberately slow `run_scanners` (simulating CodeQL's database-
        build phase) must not block the stream from emitting heartbeats --
        `scan` and `rescan` are both wrapped in `run_with_heartbeat` (spec
        §9.2). Uses a tiny `HEARTBEAT_INTERVAL` override so the test does
        not actually wait real minutes."""
        import time

        import main

        monkeypatch.setattr(main, "HEARTBEAT_INTERVAL", 0.01)

        def _slow_scan(workspace, requested, timeout):
            time.sleep(0.05)
            return _clean_results()

        results, fake_run = _drive(monkeypatch, _slow_scan)

        from heartbeat import is_heartbeat_chunk, is_terminal_chunk

        assert any(is_heartbeat_chunk(r) for r in results)
        assert sum(1 for r in results if is_terminal_chunk(r)) == 1
        # The terminal chunk is always last (CT-3).
        assert is_terminal_chunk(results[-1])


# ---------------------------------------------------------------------------
# ALL_SCANNERS_FAILED during a fix-mode initial scan (shared boundary,
# mirrors audit_only's own coverage -- proves the shared scan/classify code
# path still raises correctly for fix mode too).
# ---------------------------------------------------------------------------


class TestScannerFailureFixMode:
    def test_all_scanners_failing_on_initial_scan_terminates_all_scanners_failed(self, monkeypatch):
        from scanners import AllScannersFailedError

        failed_results = [
            _scan_result(t, status=ScanStatus.FAILED, reason=f"{t} crashed") for t in ALL_FIVE
        ]

        def _raise(workspace, requested, timeout):
            raise AllScannersFailedError(failed_results)

        def _pr_must_not_be_called(*a, **k):
            raise AssertionError("open_pr_if_needed must not be called")

        results, fake_run = _drive(monkeypatch, _raise, pr_side_effect=_pr_must_not_be_called)

        payload = _terminal_payload(results)
        assert payload["status"] == "failed"
        assert payload["outcome"] == "not_applicable"
        assert payload["error_code"] == "ALL_SCANNERS_FAILED"
