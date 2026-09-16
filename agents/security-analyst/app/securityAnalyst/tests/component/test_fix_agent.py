"""
Component tests for the LLM fix agent's per-finding escape hatch
(`fix_agent.run_fix_loop_for_finding`, spec §8.6/§12, PRD requirements
29-32/D22/D26, story S-138, task 14.10).

`strands.Agent` is always mocked (`patch("fix_agent.Agent")`) -- a real
Bedrock call is never made in this suite. `scanners.run_scanners` is mocked
per-test to control the post-attempt re-scan outcome deterministically,
independent of any real scanner binary.

Covers:
  - PRD AC16: LLM path only reached per-finding, single-finding scope.
  - PRD AC17: `max_fix_attempts` budget applies per finding, not per run --
    each call to `run_fix_loop_for_finding` gets its own fresh counter.
  - PRD AC18: `max_fix_attempts=0` -> zero Bedrock/Agent calls at all, not
    merely zero *successful* fixes.
  - PRD AC19: the fix agent's prompt/tool-call arguments are scoped to
    exactly one finding's record -- inspected directly via the mocked
    Agent's call arguments, never inferred from behavior alone.
  - spec §12 / task 14.8: an out-of-scope diff after an attempt is caught by
    `_assert_diff_confined_to` and the finding is reported unresolved, not
    trusted -- the loop does not silently accept it as success.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from dedupe import MergedFinding
from fix_agent import FixAttemptResult, run_fix_loop_for_finding
from normalize import Finding, Remediation
from scanners import AllScannersFailedError
from scanners.types import ScanResult, ScanStatus
from severity import Severity


def _finding(
    *,
    tool: str = "semgrep",
    rule_id: str = "python.lang.security.audit.eval-detected",
    severity: Severity = Severity.HIGH,
    file_path: str = "src/app.py",
    line_start: int = 10,
    line_end: int = 10,
    message: str = "Detected use of eval().",
    cwe_or_category: str = "CWE-95",
    remediation: Remediation | None = None,
    raw_ref: str = "semgrep_findings.json#0",
) -> Finding:
    return Finding(
        tool=tool,
        rule_id=rule_id,
        severity=severity,
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        message=message,
        cwe_or_category=cwe_or_category,
        remediation=remediation,
        raw_ref=raw_ref,
    )


def _merged(finding: Finding, *, reported_by: tuple[str, ...] | None = None) -> MergedFinding:
    return MergedFinding(finding=finding, reported_by=reported_by or (finding.tool,))


def _other_finding() -> Finding:
    """A second, unrelated finding that must never reach the fix agent's
    prompt/tool-call arguments in these tests (AC19)."""
    return _finding(
        tool="checkov",
        rule_id="CKV_AWS_1",
        file_path="infra/main.tf",
        message="Unrelated Checkov finding that must never leak into the prompt.",
        cwe_or_category="CWE-000",
        raw_ref="checkov_findings.json#0",
    )


@pytest.fixture
def git_workspace(tmp_path):
    """A real git working tree so `_assert_diff_confined_to` exercises a
    genuine `git status --porcelain` call, not a mock."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("eval(user_input)\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=tmp_path, check=True)
    return tmp_path


def _scan_result(tool: str, findings: list[Finding]) -> ScanResult:
    return ScanResult(tool=tool, status=ScanStatus.PASSED, findings=findings, reason=None)


@pytest.mark.component
class TestMaxAttemptsZero:
    """max_attempts=0 must result in zero Agent/Bedrock calls (PRD AC18)."""

    @patch("fix_agent.Agent")
    def test_zero_attempts_no_agent_call(self, mock_agent_class, git_workspace):
        finding = _merged(_finding())
        result = run_fix_loop_for_finding(str(git_workspace), finding, 0)

        mock_agent_class.assert_not_called()
        assert result.resolved is False
        assert result.attempts == 0
        assert result.llm_used is False

    @patch("fix_agent.run_scanners")
    @patch("fix_agent.Agent")
    def test_zero_attempts_no_rescan_call_either(
        self, mock_agent_class, mock_run_scanners, git_workspace
    ):
        """Zero attempts means the loop body never executes at all -- the
        re-scan call is never reached either, not just the Agent call."""
        finding = _merged(_finding())
        run_fix_loop_for_finding(str(git_workspace), finding, 0)

        mock_run_scanners.assert_not_called()


