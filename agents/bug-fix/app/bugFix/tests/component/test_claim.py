"""L2 tests for the claim and the post-claim race check (S-188 AC1–AC5; D-54, D-81, D-93, D-94).

GitHub is the in-repo double :class:`FakeGitHub` (DF-186-02), so the claim
runs its real request sequence: the claim comment, the 👀 reaction, the
comment listing of the post-check and, on a lost race, the ``DELETE`` of this
run's own comment. Supabase (``v_runs``) is the PostgREST double from
``test_refusal``.

The claim:

1. posts the claim marker comment, then adds 👀 to ``trigger_comment_id``
   when present (a reaction 4xx is logged, not fatal);
2. runs the post-check: an open trusted claim with a lower comment id whose
   run isn't terminal means this run lost, so it deletes **only** its own
   comment and ends ``not_applicable``/``active_run`` with no board call;
3. confirms ownership on the Disposer only after a won race. A post-check
   Supabase failure ends ``failed``/``SUPABASE_UNAVAILABLE`` with no
   disposition (D-81).

No label or assignee is ever written (D-93, FR-8).

TC-188-02…04, 08…10, 12…15; the 9.5 edge cases.
"""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from claim import CLAIM_LINE, Claimer, ClaimOutcome, build_claim_body, claim_issue
from disposition import Diagnosis, Disposer
from issues import IssuesClient
from markers import build, parse_block
from refusal import RunStatusReader, run_refusal_checks
from run_link import RunLink
from scrubber import SecretSet
from tests.component.fake_github import APP_ID, TOKEN, FakeGitHub, FakeResponse
from tests.component.test_refusal import SB_KEY, SB_URL, FakeSupabase, _token

RUN = "0b9a2f4e-1c3d-4e5f-8a6b-7c8d9e0f1a2b"
OTHER = "1c0b3e5f-2d4e-4f60-9b7c-8d9e0f1a2b3c"
THIRD = "2d1c4f60-3e5f-4071-8c8d-9e0f1a2b3c4d"
ISSUE = 12
TRIGGER = 9_001
OTHER_TRIGGER = 9_002
PANEL = "https://dt-agent-fleet-panel.fly.dev"
LINK = RunLink(PANEL, RUN)
LABELS = ("type: bug", "status: ready")


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class TimelineSupabase(FakeSupabase):
    """The ``v_runs`` double, also writing each read to a shared timeline."""

    def __init__(self, statuses=None, timeline: list[str] | None = None) -> None:
        super().__init__(statuses)
        self.timeline = timeline if timeline is not None else []

    def get(self, url, **kwargs) -> FakeResponse:
        self.timeline.append("v_runs")
        return super().get(url, **kwargs)


def _secrets() -> SecretSet:
    s = SecretSet()
    s.add("GITHUB_INSTALLATION_TOKEN", TOKEN)
    s.add("SUPABASE_SERVICE_ROLE_KEY", SB_KEY)
    return s


def _gh() -> FakeGitHub:
    gh = FakeGitHub()
    gh.add_issue(ISSUE, labels=LABELS)
    return gh


def _client(gh: FakeGitHub) -> IssuesClient:
    return IssuesClient("o", "r", TOKEN, session=gh)


def _disposer(gh: FakeGitHub, run_id: str = RUN, trigger: int | None = TRIGGER, board=None):
    return Disposer(
        client=_client(gh),
        issue_number=ISSUE,
        run_id=run_id,
        app_id=APP_ID,
        trigger_comment_id=trigger,
        secrets=_secrets(),
        run_link=LINK,
        panel_origin=LINK.origin,
        board_ready=board,
    )


def _claimer(
    gh: FakeGitHub,
    sb: FakeSupabase,
    *,
    run_id: str = RUN,
    trigger: int | None = TRIGGER,
    run: Any = None,
    disposer: Disposer | None = None,
    board: Any = None,
    link: str | None = LINK,
) -> Claimer:
    return Claimer(
        client=_client(gh),
        issue_number=ISSUE,
        run_id=run_id,
        app_id=APP_ID,
        trigger_comment_id=trigger,
        run_status=RunStatusReader(SB_URL, SB_KEY, session=sb),
        run=run,
        run_link=link,
        panel_origin=PANEL,
        secrets=_secrets(),
        disposer=disposer,
        board_in_progress=board,
    )


