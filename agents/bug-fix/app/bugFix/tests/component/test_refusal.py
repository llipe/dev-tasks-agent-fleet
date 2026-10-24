"""L2 tests for the preflight and refusal step (S-185 AC1–AC5; D-55, D-58, D-67, D-92, D-104).

GitHub is the in-repo double :class:`FakeGitHub` (DF-186-02), so the step
runs its real request sequence: issue facts, the closing-reference GraphQL
query, open pulls, comments, and the one reply. Supabase (``v_runs``) is the
small PostgREST double below.

TC-185-02, 09, 11, 12, 13, 18–25.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from credentials import CredentialError, TokenContext
from markers import build, parse_block
from refusal import CheckOutcome, RunStatusReader, run_refusal_checks
from scrubber import SecretSet
from tests.component.fake_github import (
    API,
    APP_ID,
    TOKEN,
    FakeGitHub,
    FakeResponse,
    pull_payload,
    redirect,
)

RUN = "0b9a2f4e-1c3d-4e5f-8a6b-7c8d9e0f1a2b"
OTHER = "1c0b3e5f-2d4e-4f60-9b7c-8d9e0f1a2b3c"
ISSUE = 12
SB_URL = "https://sb.example"
SB_KEY = "sb_secret_" + "K" * 40
PAT = "ghp_" + "P" * 36
LINK = "https://panel.example/runs/" + RUN

REFUSAL_CODES = ("pull_request", "closed", "linked_pr", "active_run", "invalid_params")


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class FakeSupabase:
    """PostgREST double for ``GET /rest/v1/v_runs``."""

    def __init__(self, statuses: dict[str, str] | None = None) -> None:
        self.statuses = dict(statuses or {})
        self.calls: list[dict[str, Any]] = []
        self.fail: BaseException | int | None = None
        self.payload_override: Any = None

    def get(
        self, url: str, *, headers=None, params=None, timeout=None, allow_redirects=None
    ) -> FakeResponse:
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "params": params,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
            }
        )
        if isinstance(self.fail, BaseException):
            raise self.fail
        if isinstance(self.fail, int):
            return FakeResponse(self.fail, {"message": f"bad {SB_KEY}"})
        if self.payload_override is not None:
            return FakeResponse(200, self.payload_override)
        wanted = str((params or {}).get("id", ""))
        ids = wanted.removeprefix("in.(").removesuffix(")").split(",")
        rows = [{"id": i, "effective_status": self.statuses[i]} for i in ids if i in self.statuses]
        return FakeResponse(200, rows)


def _token(permissions: Any = None, *, app_id: int | None = APP_ID) -> TokenContext:
    perms = {"issues": "write", "metadata": "read"} if permissions is None else permissions
    return TokenContext(
        token=TOKEN, issued_at=0.0, installation_id=1, app_id=app_id, permissions=perms
    )


def _secrets() -> SecretSet:
    s = SecretSet()
    s.add("GITHUB_INSTALLATION_TOKEN", TOKEN)
    s.add("SUPABASE_SERVICE_ROLE_KEY", SB_KEY)
    s.add("GITHUB_PROJECTS_TOKEN", PAT)
    return s


def _check(
    gh: FakeGitHub,
    sb: FakeSupabase | None = None,
    *,
    params: Any = None,
    token: Any = None,
    run: Any = None,
) -> CheckOutcome:
    sb = sb if sb is not None else FakeSupabase()
    resolve = token if callable(token) else (lambda: token or _token())
    return run_refusal_checks(
        run_id=RUN,
        owner="o",
        repo="r",
        raw_params={"issue_number": ISSUE} if params is None else params,
        resolve_token=resolve,
        run_status=RunStatusReader(SB_URL, SB_KEY, session=sb),
        session=gh,
        run=run,
        run_link=LINK,
        secrets=_secrets(),
    )


def _gh_for(code: str, *, labels=()) -> tuple[FakeGitHub, FakeSupabase]:
    """A fixture whose first matching check is ``code`` (or ``proceed``)."""
    gh = FakeGitHub()
    sb = FakeSupabase()
    if code == "pull_request":
        gh.add_issue(ISSUE, pull_request=True, labels=labels)
    elif code == "closed":
        gh.add_issue(ISSUE, state="closed", labels=labels)
    elif code == "linked_pr":
        gh.add_issue(ISSUE, labels=labels)
        gh.add_closing_ref(ISSUE, 77)
    elif code == "active_run":
        gh.add_issue(ISSUE, labels=labels)
        gh.add_comment(ISSUE, build("claim", OTHER) + "\nworking")
        sb.statuses[OTHER] = "running"
    elif code in ("proceed", "invalid_params"):
        gh.add_issue(ISSUE, labels=labels)
    else:  # pragma: no cover - fixture guard
        raise AssertionError(code)
    return gh, sb


def _params_for(code: str) -> dict:
    if code == "invalid_params":
        return {"issue_number": ISSUE, "max_turns": 500}
    return {"issue_number": ISSUE}


def _write_templates(gh: FakeGitHub) -> list[tuple[str, str]]:
    return [(c.method, c.path) for c in gh.writes()]


# ---------------------------------------------------------------------------
# TC-185-09, TC-185-23: one marked reply, nothing else
# ---------------------------------------------------------------------------


class TestEachRefusalWritesOnce:
    @pytest.mark.parametrize("code", REFUSAL_CODES)
    def test_exactly_one_write_the_marked_reply(self, code):
        gh, sb = _gh_for(code)
        out = _check(gh, sb, params=_params_for(code))
        assert (out.status, out.outcome, out.reason) == ("succeeded", "not_applicable", code)
        assert out.reply == "posted"
        assert _write_templates(gh) == [("POST", f"/repos/o/r/issues/{ISSUE}/comments")]
        assert gh.reactions == []
        assert not any("/reactions" in p or "/labels" in p or "/assignees" in p for p in gh.paths())
        assert all(c.method in ("GET", "POST") for c in gh.calls)
        assert gh.projects_calls() == []

    @pytest.mark.parametrize("code", REFUSAL_CODES)
    def test_the_reply_body_is_marked_with_this_run_and_code(self, code):
        gh, sb = _gh_for(code)
        _check(gh, sb, params=_params_for(code))
        body = gh.writes()[0].json["body"]
        (marker,) = parse_block(body)
        assert (marker.kind, marker.run_id, marker.reason) == ("refusal", RUN, code)
        assert body.splitlines()[-1] == f"Run: {LINK}"
        assert "Issue 12 title" not in body and "issue body" not in body
        assert "reporter" not in body

    @pytest.mark.parametrize("code", REFUSAL_CODES)
    def test_no_claim_and_no_board_touch(self, code):
        gh, sb = _gh_for(code)
        out = _check(gh, sb, params=_params_for(code))
        assert not any(m.kind == "claim" for c in gh.writes() for m in parse_block(c.json["body"]))
        # TC-185-23: no PAT on any request, no Projects query, no board metrics.
        assert all(PAT not in str(c.headers) for c in gh.calls)
        assert "board" not in out.result()
        assert out.proceed is False

    def test_the_linked_pr_reply_names_the_pr(self):
        gh, sb = _gh_for("linked_pr")
        _check(gh, sb)
        assert "pull request #77" in gh.writes()[0].json["body"]


# ---------------------------------------------------------------------------
# AC4: the run ends succeeded / not_applicable with result.reason
# ---------------------------------------------------------------------------


class TestReport:
    @pytest.mark.parametrize("code", REFUSAL_CODES)
    def test_a_refusal_reports_not_applicable_with_the_reason(self, code):
        gh, sb = _gh_for(code)
        run = MagicMock()
        out = _check(gh, sb, params=_params_for(code), run=run)
        out.report(run)
        run.succeed.assert_called_once()
        args, kwargs = run.succeed.call_args
        assert args == ("not_applicable",)
        assert kwargs["result"]["reason"] == code
        assert kwargs["result"]["summary"].startswith("Bug-fix didn't start")
        run.fail.assert_not_called()

    def test_a_fault_reports_failed_with_the_code(self):
        run = MagicMock()
        out = _check(FakeGitHub(), token=_token({"issues": "read"}))
        out.report(run)
        run.fail.assert_called_once()
        assert run.fail.call_args.args[0] == "GITHUB_PERMISSION_MISSING"
        run.succeed.assert_not_called()

    def test_proceed_reports_nothing(self):
        gh, sb = _gh_for("proceed")
        run = MagicMock()
        out = _check(gh, sb)
        out.report(run)
        run.succeed.assert_not_called()
        run.fail.assert_not_called()


# ---------------------------------------------------------------------------
# The happy path proceeds
# ---------------------------------------------------------------------------


class TestProceed:
    def test_an_open_issue_with_nothing_linked_proceeds_with_zero_writes(self):
        gh, sb = _gh_for("proceed")
        out = _check(gh, sb)
        assert out.status == "proceed" and out.proceed is True
        assert out.reason is None and out.error_code is None
        assert out.params is not None and out.params.issue_number == ISSUE
        assert out.facts is not None and out.facts.state == "open"
        assert out.token is not None and out.token.token == TOKEN
        assert gh.writes() == []
        assert out.reply == "none"
        assert out.result() == {}

    def test_the_proceed_request_sequence(self):
        gh, sb = _gh_for("proceed")
        _check(gh, sb)
        assert [(c.method, c.path) for c in gh.calls] == [
            ("GET", f"/repos/o/r/issues/{ISSUE}"),
            ("POST", "/graphql"),
            ("GET", "/repos/o/r/pulls"),
            ("GET", f"/repos/o/r/issues/{ISSUE}/comments"),
        ]
        assert sb.calls == []  # no open claim, so no Supabase read

    def test_every_github_call_uses_the_installation_token(self):
        gh, sb = _gh_for("proceed")
        _check(gh, sb)
        assert all(c.headers["Authorization"] == f"Bearer {TOKEN}" for c in gh.calls)


# ---------------------------------------------------------------------------
# TC-185-02: missing issues: write
# ---------------------------------------------------------------------------


class TestPermission:
    @pytest.mark.parametrize("permissions", [{}, {"issues": "read"}, {"contents": "write"}])
    def test_missing_issues_write_fails_with_zero_github_calls(self, permissions):
        gh, sb = _gh_for("proceed")
        out = _check(gh, sb, token=_token(permissions))
        assert (out.status, out.error_code) == ("failed", "GITHUB_PERMISSION_MISSING")
        assert out.outcome is None
        assert gh.calls == [] and sb.calls == []
        assert out.reply == "none"

    def test_an_absent_permissions_key_fails(self):
        ctx = TokenContext(token=TOKEN, issued_at=0.0, installation_id=1, app_id=APP_ID)
        out = _check(FakeGitHub(), token=ctx)
        assert out.error_code == "GITHUB_PERMISSION_MISSING"

    def test_the_permission_check_precedes_params(self):
        gh = FakeGitHub()
        out = _check(gh, params={}, token=_token({"issues": "read"}))
        assert out.error_code == "GITHUB_PERMISSION_MISSING"


# ---------------------------------------------------------------------------
# TC-185-12: credentials
# ---------------------------------------------------------------------------


class TestCredentials:
    def test_a_mint_failure_is_credentials_unavailable_before_any_github_call(self):
        def boom():
            raise CredentialError("PEM_UNAVAILABLE", f"secret {SB_KEY}")

        gh = FakeGitHub()
        out = _check(gh, token=boom)
        assert (out.status, out.error_code) == ("failed", "CREDENTIALS_UNAVAILABLE")
        assert gh.calls == []
        assert SB_KEY not in out.summary

    def test_a_context_without_an_app_id_cannot_trust_markers(self):
        gh = FakeGitHub()
        out = _check(gh, token=_token(app_id=None))
        assert out.error_code == "CREDENTIALS_UNAVAILABLE"
        assert gh.calls == []


# ---------------------------------------------------------------------------
# TC-185-13: invalid_params
# ---------------------------------------------------------------------------


class TestInvalidParams:
    @pytest.mark.parametrize(
        "extra,key",
        [
            ({"max_turns": 500}, "max_turns"),
            ({"project": "bad"}, "project"),
            ({"status_ready": ""}, "status_ready"),
            ({"trigger_comment_id": "x"}, "trigger_comment_id"),
        ],
    )
    def test_a_bad_key_with_a_valid_issue_replies_naming_the_key(self, extra, key):
        gh, sb = _gh_for("invalid_params")
        out = _check(gh, sb, params={"issue_number": ISSUE, **extra})
        assert (out.status, out.outcome, out.reason) == (
            "succeeded",
            "not_applicable",
            "invalid_params",
        )
        (write,) = gh.writes()
        assert f"`{key}`" in write.json["body"]
        assert parse_block(write.json["body"])[0].reason == "invalid_params"
        # Nothing else is read: an invalid run never inspects the issue.
        assert [c.method for c in gh.calls] == ["POST"]

    @pytest.mark.parametrize(
        "params",
        [{}, {"issue_number": 0}, {"issue_number": "12"}, {"issue_number": True}, None, [], "x"],
    )
    def test_no_usable_issue_number_means_zero_github_writes(self, params):
        gh = FakeGitHub()
        out = run_refusal_checks(
            run_id=RUN,
            owner="o",
            repo="r",
            raw_params=params,
            resolve_token=_token,
            run_status=RunStatusReader(SB_URL, SB_KEY, session=FakeSupabase()),
            session=gh,
        )
        assert (out.status, out.outcome, out.reason) == (
            "succeeded",
            "not_applicable",
            "invalid_params",
        )
        assert gh.calls == []
        assert out.reply == "none"

    def test_an_integral_float_issue_number_is_used(self):
        gh, sb = _gh_for("invalid_params")
        _check(gh, sb, params={"issue_number": float(ISSUE), "max_turns": 1})
        assert gh.writes()[0].path == f"/repos/o/r/issues/{ISSUE}/comments"


# ---------------------------------------------------------------------------
# TC-185-18: pull_request and a missing issue
# ---------------------------------------------------------------------------


class TestPullRequest:
    @pytest.mark.parametrize("state", ["open", "closed"])
    def test_a_pr_payload_refuses_pull_request(self, state):
        gh = FakeGitHub()
        gh.add_issue(ISSUE, pull_request=True, state=state)
        assert _check(gh).reason == "pull_request"
        assert gh.graphql_calls() == []  # first match wins: later checks never run

    def test_a_404_issue_is_invalid_params_with_no_write(self):
        gh = FakeGitHub()
        out = _check(gh)
        assert (out.status, out.reason) == ("succeeded", "invalid_params")
        assert gh.writes() == []
        assert out.reply == "none"

    def test_a_malformed_issue_payload_is_rejected(self):
        gh = FakeGitHub()
        gh.faults["issue"] = [FakeResponse(200, {"number": ISSUE})]  # no state
        out = _check(gh)
        assert (out.status, out.error_code) == ("failed", "GITHUB_REQUEST_REJECTED")


# ---------------------------------------------------------------------------
# TC-185-19: linked_pr (D-55)
# ---------------------------------------------------------------------------


class TestLinkedPr:
    def test_an_open_closing_reference_refuses(self):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.add_closing_ref(ISSUE, 31)
        out = _check(gh)
        assert out.reason == "linked_pr"
        assert "#31" in out.summary

    @pytest.mark.parametrize("state", ["CLOSED", "MERGED"])
    def test_a_closed_or_merged_closing_reference_does_not(self, state):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.add_closing_ref(ISSUE, 31, state=state)
        assert _check(gh).status == "proceed"

    def test_the_graphql_query_asks_for_open_prs_only(self):
        gh, sb = _gh_for("proceed")
        _check(gh, sb)
        (call,) = gh.graphql_calls()
        assert "includeClosedPrs: false" in call.json["query"]
        assert call.json["variables"] == {"owner": "o", "name": "r", "number": ISSUE, "after": None}

    def test_closing_references_are_paged(self):
        gh = FakeGitHub(graphql_page_size=2)
        gh.add_issue(ISSUE)
        for n in (1, 2, 3, 4):
            gh.add_closing_ref(ISSUE, n, state="MERGED")
        gh.add_closing_ref(ISSUE, 5)
        out = _check(gh)
        assert out.reason == "linked_pr" and "#5" in out.summary
        assert len(gh.graphql_calls()) == 3

    @pytest.mark.parametrize(
        "head,refused",
        [
            ("issue/12-x", True),
            ("issue/12-", True),
            ("issue/123-x", False),
            ("issue/12", False),
            ("issue/1-x", False),
            ("Issue/12-x", False),
            ("feature/issue/12-x", False),
            ("story/S-185-x", False),
        ],
    )
    def test_head_branch_prefix(self, head, refused):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.pulls.append(pull_payload(40, head))
        assert (_check(gh).reason == "linked_pr") is refused

    def test_a_fork_pr_with_the_head_prefix_links(self):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.pulls.append(pull_payload(41, "issue/12-from-fork", fork=True))
        out = _check(gh)
        assert out.reason == "linked_pr" and "#41" in out.summary

    def test_a_deleted_fork_head_repo_does_not_crash(self):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.pulls.append(pull_payload(42, "issue/12-gone", fork=None))
        assert _check(gh).reason == "linked_pr"

    @pytest.mark.parametrize(
        "bad", [{"number": 5}, {"number": 5, "head": None}, "x", {"head": {"ref": "issue/12-a"}}]
    )
    def test_malformed_pull_items_are_skipped(self, bad):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.pulls.append(bad if isinstance(bad, dict) else {"state": "open", "x": bad})
        gh.pulls[-1].setdefault("state", "open")
        assert _check(gh).status == "proceed"

    def test_a_closed_unmerged_pr_does_not_link(self):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.pulls.append(pull_payload(43, "issue/12-old", state="closed"))
        assert _check(gh).status == "proceed"

    def test_open_pulls_are_fetched_once_and_paged(self):
        gh = FakeGitHub(per_page_cap=2)
        gh.add_issue(ISSUE)
        for n in range(1, 6):
            gh.pulls.append(pull_payload(n, f"other/{n}"))
        assert _check(gh).status == "proceed"
        assert len([p for p in gh.paths("GET") if p.endswith("/pulls")]) == 3

    def test_the_lowest_linked_pr_is_named(self):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.pulls.append(pull_payload(90, "issue/12-b"))
        gh.add_closing_ref(ISSUE, 55)
        assert "#55" in _check(gh).summary


# ---------------------------------------------------------------------------
# TC-185-20: active_run
# ---------------------------------------------------------------------------


class TestActiveRun:
    @pytest.mark.parametrize("status", ["queued", "running"])
    def test_a_non_terminal_trusted_claim_refuses(self, status):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.add_comment(ISSUE, build("claim", OTHER))
        sb = FakeSupabase({OTHER: status})
        assert _check(gh, sb).reason == "active_run"

    @pytest.mark.parametrize(
        "status", ["succeeded", "failed", "timed_out", "failed_to_start", "canceled"]
    )
    def test_a_terminal_claim_proceeds(self, status):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.add_comment(ISSUE, build("claim", OTHER))
        assert _check(gh, FakeSupabase({OTHER: status})).status == "proceed"

    @pytest.mark.parametrize("kind", ["pr", "disposition"])
    def test_a_closed_claim_proceeds_without_a_supabase_read(self, kind):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.add_comment(ISSUE, build("claim", OTHER))
        gh.add_comment(ISSUE, build(kind, OTHER))
        sb = FakeSupabase({OTHER: "running"})
        assert _check(gh, sb).status == "proceed"
        assert sb.calls == []

    @pytest.mark.parametrize(
        "forger", [{"app_id": None, "user_type": "User"}, {"app_id": 1}, {"user_type": "User"}]
    )
    def test_an_untrusted_claim_is_ignored(self, forger):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.add_comment(ISSUE, build("claim", OTHER), **forger)
        sb = FakeSupabase({OTHER: "running"})
        assert _check(gh, sb).status == "proceed"
        assert sb.calls == []

    def test_a_refusal_marker_is_never_a_claim(self):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.add_comment(ISSUE, build("refusal", OTHER, "active_run"))
        sb = FakeSupabase({OTHER: "running"})
        assert _check(gh, sb).status == "proceed"
        assert sb.calls == []

    def test_a_claim_with_no_v_runs_row_is_not_active(self, caplog):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.add_comment(ISSUE, build("claim", OTHER))
        with caplog.at_level(logging.WARNING, logger="bug_fix.refusal"):
            assert _check(gh, FakeSupabase()).status == "proceed"
        assert any("no v_runs row" in r.getMessage() for r in caplog.records)

    def test_the_v_runs_read_uses_the_service_key_and_the_claimed_ids(self):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.add_comment(ISSUE, build("claim", OTHER))
        sb = FakeSupabase({OTHER: "succeeded"})
        _check(gh, sb)
        (call,) = sb.calls
        assert call["url"] == f"{SB_URL}/rest/v1/v_runs"
        assert call["params"] == {"select": "id,effective_status", "id": f"in.({OTHER})"}
        assert call["headers"]["apikey"] == SB_KEY
        assert call["headers"]["Authorization"] == f"Bearer {SB_KEY}"
        assert call["timeout"]

    def test_this_runs_own_claim_never_blocks_it(self):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.add_comment(ISSUE, build("claim", RUN))
        sb = FakeSupabase({RUN: "running"})
        assert _check(gh, sb).status == "proceed"


# ---------------------------------------------------------------------------
# TC-185-22: Supabase failure
# ---------------------------------------------------------------------------


class TestSupabaseUnavailable:
    @pytest.mark.parametrize(
        "fail,override",
        [
            (requests.ConnectionError(f"down {SB_KEY}"), None),
            (500, None),
            (401, None),
            (None, {"not": "a list"}),
            (None, [{"id": OTHER}]),
            (None, [{"id": OTHER, "effective_status": 3}]),
            (None, ["x"]),
        ],
    )
    def test_a_read_failure_is_supabase_unavailable_with_no_write(self, fail, override):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.add_comment(ISSUE, build("claim", OTHER))
        sb = FakeSupabase()
        sb.fail = fail
        sb.payload_override = override
        out = _check(gh, sb)
        assert (out.status, out.error_code) == ("failed", "SUPABASE_UNAVAILABLE")
        assert gh.writes() == [] and gh.projects_calls() == []
        assert SB_KEY not in out.summary

    def test_a_non_json_body_is_unavailable(self):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.add_comment(ISSUE, build("claim", OTHER))

        class NoJson(FakeSupabase):
            def get(self, url, **kw):
                self.calls.append(kw)
                return FakeResponse(200, None)

        assert _check(gh, NoJson()).error_code == "SUPABASE_UNAVAILABLE"


# ---------------------------------------------------------------------------
# TC-185-11: GitHub faults are never read as "no match"
# ---------------------------------------------------------------------------


class TestGitHubFaults:
    @pytest.mark.parametrize("route", ["issue", "graphql", "pulls", "comments_get"])
    def test_5xx_three_times_is_unavailable_and_never_a_verdict(self, route):
        gh, sb = _gh_for("proceed")
        gh.faults[route] = [502, 502, 502]
        out = _check(gh, sb)
        assert (out.status, out.error_code) == ("failed", "GITHUB_UNAVAILABLE")
        assert out.outcome is None and out.reason is None
        assert gh.writes() == []
        hits = [c for c in gh.calls if _route(c) == route]
        assert len(hits) == 3

    @pytest.mark.parametrize("route", ["issue", "graphql", "pulls", "comments_get"])
    def test_two_5xx_then_success_recovers(self, route):
        gh, sb = _gh_for("proceed")
        gh.faults[route] = [503, 503]
        assert _check(gh, sb).status == "proceed"

    def test_a_secondary_rate_limit_is_honoured(self):
        gh, sb = _gh_for("proceed")
        gh.faults["issue"] = [FakeResponse(403, {"message": "x"}, {"retry-after": "3"})]
        assert _check(gh, sb).status == "proceed"

    @pytest.mark.parametrize("route", ["issue", "graphql", "pulls", "comments_get"])
    def test_a_retry_after_of_60_is_honoured_not_abandoned(self, route):
        """DF-185-06: GitHub's common secondary-limit wait is retried within the budget."""
        gh, sb = _gh_for("proceed")
        gh.faults[route] = [FakeResponse(403, {"message": "x"}, {"retry-after": "60"})]
        assert _check(gh, sb).status == "proceed"
        assert len([c for c in gh.calls if _route(c) == route]) == 2

    @pytest.mark.parametrize("error_type", ["FORBIDDEN", "NOT_FOUND"])
    def test_permanent_graphql_errors_are_rejected_not_read_as_unlinked(self, error_type):
        """DF-185-05: a non-transient errors[] fails at once, never "no linked PR"."""
        gh, sb = _gh_for("proceed")
        gh.faults["graphql"] = [FakeResponse(200, {"data": None, "errors": [{"type": error_type}]})]
        out = _check(gh, sb)
        assert (out.status, out.error_code) == ("failed", "GITHUB_REQUEST_REJECTED")
        assert len(gh.graphql_calls()) == 1
        assert gh.writes() == []

    @pytest.mark.parametrize("error", [{"type": "INTERNAL"}, {"message": "Something went wrong"}])
    def test_transient_graphql_errors_retry_then_are_unavailable(self, error):
        """EC-14 / CT-33: errors[] with data: null retries, then GITHUB_UNAVAILABLE."""
        gh, sb = _gh_for("proceed")
        gh.faults["graphql"] = [FakeResponse(200, {"data": None, "errors": [error]})] * 3
        out = _check(gh, sb)
        assert (out.status, out.error_code) == ("failed", "GITHUB_UNAVAILABLE")
        assert len(gh.graphql_calls()) == 3
        assert out.reason is None and gh.writes() == []

    def test_a_transient_graphql_error_then_data_recovers(self):
        gh, sb = _gh_for("linked_pr")
        gh.faults["graphql"] = [FakeResponse(200, {"data": None, "errors": [{"type": "INTERNAL"}]})]
        assert _check(gh, sb).reason == "linked_pr"

    def test_a_missing_issue_in_graphql_is_rejected(self):
        gh, sb = _gh_for("proceed")
        gh.faults["graphql"] = [FakeResponse(200, {"data": {"repository": {"issue": None}}})]
        assert _check(gh, sb).error_code == "GITHUB_REQUEST_REJECTED"

    def test_a_read_4xx_is_rejected(self):
        gh, sb = _gh_for("proceed")
        gh.faults["pulls"] = [FakeResponse(403, {"message": "forbidden"})]
        assert _check(gh, sb).error_code == "GITHUB_REQUEST_REJECTED"

    def test_no_fault_summary_carries_a_secret(self):
        gh, sb = _gh_for("proceed")
        gh.faults["issue"] = [requests.ConnectionError(f"Bearer {TOKEN}")] * 3
        out = _check(gh, sb)
        assert out.error_code == "GITHUB_UNAVAILABLE"
        assert TOKEN not in out.summary