@pytest.mark.component
class TestPerFindingBudget:
    """`max_fix_attempts` applies per finding, not per run (PRD AC17)."""

    @patch("fix_agent.run_scanners")
    @patch("fix_agent.Agent")
    def test_exhausts_own_budget_when_never_resolved(
        self, mock_agent_class, mock_run_scanners, git_workspace
    ):
        finding = _merged(_finding())
        mock_agent_class.return_value = MagicMock()
        # Re-scan always reports the finding still present.
        mock_run_scanners.return_value = [_scan_result("semgrep", [finding.finding])]

        result = run_fix_loop_for_finding(str(git_workspace), finding, 3)

        assert mock_agent_class.call_count == 3
        assert result.attempts == 3
        assert result.resolved is False
        assert result.llm_used is True

    @patch("fix_agent.run_scanners")
    @patch("fix_agent.Agent")
    def test_stops_early_on_resolution(self, mock_agent_class, mock_run_scanners, git_workspace):
        finding = _merged(_finding())
        mock_agent_class.return_value = MagicMock()
        # First rescan: still present. Second rescan: gone (resolved).
        mock_run_scanners.side_effect = [
            [_scan_result("semgrep", [finding.finding])],
            [_scan_result("semgrep", [])],
        ]

        result = run_fix_loop_for_finding(str(git_workspace), finding, 5)

        assert mock_agent_class.call_count == 2
        assert result.attempts == 2
        assert result.resolved is True
        assert result.llm_used is True

    @patch("fix_agent.run_scanners")
    @patch("fix_agent.Agent")
    def test_each_finding_gets_its_own_fresh_budget(
        self, mock_agent_class, mock_run_scanners, git_workspace
    ):
        """Finding A exhausts its budget without success; finding B, called
        independently afterward, still gets its own full budget -- no
        shared/leaking counter across calls (this is the architectural
        departure from the sibling agent's per-run budget, task 14.6)."""
        finding_a = _merged(_finding(file_path="src/app.py", rule_id="rule-a"))
        finding_b_source = _finding(file_path="src/app.py", rule_id="rule-b")
        finding_b = _merged(finding_b_source)

        mock_agent_class.return_value = MagicMock()

        # Finding A: always still present (never resolves).
        mock_run_scanners.side_effect = [
            [_scan_result("semgrep", [finding_a.finding])],
            [_scan_result("semgrep", [finding_a.finding])],
        ]
        result_a = run_fix_loop_for_finding(str(git_workspace), finding_a, 2)
        assert result_a.attempts == 2
        assert result_a.resolved is False
        assert mock_agent_class.call_count == 2

        # Finding B: resolves on its own first attempt. Its budget/counter
        # is independent of finding A's exhausted one.
        mock_run_scanners.side_effect = [[_scan_result("semgrep", [])]]
        result_b = run_fix_loop_for_finding(str(git_workspace), finding_b, 2)
        assert result_b.attempts == 1
        assert result_b.resolved is True
        # Agent call count continued accumulating on the shared mock (2 from
        # A + 1 from B) -- the important assertion is B's own `attempts`
        # value, which proves its counter started fresh at 1, not at 3.
        assert mock_agent_class.call_count == 3