def _claim(gh: FakeGitHub, sb: FakeSupabase | None = None, **kw) -> ClaimOutcome:
    return _claimer(gh, sb if sb is not None else FakeSupabase(), **kw).claim()


def _writes(gh: FakeGitHub) -> list[tuple[str, str]]:
    return [(c.method, c.path) for c in gh.writes()]


def _claim_comments(gh: FakeGitHub, run_id: str) -> list[dict]:
    return [
        c
        for c in gh.comments.get(ISSUE, [])
        if any(m.kind == "claim" and m.run_id == run_id for m in parse_block(c["body"]))
    ]


def _no_label_or_assignee_call(gh: FakeGitHub) -> None:
    for path in gh.paths():
        assert "/labels" not in path, path
        assert "/assignees" not in path, path


def _seed_claim(gh: FakeGitHub, run_id: str, *, trigger: int | None = None) -> dict:
    comment = gh.add_comment(ISSUE, build("claim", run_id) + "\n🔧 Bug-fix run is working.")
    if trigger is not None:
        gh.reactions.append((trigger, "eyes"))
    return comment


COMMENTS = f"/repos/o/r/issues/{ISSUE}/comments"
EYES = f"/repos/o/r/issues/comments/{TRIGGER}/reactions"


# ---------------------------------------------------------------------------
# AC1: the happy claim (TC-188-02, TC-188-03)
# ---------------------------------------------------------------------------


class TestHappyClaim:
    def test_the_marker_comment_comes_first_then_eyes(self):
        gh = _gh()
        out = _claim(gh)
        assert out.status == "owned"
        assert _writes(gh) == [("POST", COMMENTS), ("POST", EYES)]
        eyes = [c for c in gh.calls if c.path == EYES]
        assert eyes[0].json == {"content": "eyes"}
        assert gh.reactions == [(TRIGGER, "eyes")]
        _no_label_or_assignee_call(gh)

    def test_the_post_check_lists_the_comments_after_both_writes(self):
        gh = _gh()
        _claim(gh)
        sequence = [(c.method, c.path) for c in gh.calls]
        assert sequence == [("POST", COMMENTS), ("POST", EYES), ("GET", COMMENTS)]

    def test_line_1_is_the_claim_marker_and_the_body_has_the_run_link(self):
        gh = _gh()
        out = _claim(gh)
        (comment,) = gh.comments[ISSUE]
        assert comment["id"] == out.comment_id
        lines = comment["body"].split("\n")
        assert lines[0] == build("claim", RUN)
        assert parse_block(comment["body"])[0].run_id == RUN
        assert lines[1] == CLAIM_LINE.format(run=LINK)
        assert LINK in comment["body"]

    def test_the_body_is_exactly_the_marker_and_one_line(self):
        assert build_claim_body(RUN, LINK, panel_origin=PANEL) == (
            f"{build('claim', RUN)}\n🔧 Bug-fix run {LINK} is working on this issue."
        )

    @pytest.mark.parametrize(
        "link",
        [None, "", "http://panel.example/runs/x", "https://a b", "javascript:alert(1)"],
        ids=["none", "empty", "http", "space", "scheme"],
    )
    def test_an_unusable_link_falls_back_to_the_run_id(self, link):
        body = build_claim_body(RUN, link)
        assert body.split("\n")[1] == CLAIM_LINE.format(run=f"`{RUN}`")

    def test_the_run_id_is_canonical(self):
        body = build_claim_body(RUN.upper(), LINK)
        assert parse_block(body)[0].run_id == RUN

    def test_a_won_race_confirms_ownership_on_the_disposer(self):
        gh = _gh()
        disposer = _disposer(gh)
        out = _claim(gh, disposer=disposer)
        assert out.owned
        assert disposer.ownership_confirmed

    def test_an_owned_claim_reports_nothing(self):
        gh = _gh()
        run = MagicMock()
        out = _claim(gh, run=run)
        out.report(run)
        run.succeed.assert_not_called()
        run.fail.assert_not_called()
        assert out.result() == {}

    def test_claim_issue_is_the_one_call_form(self):
        gh = _gh()
        out = claim_issue(
            client=_client(gh),
            issue_number=ISSUE,
            run_id=RUN,
            app_id=APP_ID,
            trigger_comment_id=TRIGGER,
            run_status=RunStatusReader(SB_URL, SB_KEY, session=FakeSupabase()),
            run_link=LINK,
            panel_origin=LINK.origin,
        )
        assert out.status == "owned"
        assert _writes(gh) == [("POST", COMMENTS), ("POST", EYES)]

    def test_no_v_runs_read_without_an_earlier_claim(self):
        gh = _gh()
        sb = FakeSupabase()
        _claim(gh, sb)
        assert sb.calls == []