def _route(call) -> str:
    if call.path == "/graphql":
        return "graphql"
    if call.path.endswith("/pulls"):
        return "pulls"
    if call.path.endswith("/comments"):
        return "comments_get" if call.method == "GET" else "comments_post"
    return "issue"


# ---------------------------------------------------------------------------
# TC-185-21: a reply-post failure is logged; the outcome is unchanged
# ---------------------------------------------------------------------------


class TestReplyFailure:
    @pytest.mark.parametrize(
        "fault",
        [403, 422, 502, FakeResponse(429, {}, {"retry-after": "1"}), requests.Timeout("t")],
    )
    def test_the_outcome_stays_not_applicable(self, fault, caplog):
        gh, sb = _gh_for("closed")
        gh.faults["comments_post"] = [fault] * 3
        run = MagicMock()
        with caplog.at_level(logging.WARNING, logger="bug_fix.refusal"):
            out = _check(gh, sb, run=run)
        assert (out.status, out.outcome, out.reason) == ("succeeded", "not_applicable", "closed")
        assert out.reply == "failed"
        assert any("refusal reply" in r.getMessage() for r in caplog.records)
        run.warn.assert_called()
        assert "refusal reply" in run.warn.call_args.args[0]
        assert TOKEN not in caplog.text

    def test_a_reporter_failure_never_breaks_the_refusal(self):
        gh, sb = _gh_for("closed")
        gh.faults["comments_post"] = [422]
        run = MagicMock()
        run.warn.side_effect = RuntimeError("db down")
        run.info.side_effect = RuntimeError("db down")
        assert _check(gh, sb, run=run).reason == "closed"

    def test_a_posted_reply_records_a_run_event(self):
        gh, sb = _gh_for("closed")
        run = MagicMock()
        _check(gh, sb, run=run)
        assert any("refused: closed" in c.args[0] for c in run.info.call_args_list)