@pytest.mark.component
class TestSingleFindingScope:
    """The fix agent receives only the single targeted finding's record,
    never the full findings list (PRD AC19, requirement 31, task 14.4)."""

    @patch("fix_agent.run_scanners")
    @patch("fix_agent.Agent")
    def test_prompt_contains_only_target_finding_fields(
        self, mock_agent_class, mock_run_scanners, git_workspace
    ):
        mock_agent_instance = MagicMock()
        mock_agent_class.return_value = mock_agent_instance
        mock_run_scanners.return_value = [_scan_result("semgrep", [])]

        target = _finding(rule_id="python.lang.security.audit.eval-detected")
        other = _other_finding()
        finding = _merged(target)

        run_fix_loop_for_finding(str(git_workspace), finding, 1)

        # Inspect the actual prompt text passed to the mocked Agent
        # instance's call -- the only reliable evidence of what the model
        # would have seen, not just what run_fix_loop_for_finding's
        # signature happens to accept.
        assert mock_agent_instance.call_count == 1
        prompt = mock_agent_instance.call_args[0][0]
        assert target.rule_id in prompt
        assert target.file_path in prompt
        assert target.message in prompt
        # The unrelated finding's identifying details must never appear.
        assert other.rule_id not in prompt
        assert other.file_path not in prompt
        assert other.message not in prompt

    def test_function_signature_takes_one_finding_not_a_list(self):
        """Structural guarantee (task 14.4): the function's own signature
        accepts a single `MergedFinding`, not a list -- it is impossible to
        pass the full findings list even by caller mistake."""
        import inspect

        sig = inspect.signature(run_fix_loop_for_finding)
        params = list(sig.parameters.values())
        finding_param = next(p for p in params if p.name == "finding")
        assert finding_param.annotation in ("MergedFinding", MergedFinding)

    @patch("fix_agent.run_scanners")
    @patch("fix_agent.Agent")
    def test_rescan_requests_only_the_targeted_finding_s_tool(
        self, mock_agent_class, mock_run_scanners, git_workspace
    ):
        """The re-scan call after an attempt is scoped to the single
        finding's own tool, not every scanner (spec §8.6 pseudocode)."""
        mock_agent_class.return_value = MagicMock()
        mock_run_scanners.return_value = [_scan_result("semgrep", [])]

        finding = _merged(_finding(tool="semgrep"))
        run_fix_loop_for_finding(str(git_workspace), finding, 1)

        mock_run_scanners.assert_called_once()
        call_args = mock_run_scanners.call_args[0]
        assert call_args[1] == ["semgrep"]


@pytest.mark.component
class TestDiffConfinementEnforced:
    """A diff touching a file outside the finding's own path is caught and
    the finding is reported unresolved, not trusted (spec §12, task 14.8)."""

    @patch("fix_agent.run_scanners")
    @patch("fix_agent.Agent")
    def test_out_of_scope_write_reports_unresolved(
        self, mock_agent_class, mock_run_scanners, git_workspace
    ):
        """The mocked Agent's call simulates the LLM writing to a file
        outside the finding's path. Even though the re-scan (mocked) would
        report the finding itself gone, the out-of-scope diff must still
        cause the finding to be reported unresolved -- the diff confinement
        check runs, and fails, before/independent of trusting the rescan."""

        def _simulate_out_of_scope_write(prompt):
            (git_workspace / "src" / "unexpected.py").write_text("malicious = True\n")

        mock_agent_instance = MagicMock(side_effect=_simulate_out_of_scope_write)
        mock_agent_class.return_value = mock_agent_instance
        # Even if the scanner call would say "resolved", it must never be
        # reached/trusted once the diff confinement check has failed.
        mock_run_scanners.return_value = [_scan_result("semgrep", [])]

        finding = _merged(_finding(file_path="src/app.py"))
        result = run_fix_loop_for_finding(str(git_workspace), finding, 3)

        assert result.resolved is False
        assert result.violation is not None
        assert "unexpected.py" in result.violation
        # The loop must not burn through the whole attempt budget once a
        # violation is detected -- it stops immediately rather than
        # retrying into more potential violations.
        assert mock_agent_instance.call_count == 1

    @patch("fix_agent.run_scanners")
    @patch("fix_agent.Agent")
    def test_confined_change_does_not_raise_violation(
        self, mock_agent_class, mock_run_scanners, git_workspace
    ):
        """A change confined to the finding's own file is not treated as a
        violation -- the happy path is not broken by the confinement check."""

        def _simulate_in_scope_write(prompt):
            (git_workspace / "src" / "app.py").write_text("safe_eval(user_input)\n")

        mock_agent_instance = MagicMock(side_effect=_simulate_in_scope_write)
        mock_agent_class.return_value = mock_agent_instance
        mock_run_scanners.return_value = [_scan_result("semgrep", [])]

        finding = _merged(_finding(file_path="src/app.py"))
        result = run_fix_loop_for_finding(str(git_workspace), finding, 3)

        assert result.resolved is True
        assert result.violation is None