# ---------------------------------------------------------------------------
# AC4: the PRD AC-3 end state (TC-188-08)
# ---------------------------------------------------------------------------


def test_the_end_state_matches_prd_ac_3():
    gh = _gh()
    before = copy.deepcopy(gh.issues[ISSUE])
    out = _claim(gh)
    assert out.owned
    assert gh.reactions == [(TRIGGER, "eyes")]
    (comment,) = _claim_comments(gh, RUN)
    assert comment["body"].startswith(build("claim", RUN) + "\n")
    assert LINK in comment["body"]
    # Labels and assignees byte-equal to their pre-run state, and no call
    # that could have changed them.
    assert gh.issues[ISSUE] == before
    _no_label_or_assignee_call(gh)


# ---------------------------------------------------------------------------
# AC1, AC-19: a manual invoke makes no reaction call (TC-188-15)
# ---------------------------------------------------------------------------


class TestManualInvoke:
    def test_no_trigger_comment_means_no_reaction_call(self):
        gh = _gh()
        out = _claim(gh, trigger=None)
        assert out.owned
        assert out.reaction == "skipped"
        assert _writes(gh) == [("POST", COMMENTS)]
        assert not any("/reactions" in p for p in gh.paths())

    def test_no_reaction_on_the_later_disposition_either(self):
        gh = _gh()
        disposer = _disposer(gh, trigger=None)
        _claim(gh, trigger=None, disposer=disposer)
        assert disposer.dispose(Diagnosis(why="gave up", tried="t")).status == "applied"
        assert not any("/reactions" in p for p in gh.paths())
        _no_label_or_assignee_call(gh)


# ---------------------------------------------------------------------------
# AC2: a lost race (TC-188-04, TC-188-14)
# ---------------------------------------------------------------------------