# ---------------------------------------------------------------------------
# TC-185-24: the commenter is never checked (D-91)
# ---------------------------------------------------------------------------


class TestNoCommenterCheck:
    @pytest.mark.parametrize("code", ("proceed", *REFUSAL_CODES))
    def test_no_permission_membership_or_user_call(self, code):
        gh, sb = _gh_for(code)
        gh.add_comment(ISSUE, "/bug-fix", app_id=None, user_type="User")
        _check(gh, sb, params=_params_for(code))
        for path in gh.paths():
            assert "/collaborators" not in path
            assert "/orgs/" not in path
            assert path != "/user"


# ---------------------------------------------------------------------------
# TC-185-25: labels have no effect (D-90)
# ---------------------------------------------------------------------------

LABEL_SETS = [
    (),
    ("status: in-progress",),
    ("status: blocked",),
    ("wontfix",),
    ("type: bug", "status: ready"),
    tuple(f"label-{i}" for i in range(100)),
]


class TestLabelsHaveNoEffect:
    @pytest.mark.parametrize("code", ("proceed", *REFUSAL_CODES))
    @pytest.mark.parametrize("labels", LABEL_SETS, ids=lambda s: f"{len(s)}-labels")
    def test_verdict_and_writes_equal_the_no_label_control(self, code, labels):
        control_gh, control_sb = _gh_for(code)
        control = _check(control_gh, control_sb, params=_params_for(code))
        gh, sb = _gh_for(code, labels=labels)
        out = _check(gh, sb, params=_params_for(code))
        assert (out.status, out.reason) == (control.status, control.reason)
        assert _write_templates(gh) == _write_templates(control_gh)
        assert not any("/labels" in p for p in gh.paths())
        for label in labels:
            assert all(label not in str(c.json) for c in gh.writes())


