"""L1 tests for the outcome mapping (S-190 AC2; spec §8.9 v2.5; FR-26; D-20, D-61, D-67).

``outcomes.py`` turns every terminal path of a Wave A run into one
:class:`outcomes.RunResult`. These tests build each row from the real step
result it comes from (``refusal.CheckOutcome``, ``checkout.CheckoutResult``,
``claim.ClaimOutcome``, or the typed exception), so a step that changed its
shape would fail here, not in production.

- TC-190-03: one test per Wave A row of §8.9.
- TC-190-04: every ``needs_review`` and ``not_applicable`` result carries a
  non-empty ``result.summary`` holding the reason; an empty one is rejected.
- TC-190-05: only ``failed`` counts toward the breaker (D-20).
- TC-190-12: the agent can produce exactly ``fixed``, ``not_applicable`` and
  ``needs_review`` on ``succeeded``, plus ``failed``; never ``no_findings``. A
  static check finds no label route or constant, no search and no issue
  listing in the source (FR-3, D-90).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import outcomes
from checkout import CheckoutResult
from claim import ClaimOutcome
from credentials import CredentialError, PermissionMissing
from github_client import GitHubRequestRejected, GitHubUnavailable
from outcomes import (
    BREAKER_FREE_STATUSES,
    ERROR_CODES,
    FIX_LOOP_DISABLED,
    PRODUCIBLE_OUTCOMES,
    REFUSAL_REASONS,
    WAVE_A_ROWS,
    OutcomeError,
    RunResult,
    failed,
    fix_loop_disabled,
    fixed,
    from_check,
    from_checkout,
    from_claim,
    from_exception,
    lost_race,
    needs_review,
    refused,
)
from refusal import CheckOutcome, SupabaseUnavailable

PKG = Path(__file__).resolve().parents[2]
TOKEN = "ghs_" + "S" * 36


def _refusal_outcome(code: str) -> CheckOutcome:
    return CheckOutcome(
        status="succeeded",
        summary=f"Bug-fix didn't start: {code}",
        outcome="not_applicable",
        reason=code,
        reply="posted",
    )


def _fault_outcome(code: str) -> CheckOutcome:
    return CheckOutcome(status="failed", summary=f"{code}: something broke", error_code=code)


# ---------------------------------------------------------------------------
# TC-190-03: one test per Wave A row
# ---------------------------------------------------------------------------


class TestWaveARows:
    @pytest.mark.parametrize("code", ["pull_request", "closed", "linked_pr", "active_run"])
    def test_a_refusal_check_is_not_applicable(self, code):
        res = from_check(_refusal_outcome(code))
        assert res is not None
        assert (res.status, res.outcome, res.reason, res.error_code) == (
            "succeeded",
            "not_applicable",
            code,
            None,
        )
        assert code in res.summary

    def test_invalid_params_is_not_applicable(self):
        out = CheckOutcome(
            status="succeeded",
            summary="Bug-fix didn't start: the run parameter `max_turns` is missing or invalid.",
            outcome="not_applicable",
            reason="invalid_params",
        )
        res = from_check(out)
        assert res is not None
        assert (res.status, res.outcome, res.reason) == (
            "succeeded",
            "not_applicable",
            "invalid_params",
        )
        assert "max_turns" in res.result()["summary"]

    def test_repo_gate_is_not_applicable_with_every_missing_item(self):
        refusal = CheckOutcome(
            status="succeeded",
            summary="repo gate: missing script typecheck; missing .claude/agents/developer.md",
            outcome="not_applicable",
            reason="repo_gate",
        )
        res = from_checkout(CheckoutResult(status="refused", summary="x", refusal=refusal))
        assert res is not None
        assert (res.status, res.outcome, res.reason) == ("succeeded", "not_applicable", "repo_gate")
        assert "typecheck" in res.summary and "developer.md" in res.summary

    def test_a_lost_race_is_not_applicable_active_run(self):
        claim = ClaimOutcome(
            status="lost",
            summary="bug-fix run X claimed #12 first; this run withdrew its claim (active_run)",
            winner="x",
            withdrawal="deleted",
        )
        res = from_claim(claim)
        assert res is not None
        assert (res.status, res.outcome, res.reason) == (
            "succeeded",
            "not_applicable",
            "active_run",
        )
        assert "withdrew" in res.summary

    def test_a_lost_race_whose_comment_was_already_gone_is_the_same_row(self):
        claim = ClaimOutcome(
            status="lost", summary="lost (already gone)", withdrawal="already_gone"
        )
        res = from_claim(claim)
        assert res is not None
        assert (res.outcome, res.reason) == ("not_applicable", "active_run")

    def test_fix_loop_not_yet_enabled_is_needs_review(self):
        res = fix_loop_disabled()
        assert (res.status, res.outcome, res.reason) == (
            "succeeded",
            "needs_review",
            "fix_loop_disabled",
        )
        assert res.summary == FIX_LOOP_DISABLED == "fix loop not yet enabled"

    @pytest.mark.parametrize(
        "code",
        [
            "GITHUB_PERMISSION_MISSING",
            "CREDENTIALS_UNAVAILABLE",
            "GITHUB_UNAVAILABLE",
            "GITHUB_REQUEST_REJECTED",
            "SUPABASE_UNAVAILABLE",
        ],
    )
    def test_a_preflight_or_refusal_fault_is_failed_with_its_code(self, code):
        res = from_check(_fault_outcome(code))
        assert res is not None
        assert (res.status, res.outcome, res.error_code) == ("failed", None, code)

    @pytest.mark.parametrize("code", ["CLONE_FAILED", "INSTALL_FAILED"])
    def test_a_checkout_fault_is_failed_with_its_code(self, code):
        res = from_checkout(CheckoutResult(status="failed", summary=f"{code}: x", error_code=code))
        assert res is not None
        assert (res.status, res.error_code) == ("failed", code)

    @pytest.mark.parametrize(
        "code", ["GITHUB_UNAVAILABLE", "GITHUB_REQUEST_REJECTED", "SUPABASE_UNAVAILABLE"]
    )
    def test_a_claim_fault_is_failed_with_its_code(self, code):
        res = from_claim(ClaimOutcome(status="failed", summary=f"{code}: x", error_code=code))
        assert res is not None
        assert (res.status, res.error_code) == ("failed", code)

    def test_an_unhandled_exception_is_unhandled_error(self):
        res = from_exception(RuntimeError("boom"), [])
        assert (res.status, res.error_code) == ("failed", "UNHANDLED_ERROR")
        assert "RuntimeError" in res.summary

    def test_proceed_steps_map_to_none(self):
        assert from_check(CheckOutcome(status="proceed", summary="ok")) is None
        assert from_checkout(CheckoutResult(status="proceed", summary="ok")) is None
        assert from_claim(ClaimOutcome(status="owned", summary="ok")) is None

    def test_the_row_table_covers_every_wave_a_path_of_the_spec(self):
        paths = {row.path for row in WAVE_A_ROWS}
        assert paths == {
            "refusal:pull_request",
            "refusal:closed",
            "refusal:linked_pr",
            "refusal:active_run",
            "refusal:repo_gate",
            "refusal:invalid_params",
            "lost_race",
            "fix_loop_disabled",
            "GITHUB_PERMISSION_MISSING",
            "CREDENTIALS_UNAVAILABLE",
            "CLONE_FAILED",
            "INSTALL_FAILED",
            "GITHUB_UNAVAILABLE",
            "GITHUB_REQUEST_REJECTED",
            "SUPABASE_UNAVAILABLE",
            "UNHANDLED_ERROR",
        }

    @pytest.mark.parametrize("row", WAVE_A_ROWS, ids=lambda r: r.path)
    def test_each_row_builds_its_status_outcome_and_code(self, row):
        res = row.build()
        assert (res.status, res.outcome, res.error_code) == (
            row.status,
            row.outcome,
            row.error_code,
        )
        assert res.counts_toward_breaker is row.breaker


# ---------------------------------------------------------------------------
# Typed exceptions map by their own code (S-185 residual: exc.error_code)
# ---------------------------------------------------------------------------


class TestFromException:
    def test_permission_missing_on_a_refresh_is_github_permission_missing(self):
        res = from_exception(PermissionMissing("the refreshed token lacks issues: write"), [])
        assert res.error_code == "GITHUB_PERMISSION_MISSING"

    def test_a_mint_failure_is_credentials_unavailable(self):
        res = from_exception(CredentialError("TOKEN_MINT_FAILED", "GitHub answered 500"), [])
        assert res.error_code == "CREDENTIALS_UNAVAILABLE"

    @pytest.mark.parametrize(
        ("exc", "code"),
        [
            (GitHubUnavailable("GET x returned 502"), "GITHUB_UNAVAILABLE"),
            (GitHubRequestRejected("POST x returned 422"), "GITHUB_REQUEST_REJECTED"),
            (SupabaseUnavailable("v_runs read returned 500"), "SUPABASE_UNAVAILABLE"),
        ],
    )
    def test_github_and_supabase_faults_keep_their_code(self, exc, code):
        assert from_exception(exc, []).error_code == code

    def test_the_summary_is_scrubbed(self):
        res = from_exception(RuntimeError(f"leaked {TOKEN}"), [TOKEN])
        assert TOKEN not in res.summary
        assert TOKEN not in str(res.terminal())


# ---------------------------------------------------------------------------
# TC-190-04: a reason in result.summary, always
# ---------------------------------------------------------------------------


class TestSummary:
    @pytest.mark.parametrize("row", WAVE_A_ROWS, ids=lambda r: r.path)
    def test_every_row_has_a_non_empty_summary_in_result(self, row):
        res = row.build()
        assert res.result()["summary"].strip()
        if res.outcome in ("needs_review", "not_applicable"):
            assert res.result()["reason"] == res.reason
            assert res.reason

    @pytest.mark.parametrize("summary", ["", "   ", "\n\t"])
    @pytest.mark.parametrize(
        "make",
        [
            lambda s: refused("closed", s),
            lambda s: lost_race(s),
            lambda s: needs_review("fix_loop_disabled", s),
            lambda s: failed("CLONE_FAILED", s),
            lambda s: fixed(s),
        ],
        ids=["refused", "lost_race", "needs_review", "failed", "fixed"],
    )
    def test_an_empty_summary_is_rejected(self, make, summary):
        with pytest.raises(OutcomeError):
            make(summary)

    @pytest.mark.parametrize("reason", ["", None])
    def test_a_needs_review_or_not_applicable_needs_a_reason(self, reason):
        with pytest.raises(OutcomeError):
            needs_review(reason, "why")  # type: ignore[arg-type]
        with pytest.raises(OutcomeError):
            RunResult("succeeded", "not_applicable", "why", reason=reason)

    def test_an_unknown_refusal_code_is_rejected(self):
        with pytest.raises(OutcomeError):
            refused("labels_missing", "nope")

    def test_an_unknown_error_code_is_rejected(self):
        with pytest.raises(OutcomeError):
            failed("SOMETHING_ELSE", "nope")

    def test_failed_has_no_outcome_and_succeeded_has_no_error_code(self):
        with pytest.raises(OutcomeError):
            RunResult("failed", "needs_review", "x", error_code="CLONE_FAILED")
        with pytest.raises(OutcomeError):
            RunResult("succeeded", "fixed", "x", error_code="CLONE_FAILED")
        with pytest.raises(OutcomeError):
            RunResult("failed", None, "x")

    def test_terminal_payload_carries_the_reason_and_code(self):
        assert refused("closed", "closed issue").terminal() == {
            "status": "succeeded",
            "outcome": "not_applicable",
            "reason": "closed",
            "summary": "closed issue",
        }
        assert failed("CLONE_FAILED", "CLONE_FAILED: x").terminal() == {
            "status": "failed",
            "error_code": "CLONE_FAILED",
            "summary": "CLONE_FAILED: x",
        }


# ---------------------------------------------------------------------------
# TC-190-05: only failed counts toward the breaker (D-20)
# ---------------------------------------------------------------------------


class TestBreaker:
    def test_every_succeeded_row_is_breaker_free_and_every_failed_row_counts(self):
        for row in WAVE_A_ROWS:
            res = row.build()
            assert res.counts_toward_breaker is (res.status == "failed"), row.path
        assert {"succeeded"} == BREAKER_FREE_STATUSES

    @pytest.mark.parametrize("code", sorted(ERROR_CODES))
    def test_every_error_code_counts(self, code):
        assert failed(code, f"{code}: x").counts_toward_breaker is True

    @pytest.mark.parametrize("outcome", sorted(PRODUCIBLE_OUTCOMES))
    def test_every_succeeded_outcome_does_not_count(self, outcome):
        reason = None if outcome == "fixed" else "closed"
        assert RunResult("succeeded", outcome, "x", reason=reason).counts_toward_breaker is False


# ---------------------------------------------------------------------------
# TC-190-12: the outcomes it can produce; no labels, no listing, no search
# ---------------------------------------------------------------------------


def _sources() -> list[Path]:
    return sorted(p for p in PKG.glob("*.py") if p.name != "agent_reporter.py")


def _strings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    return [
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


class TestProducibleOutcomes:
    def test_exactly_three_succeeded_outcomes_and_never_no_findings(self):
        assert frozenset({"fixed", "not_applicable", "needs_review"}) == PRODUCIBLE_OUTCOMES
        with pytest.raises(OutcomeError):
            RunResult("succeeded", "no_findings", "x")

    def test_no_source_names_no_findings_as_an_outcome(self):
        for path in _sources():
            for value in _strings(path):
                assert value != "no_findings", path.name

    def test_refusal_reasons_are_the_spec_codes(self):
        assert REFUSAL_REASONS == (
            "pull_request",
            "closed",
            "linked_pr",
            "active_run",
            "repo_gate",
            "invalid_params",
        )

    def test_the_error_codes_are_a_closed_set(self):
        assert {
            "GITHUB_PERMISSION_MISSING",
            "CREDENTIALS_UNAVAILABLE",
            "CLONE_FAILED",
            "INSTALL_FAILED",
            "CLI_CRASHED",
            "GITHUB_UNAVAILABLE",
            "GITHUB_REQUEST_REJECTED",
            "SUPABASE_UNAVAILABLE",
            "PR_CREATE_FAILED",
            "UNHANDLED_ERROR",
        } <= ERROR_CODES

    def test_every_error_code_main_can_report_is_in_the_set(self):
        text = (PKG / "main.py").read_text()
        for code in re.findall(r'"([A-Z][A-Z_]{4,})"', text):
            if code.endswith(("_ENABLED", "_ID", "_KEY", "_TOKEN", "_PEM")):
                continue
            assert code in ERROR_CODES, code


_FORBIDDEN = [
    (re.compile(r"/labels\b"), "a labels route"),
    (re.compile(r"/assignees\b"), "an assignees route"),
    (re.compile(r"search/issues"), "an issue search"),
    (re.compile(r"/issues\?"), "an issue listing"),
    (
        re.compile(r"\bissues\s*\(\s*(first|last|states|labels|filterBy)\b"),
        "a GraphQL issue listing",
    ),
    (re.compile(r"\bsearch\s*\(\s*(query|type)\b"), "a GraphQL search"),
    (re.compile(r"\b(status|type):\s+\w"), "a github-ops label name"),
]


# The one allowed hit: the S-182 spike probe finds its own probe issue
# ("[probe] bug-fix board probe") by listing issues. Probe mode runs only with
# ALLOW_PROBE=1 on the runtime and a top-level ``__probe`` (D-70), never on a
# /bug-fix run, and the runtime no longer sets ALLOW_PROBE (task 3.10).
_PROBE_ONLY = {("probe.py", "/issues?state=all&per_page=100")}


@pytest.mark.parametrize("path", _sources(), ids=lambda p: p.name)
def test_no_label_route_constant_listing_or_search_in_the_source(path):
    for value in _strings(path):
        if any(path.name == name and needle in value for name, needle in _PROBE_ONLY):
            continue
        for pattern, what in _FORBIDDEN:
            assert not pattern.search(value), f"{path.name}: {what} in {value[:80]!r}"
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    assert not re.search(r"LABELS$", target.id), f"{path.name}: {target.id}"


def test_the_outcomes_module_has_no_io():
    text = (PKG / "outcomes.py").read_text()
    for name in ("requests", "subprocess", "urllib", "boto3", "socket"):
        assert f"import {name}" not in text
    assert outcomes.__doc__ and "§8.9" in outcomes.__doc__


def test_an_unhandled_summary_names_the_type_once():
    """QA-190-03: scrub_exception already gives ``Type: message``."""
    res = outcomes.from_exception(RuntimeError("boom"), [])
    assert res.summary == "UNHANDLED_ERROR: RuntimeError: boom"


@pytest.mark.parametrize(
    ("exc", "summary"),
    [
        (RuntimeError(), "UNHANDLED_ERROR: RuntimeError"),
        (KeyError("k"), "UNHANDLED_ERROR: KeyError: 'k'"),
        (
            ValueError("a RuntimeError: inside"),
            "UNHANDLED_ERROR: ValueError: a RuntimeError: inside",
        ),
    ],
)
def test_an_unhandled_summary_names_each_type_once(exc, summary):
    res = outcomes.from_exception(exc, [])
    assert res.summary == summary
    assert res.summary.count(type(exc).__name__) == 1