class TestLostRace:
    def _lost(self, *, run=None, board=None, disposer=None, status="running"):
        gh = _gh()
        theirs = _seed_claim(gh, OTHER, trigger=OTHER_TRIGGER)
        sb = FakeSupabase({OTHER: status})
        out = _claim(gh, sb, run=run, board=board, disposer=disposer)
        return gh, sb, theirs, out

    @pytest.mark.parametrize("status", ["queued", "running"])
    def test_only_this_runs_comment_is_deleted(self, status):
        gh, _sb, theirs, out = self._lost(status=status)
        assert out.status == "lost"
        assert out.winner == OTHER
        assert out.withdrawal == "deleted"
        assert gh.deleted == [out.comment_id]
        assert _writes(gh) == [
            ("POST", COMMENTS),
            ("POST", EYES),
            ("DELETE", f"/repos/o/r/issues/comments/{out.comment_id}"),
        ]
        assert gh.comments[ISSUE] == [theirs]

    def test_the_run_ends_not_applicable_active_run_naming_the_winner(self):
        run = MagicMock()
        _gh_, _sb, _theirs, out = self._lost(run=run)
        out.report(run)
        run.succeed.assert_called_once()
        args, kwargs = run.succeed.call_args
        assert args == ("not_applicable",)
        assert kwargs["result"]["reason"] == "active_run"
        assert OTHER in kwargs["result"]["summary"]
        assert "board" not in kwargs["result"]
        run.fail.assert_not_called()

    def test_no_board_call_and_no_projects_request(self):
        board = MagicMock()
        gh, _sb, _theirs, _out = self._lost(board=board)
        board.assert_not_called()
        assert gh.projects_calls() == []

    def test_ownership_is_never_confirmed_so_nothing_is_disposed(self):
        gh = _gh()
        _seed_claim(gh, OTHER)
        board_ready = MagicMock()
        disposer = _disposer(gh, board=board_ready)
        out = _claim(gh, FakeSupabase({OTHER: "running"}), disposer=disposer)
        assert out.status == "lost"
        assert not disposer.ownership_confirmed
        writes = len(gh.writes())
        assert disposer.dispose(Diagnosis(why="x", tried="y")).status == "not_owned"
        assert disposer.backstop_action() is None
        assert len(gh.writes()) == writes
        board_ready.assert_not_called()

    def test_the_losers_eyes_stays_and_it_posts_no_reply(self):
        # Pinned per spec §8.6 as written; recorded as DF-32.
        gh, _sb, _theirs, _out = self._lost()
        assert (TRIGGER, "eyes") in gh.reactions
        assert not any(
            m.kind == "refusal" for c in gh.comments[ISSUE] for m in parse_block(c["body"])
        )

    def test_a_delete_404_is_logged_and_the_run_still_withdraws(self):
        gh = _gh()
        _seed_claim(gh, OTHER)
        gh.faults["comment_delete"] = [404]
        run = MagicMock()
        out = _claim(gh, FakeSupabase({OTHER: "running"}), run=run)
        assert (out.status, out.withdrawal) == ("lost", "already_gone")
        assert any("already gone" in str(c.args[0]) for c in run.warn.call_args_list)

    @pytest.mark.parametrize(
        ("faults", "code"),
        [([503, 503, 503], "GITHUB_UNAVAILABLE"), ([422], "GITHUB_REQUEST_REJECTED")],
    )
    def test_another_delete_fault_ends_failed_with_no_disposition(self, faults, code):
        gh = _gh()
        _seed_claim(gh, OTHER)
        gh.faults["comment_delete"] = list(faults)
        disposer = _disposer(gh)
        board = MagicMock()
        run = MagicMock()
        out = _claim(gh, FakeSupabase({OTHER: "running"}), disposer=disposer, board=board, run=run)
        assert (out.status, out.error_code) == ("failed", code)
        assert not disposer.ownership_confirmed
        board.assert_not_called()
        out.report(run)
        assert run.fail.call_args.args[0] == code
        assert TOKEN not in out.summary


# ---------------------------------------------------------------------------
# AC5, PRD AC-20: two runs a moment apart (TC-188-13)
# ---------------------------------------------------------------------------


class TestTwoRuns:
    @pytest.mark.parametrize("check_order", ["a_first", "b_first"])
    def test_one_owner_and_one_withdrawal(self, check_order):
        gh = _gh()
        sb = FakeSupabase({RUN: "running", OTHER: "running"})
        board_a, board_b = MagicMock(), MagicMock()
        dis_a, dis_b = _disposer(gh, RUN), _disposer(gh, OTHER, OTHER_TRIGGER)
        a = _claimer(gh, sb, run_id=RUN, trigger=TRIGGER, disposer=dis_a, board=board_a)
        b = _claimer(gh, sb, run_id=OTHER, trigger=OTHER_TRIGGER, disposer=dis_b, board=board_b)
        # Interleaved: both claim before either post-checks.
        posted_a = a.post()
        posted_b = b.post()
        assert posted_a.status == posted_b.status == "posted"
        assert posted_a.comment_id < posted_b.comment_id
        if check_order == "a_first":
            out_a, out_b = a.post_check(), b.post_check()
        else:
            out_b, out_a = b.post_check(), a.post_check()
        assert (out_a.status, out_b.status) == ("owned", "lost")
        assert out_b.winner == RUN
        assert dis_a.ownership_confirmed and not dis_b.ownership_confirmed
        board_a.assert_called_once()
        board_b.assert_not_called()
        # The loser deleted only its own comment; the winner's stays.
        assert gh.deleted == [posted_b.comment_id]
        assert [c["id"] for c in gh.comments[ISSUE]] == [posted_a.comment_id]
        # Each run reacted on its own trigger comment, and the loser's 👀
        # stays (DF-32, pinned).
        assert sorted(gh.reactions) == [(TRIGGER, "eyes"), (OTHER_TRIGGER, "eyes")]
        assert gh.projects_calls() == []
        _no_label_or_assignee_call(gh)

    def test_a_shared_trigger_comment_gets_one_eyes_per_run_request(self):
        gh = _gh()
        sb = FakeSupabase({RUN: "running", OTHER: "running"})
        a = _claimer(gh, sb, run_id=RUN, trigger=TRIGGER)
        b = _claimer(gh, sb, run_id=OTHER, trigger=TRIGGER)
        a.post()
        b.post()
        assert (b.post_check().status, a.post_check().status) == ("lost", "owned")