def test_github_double_path_is_on_the_api_host():
    gh, sb = _gh_for("proceed")
    _check(gh, sb)
    assert all(c.url.startswith(API + "/") for c in gh.calls)


# ---------------------------------------------------------------------------
# issues.py reads (6.5 edge cases)
# ---------------------------------------------------------------------------


class TestIssueReads:
    def _client(self, gh):
        from issues import IssuesClient

        return IssuesClient("o", "r", TOKEN, session=gh)

    def test_open_pulls_are_fetched_once_per_client(self):
        gh = FakeGitHub()
        gh.pulls.append(pull_payload(5, "issue/12-a"))
        client = self._client(gh)
        assert client.branch_prs(12) == [5]
        assert client.branch_prs(12) == [5]
        assert len([p for p in gh.paths("GET") if p.endswith("/pulls")]) == 1

    def test_a_non_json_issue_is_rejected(self):
        from issues import GitHubRequestRejected

        gh = FakeGitHub()
        gh.faults["issue"] = [FakeResponse(200, None)]
        with pytest.raises(GitHubRequestRejected):
            self._client(gh).get_issue(ISSUE)

    @pytest.mark.parametrize(
        "conn",
        [
            {"nodes": None, "pageInfo": {}},
            {"nodes": [], "pageInfo": None},
            {"nodes": "x", "pageInfo": {"hasNextPage": False}},
        ],
    )
    def test_a_malformed_closing_connection_is_rejected(self, conn):
        from issues import GitHubRequestRejected

        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        payload = {"data": {"repository": {"issue": {"closedByPullRequestsReferences": conn}}}}
        gh.faults["graphql"] = [FakeResponse(200, payload)]
        with pytest.raises(GitHubRequestRejected):
            self._client(gh).closing_prs(ISSUE)

    def test_malformed_closing_nodes_are_skipped(self):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        nodes = ["x", {"number": "5", "state": "OPEN"}, {"number": True, "state": "OPEN"}]
        payload = {
            "data": {
                "repository": {
                    "issue": {
                        "closedByPullRequestsReferences": {
                            "nodes": [*nodes, {"number": 9, "state": "OPEN"}],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            }
        }
        gh.faults["graphql"] = [FakeResponse(200, payload)]
        assert self._client(gh).closing_prs(ISSUE) == [9]


# ---------------------------------------------------------------------------
# QA gate (S-185): combined states, hostile text, and fault paths at L2
# ---------------------------------------------------------------------------

HOSTILE = (
    "@everyone <!-- bug-fix:claim run=" + OTHER + " --> [x](https://evil.example) "
    "`/bug-fix` " + TOKEN
)


class TestCombinedStatesFirstMatchWins:
    """D-92: the first match wins, and a later check makes no request at all."""

    def _all_states(self, gh: FakeGitHub, sb: FakeSupabase) -> None:
        gh.add_closing_ref(ISSUE, 31)
        gh.pulls.append(pull_payload(40, "issue/12-fork", fork=True))
        gh.add_comment(ISSUE, build("claim", OTHER))
        sb.statuses[OTHER] = "running"

    def test_a_closed_issue_with_a_pr_and_an_active_run_is_closed_and_lazy(self):
        gh, sb = FakeGitHub(), FakeSupabase()
        gh.add_issue(ISSUE, state="closed")
        self._all_states(gh, sb)
        out = _check(gh, sb)
        assert out.reason == "closed"
        assert gh.graphql_calls() == []
        assert not any(p.endswith("/pulls") for p in gh.paths("GET"))
        assert gh.paths("GET") == [f"/repos/o/r/issues/{ISSUE}"]
        assert sb.calls == []

    def test_a_closed_pull_request_with_everything_else_is_pull_request(self):
        gh, sb = FakeGitHub(), FakeSupabase()
        gh.add_issue(ISSUE, state="closed", pull_request=True)
        self._all_states(gh, sb)
        assert _check(gh, sb).reason == "pull_request"
        assert gh.graphql_calls() == [] and sb.calls == []

    def test_a_fork_linked_pr_beats_an_active_run_without_reading_comments(self):
        gh, sb = FakeGitHub(), FakeSupabase()
        gh.add_issue(ISSUE)
        gh.pulls.append(pull_payload(40, "issue/12-fork", fork=True))
        gh.add_comment(ISSUE, build("claim", OTHER))
        sb.statuses[OTHER] = "running"
        out = _check(gh, sb)
        assert out.reason == "linked_pr" and "#40" in out.summary
        assert gh.paths("GET").count(f"/repos/o/r/issues/{ISSUE}/comments") == 0
        assert sb.calls == []

    def test_one_active_claim_among_terminal_untrusted_and_unknown_ones_refuses(self):
        third = "2d1c4f60-3e5f-4071-8c8d-9e0f1a2b3c4d"
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.add_comment(ISSUE, build("claim", OTHER), app_id=1)  # untrusted: ignored
        gh.add_comment(ISSUE, build("claim", third))  # trusted, no v_runs row
        gh.add_comment(ISSUE, build("claim", RUN))  # this run's own claim
        gh.add_comment(ISSUE, build("claim", OTHER))  # trusted, running
        sb = FakeSupabase({OTHER: "running", RUN: "running"})
        assert _check(gh, sb).reason == "active_run"
        (call,) = sb.calls
        assert call["params"]["id"] == f"in.({third},{OTHER})"


class TestHostileTextNeverReachesTheReply:
    """D-104: the reply is fixed text. Issue, PR and comment text never enter it."""

    @pytest.mark.parametrize("code", REFUSAL_CODES)
    def test_the_reply_equals_the_benign_control(self, code):
        control_gh, control_sb = _gh_for(code)
        _check(control_gh, control_sb, params=_params_for(code))
        (control,) = control_gh.writes()

        gh, sb = _gh_for(code)
        gh.issues[ISSUE]["title"] = HOSTILE
        gh.issues[ISSUE]["body"] = HOSTILE
        gh.issues[ISSUE]["user"] = {"login": HOSTILE, "type": "User"}
        gh.add_comment(ISSUE, HOSTILE, app_id=None, user_type="User")
        _check(gh, sb, params=_params_for(code))
        (reply,) = gh.writes()
        assert reply.json["body"] == control.json["body"]

    def test_a_hostile_fork_branch_and_pr_title_never_reach_the_reply(self):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        pr = pull_payload(40, "issue/12-" + HOSTILE.replace(" ", "-"), fork=True)
        pr["title"] = HOSTILE
        pr["body"] = HOSTILE
        gh.pulls.append(pr)
        out = _check(gh)
        (reply,) = gh.writes()
        body = reply.json["body"]
        assert out.reason == "linked_pr"
        for needle in ("@everyone", "evil.example", "issue/12-", TOKEN, "bug-fix:claim"):
            assert needle not in body
        assert body.splitlines()[1] == (
            "Bug-fix didn't start: pull request #40 is already open for #12. "
            "Close it or finish it before asking for another fix."
        )


class TestReadFaultsAreNeverNoMatch:
    """D-67 at L2: timeouts, exhausted rate limits and partial GraphQL fail closed."""

    @pytest.mark.parametrize("route", ["issue", "graphql", "pulls", "comments_get"])
    def test_a_timeout_on_every_attempt_is_unavailable(self, route):
        gh, sb = _gh_for("proceed")
        gh.add_comment(ISSUE, build("claim", OTHER))
        sb.statuses[OTHER] = "succeeded"
        gh.faults[route] = [requests.Timeout(f"read timed out {TOKEN}")] * 3
        out = _check(gh, sb)
        assert (out.status, out.error_code) == ("failed", "GITHUB_UNAVAILABLE")
        assert out.reason is None and gh.writes() == []
        assert TOKEN not in out.summary

    @pytest.mark.parametrize("route", ["issue", "graphql", "pulls", "comments_get"])
    @pytest.mark.parametrize(
        "limited",
        [
            FakeResponse(429, {}, {"retry-after": "1"}),
            FakeResponse(403, {"message": "You have exceeded a secondary rate limit."}),
            FakeResponse(403, {}, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"}),
        ],
        ids=["429", "secondary-403", "primary-403"],
    )
    def test_an_exhausted_rate_limit_is_unavailable(self, route, limited):
        gh, sb = _gh_for("proceed")
        gh.add_comment(ISSUE, build("claim", OTHER))
        sb.statuses[OTHER] = "succeeded"
        gh.faults[route] = [limited] * 3
        out = _check(gh, sb)
        assert (out.status, out.error_code) == ("failed", "GITHUB_UNAVAILABLE")
        assert gh.writes() == []

    def test_a_graphql_rate_limit_payload_with_http_200_is_unavailable(self):
        gh, sb = _gh_for("proceed")
        limited = FakeResponse(200, {"errors": [{"type": "RATE_LIMITED", "message": "x"}]})
        gh.faults["graphql"] = [limited] * 3
        out = _check(gh, sb)
        assert (out.status, out.error_code) == ("failed", "GITHUB_UNAVAILABLE")
        assert gh.writes() == []

    @pytest.mark.parametrize("nodes", [[], [{"number": 31, "state": "OPEN"}]])
    def test_a_partial_graphql_response_is_rejected_not_read_as_data(self, nodes):
        conn = {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}
        partial = {
            "data": {"repository": {"issue": {"closedByPullRequestsReferences": conn}}},
            "errors": [{"type": "FORBIDDEN", "path": ["repository", "issue"], "message": "x"}],
        }
        gh, sb = _gh_for("proceed")
        gh.faults["graphql"] = [FakeResponse(200, partial)]
        out = _check(gh, sb)
        assert (out.status, out.error_code) == ("failed", "GITHUB_REQUEST_REJECTED")
        assert gh.writes() == []

    def test_a_supabase_timeout_is_unavailable_with_no_write(self):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.add_comment(ISSUE, build("claim", OTHER))
        sb = FakeSupabase()
        sb.fail = requests.Timeout(f"timed out {SB_KEY}")
        out = _check(gh, sb)
        assert (out.status, out.error_code) == ("failed", "SUPABASE_UNAVAILABLE")
        assert gh.writes() == [] and SB_KEY not in out.summary

    def test_a_comments_page_off_the_resource_is_rejected_not_truncated(self):
        gh = FakeGitHub(per_page_cap=1)
        gh.add_issue(ISSUE)
        gh.add_comment(ISSUE, "first")
        gh.add_comment(ISSUE, build("claim", OTHER))
        gh.next_link_override = f"{API}/repos/o/r/issues/{ISSUE + 1}/comments?page=2"
        sb = FakeSupabase({OTHER: "running"})
        out = _check(gh, sb)
        assert (out.status, out.error_code) == ("failed", "GITHUB_REQUEST_REJECTED")
        assert gh.writes() == []


class TestPageCapsAreFaults:
    """QA 1 (D-67): a page cap with more pages left fails closed, never "no match"."""

    def test_more_comment_pages_than_the_cap_is_unavailable(self):
        import issues

        gh = FakeGitHub(per_page_cap=1)
        gh.add_issue(ISSUE)
        for _ in range(issues._MAX_PAGES):
            gh.add_comment(ISSUE, "chatter")
        gh.add_comment(ISSUE, build("claim", OTHER))  # page 101: past the cap
        sb = FakeSupabase({OTHER: "running"})
        out = _check(gh, sb)
        assert (out.status, out.error_code) == ("failed", "GITHUB_UNAVAILABLE")
        assert out.reason is None and gh.writes() == []

    def test_more_open_pull_pages_than_the_cap_is_unavailable(self):
        import issues

        gh = FakeGitHub(per_page_cap=1)
        gh.add_issue(ISSUE)
        for n in range(1, issues._MAX_PAGES + 1):
            gh.pulls.append(pull_payload(n, f"other/{n}"))
        gh.pulls.append(pull_payload(999, "issue/12-late"))  # page 101
        out = _check(gh)
        assert (out.status, out.error_code) == ("failed", "GITHUB_UNAVAILABLE")
        assert gh.writes() == []

    def test_more_closing_reference_pages_than_the_cap_is_unavailable(self):
        import issues

        gh = FakeGitHub(graphql_page_size=1)
        gh.add_issue(ISSUE)
        for n in range(1, issues._MAX_GRAPHQL_PAGES + 1):
            gh.add_closing_ref(ISSUE, n, state="MERGED")
        gh.add_closing_ref(ISSUE, 500)  # open, but on page 21
        out = _check(gh)
        assert (out.status, out.error_code) == ("failed", "GITHUB_UNAVAILABLE")
        assert len(gh.graphql_calls()) == issues._MAX_GRAPHQL_PAGES
        assert gh.writes() == []

    def test_has_next_page_without_a_cursor_is_rejected_not_read_as_the_end(self):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        conn = {"nodes": [], "pageInfo": {"hasNextPage": True, "endCursor": None}}
        payload = {"data": {"repository": {"issue": {"closedByPullRequestsReferences": conn}}}}
        gh.faults["graphql"] = [FakeResponse(200, payload)]
        out = _check(gh)
        assert (out.status, out.error_code) == ("failed", "GITHUB_REQUEST_REJECTED")


class TestRedirectsAreFaults:
    """QA 3: no request follows a redirect, and a 3xx is never a success or "no match"."""

    @pytest.mark.parametrize("code", ("proceed", *REFUSAL_CODES))
    def test_every_github_and_supabase_call_disables_redirects(self, code):
        gh, sb = _gh_for(code)
        gh.add_comment(ISSUE, build("claim", OTHER))
        sb.statuses.setdefault(OTHER, "succeeded")
        _check(gh, sb, params=_params_for(code))
        assert gh.calls and all(c.allow_redirects is False for c in gh.calls)
        assert all(c["allow_redirects"] is False for c in sb.calls)

    @pytest.mark.parametrize("route", ["issue", "graphql", "pulls", "comments_get"])
    @pytest.mark.parametrize("status", [301, 302, 307, 308])
    def test_a_read_redirect_is_rejected_with_no_write(self, route, status):
        gh, sb = _gh_for("proceed")
        gh.add_comment(ISSUE, build("claim", OTHER))
        sb.statuses[OTHER] = "succeeded"
        gh.faults[route] = [redirect(status)]
        out = _check(gh, sb)
        assert (out.status, out.error_code) == ("failed", "GITHUB_REQUEST_REJECTED")
        assert out.reason is None and gh.writes() == []
        assert not any("evil.example" in c.url for c in gh.calls)

    @pytest.mark.parametrize("status", [301, 302, 307])
    def test_a_redirected_reply_post_is_not_reported_as_posted(self, status):
        gh, sb = _gh_for("closed")
        gh.faults["comments_post"] = [redirect(status)]
        run = MagicMock()
        out = _check(gh, sb, run=run)
        assert (out.status, out.reason) == ("succeeded", "closed")
        assert out.reply == "failed"
        assert gh.comments.get(ISSUE, []) == []
        run.warn.assert_called()

    def test_a_supabase_redirect_is_unavailable(self):
        gh = FakeGitHub()
        gh.add_issue(ISSUE)
        gh.add_comment(ISSUE, build("claim", OTHER))
        sb = FakeSupabase({OTHER: "running"})
        sb.fail = 302
        out = _check(gh, sb)
        assert (out.status, out.error_code) == ("failed", "SUPABASE_UNAVAILABLE")