@pytest.mark.component
class TestAgentException:
    """An Agent exception does not crash the loop -- diff confinement and
    re-scan still run afterward, matching the sibling agent's resilience
    pattern (req 48 there)."""

    @patch("fix_agent.run_scanners")
    @patch("fix_agent.Agent")
    def test_agent_error_continues_loop(self, mock_agent_class, mock_run_scanners, git_workspace):
        mock_agent_instance = MagicMock()
        mock_agent_instance.side_effect = RuntimeError("model unavailable")
        mock_agent_class.return_value = mock_agent_instance
        mock_run_scanners.return_value = [_scan_result("semgrep", [_finding()])]

        finding = _merged(_finding())
        result = run_fix_loop_for_finding(str(git_workspace), finding, 2)

        assert result.attempts == 2
        assert result.llm_used is True
        assert result.resolved is False


@pytest.mark.component
class TestScannerFailureDuringRescan:
    """If the re-scan itself fails for every requested scanner, the loop
    does not crash and does not falsely claim resolution."""

    @patch("fix_agent.run_scanners")
    @patch("fix_agent.Agent")
    def test_all_scanners_failed_treated_as_unresolved_this_attempt(
        self, mock_agent_class, mock_run_scanners, git_workspace
    ):
        mock_agent_class.return_value = MagicMock()
        mock_run_scanners.side_effect = AllScannersFailedError(
            [ScanResult(tool="semgrep", status=ScanStatus.FAILED, findings=[], reason="crashed")]
        )

        finding = _merged(_finding())
        result = run_fix_loop_for_finding(str(git_workspace), finding, 1)

        assert result.resolved is False
        assert result.attempts == 1


@pytest.mark.component
class TestToolsAndSystemPrompt:
    """Agent is created with exactly the 5-tool surface and a system prompt
    forbidding out-of-scope edits (mirrors sibling agent's req 45/47)."""

    @patch("fix_agent.run_scanners")
    @patch("fix_agent.Agent")
    def test_agent_created_with_five_tools(
        self, mock_agent_class, mock_run_scanners, git_workspace
    ):
        mock_agent_class.return_value = MagicMock()
        mock_run_scanners.return_value = [_scan_result("semgrep", [])]

        finding = _merged(_finding())
        run_fix_loop_for_finding(str(git_workspace), finding, 1)

        call_kwargs = mock_agent_class.call_args[1]
        assert "tools" in call_kwargs
        assert len(call_kwargs["tools"]) == 5
        tool_names = {t.__name__ for t in call_kwargs["tools"]}
        assert tool_names == {"shell", "read_file", "write_file", "find_files", "grep_code"}

    @patch("fix_agent.run_scanners")
    @patch("fix_agent.Agent")
    def test_system_prompt_forbids_out_of_scope_edits(
        self, mock_agent_class, mock_run_scanners, git_workspace
    ):
        mock_agent_class.return_value = MagicMock()
        mock_run_scanners.return_value = [_scan_result("semgrep", [])]

        finding = _merged(_finding())
        run_fix_loop_for_finding(str(git_workspace), finding, 1)

        call_kwargs = mock_agent_class.call_args[1]
        assert "system_prompt" in call_kwargs
        prompt = call_kwargs["system_prompt"]
        assert "ONE" in prompt or "single finding" in prompt.lower()
        assert "test" in prompt.lower()


@pytest.mark.component
class TestResultDataclass:
    """`FixAttemptResult` shape sanity (used by S-140's orchestrator)."""

    def test_default_violation_is_none(self):
        result = FixAttemptResult(resolved=True, attempts=1)
        assert result.violation is None
        assert result.llm_used is False