# ---------------------------------------------------------------------------
# A crash after the comment; AC-24 (TC-188-10, D-94)
# ---------------------------------------------------------------------------


class TestCrashAfterTheComment:
    def _refusal(self, gh: FakeGitHub, sb: FakeSupabase, run_id: str):
        return run_refusal_checks(
            run_id=run_id,
            owner="o",
            repo="r",
            raw_params={"issue_number": ISSUE, "trigger_comment_id": TRIGGER},
            resolve_token=_token,
            run_status=RunStatusReader(SB_URL, SB_KEY, session=sb),
            session=gh,
            run_link=LINK,
            panel_origin=LINK.origin,
            secrets=_secrets(),
        )

    def test_blocked_while_non_terminal_then_a_new_run_proceeds(self):
        gh = _gh()
        crashed = _seed_claim(gh, OTHER, trigger=OTHER_TRIGGER)
        sb = FakeSupabase({OTHER: "running"})

        # While the crashed run is non-terminal, a new /bug-fix (run THIRD)
        # is refused.
        refused = self._refusal(gh, sb, THIRD)
        assert (refused.status, refused.reason) == ("succeeded", "active_run")

        # The reaper marks it timed_out: the refusal check ignores the orphan,
        # and the new run's post-check does too, so it owns the issue.
        sb.statuses[OTHER] = "timed_out"
        checked = self._refusal(gh, sb, RUN)
        assert checked.proceed
        out = _claim(gh, sb)
        assert out.owned
        # The orphaned comment and its 👀 stay as history; no sweep exists.
        assert crashed in gh.comments[ISSUE]
        assert (OTHER_TRIGGER, "eyes") in gh.reactions
        assert gh.deleted == []

    def test_a_deleted_run_row_counts_as_finished_with_a_run_event(self):
        gh = _gh()
        _seed_claim(gh, OTHER)
        run = MagicMock()
        out = _claim(gh, FakeSupabase({}), run=run)
        assert out.owned
        warned = [str(c.args[0]) for c in run.warn.call_args_list]
        assert any(OTHER in w and "no v_runs row" in w for w in warned)


# ---------------------------------------------------------------------------
# AC3: the ownership gate on a post-check failure (TC-188-12, D-81)
# ---------------------------------------------------------------------------


class TestPostCheckFailure:
    @pytest.mark.parametrize(
        "fail",
        [503, 401, requests.ConnectionError("down"), requests.Timeout("slow")],
        ids=["503", "401", "connection", "timeout"],
    )
    def test_supabase_unavailable_keeps_the_comment_and_disposes_nothing(self, fail):
        gh = _gh()
        _seed_claim(gh, OTHER)
        sb = FakeSupabase({OTHER: "running"})
        sb.fail = fail
        board_ready, board_progress = MagicMock(), MagicMock()
        disposer = _disposer(gh, board=board_ready)
        run = MagicMock()
        out = _claim(gh, sb, disposer=disposer, board=board_progress, run=run)

        assert (out.status, out.error_code) == ("failed", "SUPABASE_UNAVAILABLE")
        assert len(_claim_comments(gh, RUN)) == 1  # the claim comment stays
        assert gh.deleted == []
        assert not disposer.ownership_confirmed
        # Nothing else, even from the finally path or the backstop.
        writes = len(gh.writes())
        assert disposer.dispose(Diagnosis(why="x", tried="y")).status == "not_owned"
        assert disposer.backstop_action() is None
        assert len(gh.writes()) == writes
        assert not any(content == "confused" for _cid, content in gh.reactions)
        board_ready.assert_not_called()
        board_progress.assert_not_called()
        assert gh.projects_calls() == []

        out.report(run)
        assert run.fail.call_args.args[0] == "SUPABASE_UNAVAILABLE"
        run.succeed.assert_not_called()
        assert SB_KEY not in out.summary

    def test_an_unknown_status_fails_closed_with_a_run_event(self):
        gh = _gh()
        _seed_claim(gh, OTHER)
        run = MagicMock()
        out = _claim(gh, FakeSupabase({OTHER: "paused"}), run=run)
        assert (out.status, out.error_code) == ("failed", "SUPABASE_UNAVAILABLE")
        assert any("unknown effective_status" in str(c.args[0]) for c in run.warn.call_args_list)

    @pytest.mark.parametrize(
        ("faults", "code"),
        [([503, 503, 503], "GITHUB_UNAVAILABLE"), ([403], "GITHUB_REQUEST_REJECTED")],
    )
    def test_a_listing_fault_keeps_the_comment_and_confirms_nothing(self, faults, code):
        gh = _gh()
        gh.faults["comments_get"] = list(faults)
        disposer = _disposer(gh)
        out = _claim(gh, disposer=disposer)
        assert (out.status, out.error_code) == ("failed", code)
        assert len(_claim_comments(gh, RUN)) == 1
        assert gh.deleted == []
        assert not disposer.ownership_confirmed


# ---------------------------------------------------------------------------
# Board only after confirmed ownership (TC-188-14, D-103)
# ---------------------------------------------------------------------------


class TestBoardGate:
    def test_in_progress_comes_strictly_after_the_post_check_read(self):
        gh = _gh()
        _seed_claim(gh, OTHER)
        timeline: list[str] = []
        sb = TimelineSupabase({OTHER: "succeeded"}, timeline)
        out = _claim(gh, sb, board=lambda: timeline.append("board"))
        assert out.owned and out.board == "ok"
        assert timeline == ["v_runs", "board"]

    def test_in_progress_follows_confirmed_ownership(self):
        gh = _gh()
        disposer = _disposer(gh)
        seen: list[bool] = []
        _claim(gh, disposer=disposer, board=lambda: seen.append(disposer.ownership_confirmed))
        assert seen == [True]

    def test_a_board_failure_is_logged_and_the_claim_stands(self):
        gh = _gh()
        run = MagicMock()

        def boom():
            raise RuntimeError(f"board down {TOKEN}")

        out = _claim(gh, run=run, board=boom)
        assert out.owned and out.board == "failed"
        messages = " ".join(str(c.args[0]) for c in run.warn.call_args_list)
        assert "board" in messages
        assert TOKEN not in messages

    def test_no_board_callback_is_skipped(self):
        assert _claim(_gh()).board == "skipped"


# ---------------------------------------------------------------------------
# Faults on the claim itself
# ---------------------------------------------------------------------------


class TestClaimFaults:
    @pytest.mark.parametrize(
        ("faults", "code"),
        [([503], "GITHUB_UNAVAILABLE"), ([422], "GITHUB_REQUEST_REJECTED")],
    )
    def test_a_failed_claim_post_writes_nothing_else(self, faults, code):
        gh = _gh()
        gh.faults["comments_post"] = list(faults)
        disposer = _disposer(gh)
        run = MagicMock()
        out = _claim(gh, disposer=disposer, run=run)
        assert (out.status, out.error_code) == ("failed", code)
        assert out.comment_id is None
        assert gh.reactions == []
        assert [c.method for c in gh.calls] == ["POST"]
        assert not disposer.ownership_confirmed
        out.report(run)
        assert run.fail.call_args.args[0] == code
        assert TOKEN not in out.summary

    def test_a_claim_answer_with_no_id_is_rejected_before_the_reaction(self):
        gh = _gh()
        gh.faults["comments_post"] = [FakeResponse(201, None)]
        out = _claim(gh)
        assert (out.status, out.error_code) == ("failed", "GITHUB_REQUEST_REJECTED")
        assert gh.reactions == []

    def test_post_check_before_post_is_a_programming_error(self):
        with pytest.raises(RuntimeError):
            _claimer(_gh(), FakeSupabase()).post_check()

    def test_a_second_post_is_a_programming_error(self):
        c = _claimer(_gh(), FakeSupabase())
        c.post()
        with pytest.raises(RuntimeError):
            c.post()


# ---------------------------------------------------------------------------
# 9.5 edge cases: same second, the other run terminal, a reaction 422
# ---------------------------------------------------------------------------


class TestEdges:
    def test_two_comments_in_the_same_second_are_ordered_by_id(self):
        gh = _gh()
        stamp = "2026-10-24T12:00:00Z"
        sb = FakeSupabase({RUN: "running", OTHER: "running"})
        a = _claimer(gh, sb, run_id=RUN)
        b = _claimer(gh, sb, run_id=OTHER, trigger=OTHER_TRIGGER)
        a.post()
        b.post()
        for comment in gh.comments[ISSUE]:
            comment["created_at"] = stamp
        # Reverse the listing order: only the integer id may decide.
        gh.comments[ISSUE].reverse()
        assert (b.post_check().status, a.post_check().status) == ("lost", "owned")

    @pytest.mark.parametrize("status", ["succeeded", "failed", "timed_out", "canceled"])
    def test_the_other_run_already_terminal_means_this_run_owns(self, status):
        gh = _gh()
        theirs = _seed_claim(gh, OTHER)
        out = _claim(gh, FakeSupabase({OTHER: status}))
        assert out.owned
        assert gh.deleted == []
        assert theirs in gh.comments[ISSUE]

    @pytest.mark.parametrize("status", [404, 422])
    def test_a_reaction_4xx_is_logged_and_not_fatal(self, status):
        gh = _gh()
        gh.faults["reaction"] = [status]
        run = MagicMock()
        out = _claim(gh, run=run)
        assert out.owned
        assert out.reaction == "failed"
        assert any(
            "eyes reaction failed" in str(c.args[0]) and str(status) in str(c.args[0])
            for c in run.warn.call_args_list
        )

    def test_an_exhausted_reaction_5xx_is_logged_and_not_fatal(self):
        gh = _gh()
        gh.faults["reaction"] = [503]
        run = MagicMock()
        out = _claim(gh, run=run)
        assert out.owned and out.reaction == "failed"
        assert run.warn.called


# ---------------------------------------------------------------------------
# FR-8: no label or assignee request on any path (TC-188-09)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["owned", "lost", "post_check_failed", "manual", "disposed"])
def test_no_label_or_assignee_request_on_any_path(path):
    gh = _gh()
    sb = FakeSupabase({OTHER: "running"})
    if path == "lost":
        _seed_claim(gh, OTHER)
    elif path == "post_check_failed":
        _seed_claim(gh, OTHER)
        sb.fail = 503
    disposer = _disposer(gh)
    _claim(gh, sb, trigger=None if path == "manual" else TRIGGER, disposer=disposer)
    if path == "disposed":
        disposer.dispose(Diagnosis(why="x", tried="y"))
    _no_label_or_assignee_call(gh)
    assert {c.method for c in gh.writes()} <= {"POST", "DELETE"}


def test_a_failing_run_reporter_never_changes_the_outcome():
    gh = _gh()
    _seed_claim(gh, OTHER)
    run = MagicMock()
    run.info.side_effect = RuntimeError("reporter down")
    run.warn.side_effect = RuntimeError("reporter down")
    out = _claim(gh, FakeSupabase({OTHER: "running"}), run=run)
    assert (out.status, out.withdrawal) == ("lost", "deleted")
