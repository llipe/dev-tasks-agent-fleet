"""L2 gap tests for the claim and the post-claim race check (S-188 QA pass).

Closes gaps the story's own suite left open:

- a three-way race in every post-check order: one owner, two withdrawals,
  each deleting only its own comment;
- this run's marker listed twice: the run never loses to itself, and a lost
  race deletes only the comment id the claim ``POST`` returned;
- an earlier claim closed by ``pr``, ``disposition`` or ``refusal`` at L2;
- a 429 or a redirect on the post-check listing or on the ``DELETE``: never
  ``lost``/``not_applicable``, never an ownership confirmation;
- ``confirm_ownership`` runs only after the listing and the ``v_runs`` read;
- a token in a transport error never reaches a log line, a run event or the
  outcome summary;
- the ``PANEL_BASE_URL`` run link reaches the claim body unchanged.

GitHub is :class:`FakeGitHub`; ``v_runs`` is the PostgREST double from
``test_refusal``.
"""

from __future__ import annotations

import itertools
import logging
from unittest.mock import MagicMock

import pytest
import requests

from claim import CLAIM_LINE, build_claim_body
from config import load_config
from markers import build, parse_block
from tests.component.fake_github import TOKEN, FakeResponse, redirect
from tests.component.test_claim import (
    ISSUE,
    LINK,
    OTHER,
    OTHER_TRIGGER,
    RUN,
    THIRD,
    TRIGGER,
    TimelineSupabase,
    _claim,
    _claim_comments,
    _claimer,
    _gh,
    _seed_claim,
)
from tests.component.test_refusal import SB_KEY, FakeSupabase

THIRD_TRIGGER = 9_003


def _disposer_spy() -> MagicMock:
    spy = MagicMock()
    spy.ownership_confirmed = False
    return spy


# ---------------------------------------------------------------------------
# Three-way race (D-54): one owner, whatever the post-check order
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("order", list(itertools.permutations("abc")), ids="".join)
def test_a_three_way_race_has_one_owner_in_every_check_order(order):
    gh = _gh()
    sb = FakeSupabase({RUN: "running", OTHER: "running", THIRD: "running"})
    dis = {k: _disposer_spy() for k in "abc"}
    boards = {k: MagicMock() for k in "abc"}
    runs = {"a": (RUN, TRIGGER), "b": (OTHER, OTHER_TRIGGER), "c": (THIRD, THIRD_TRIGGER)}
    claimers = {
        k: _claimer(gh, sb, run_id=rid, trigger=trig, disposer=dis[k], board=boards[k])
        for k, (rid, trig) in runs.items()
    }
    posted = {k: claimers[k].post() for k in "abc"}
    assert posted["a"].comment_id < posted["b"].comment_id < posted["c"].comment_id

    out = {k: claimers[k].post_check() for k in order}

    assert [out[k].status for k in "abc"] == ["owned", "lost", "lost"]
    # The earliest claim wins: a later claim never makes it lose.
    assert out["b"].winner == out["c"].winner == RUN
    dis["a"].confirm_ownership.assert_called_once()
    dis["b"].confirm_ownership.assert_not_called()
    dis["c"].confirm_ownership.assert_not_called()
    boards["a"].assert_called_once()
    boards["b"].assert_not_called()
    boards["c"].assert_not_called()
    # Each loser deleted only its own comment; the winner's stays.
    assert sorted(gh.deleted) == sorted([posted["b"].comment_id, posted["c"].comment_id])
    assert [c["id"] for c in gh.comments[ISSUE]] == [posted["a"].comment_id]


def test_a_middle_claim_closed_by_a_disposition_still_loses_to_the_first():
    # A (active) < B (closed by its own disposition) < this run.
    gh = _gh()
    _seed_claim(gh, OTHER)
    _seed_claim(gh, THIRD)
    gh.add_comment(ISSUE, build("disposition", THIRD) + "\ndone")
    out = _claim(gh, FakeSupabase({OTHER: "running", THIRD: "running"}))
    assert (out.status, out.winner) == ("lost", OTHER)


# ---------------------------------------------------------------------------
# This run's marker listed twice
# ---------------------------------------------------------------------------


class TestOwnMarkerTwice:
    def test_an_earlier_copy_of_this_runs_claim_never_makes_it_lose(self):
        gh = _gh()
        dup = _seed_claim(gh, RUN)
        sb = FakeSupabase({RUN: "running"})
        out = _claim(gh, sb)
        assert out.owned
        assert gh.deleted == []
        assert dup in gh.comments[ISSUE]
        assert sb.calls == []  # its own run is never even looked up

    def test_a_lost_race_deletes_only_the_id_the_post_returned(self):
        gh = _gh()
        dup = _seed_claim(gh, RUN)
        theirs = _seed_claim(gh, OTHER)
        out = _claim(gh, FakeSupabase({RUN: "running", OTHER: "running"}))
        assert (out.status, out.winner) == ("lost", OTHER)
        assert gh.deleted == [out.comment_id]
        assert dup["id"] != out.comment_id
        assert gh.comments[ISSUE] == [dup, theirs]


# ---------------------------------------------------------------------------
# An earlier claim closed by each closing kind (DF-33), at L2
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "closer",
    [build("pr", OTHER), build("disposition", OTHER), build("refusal", OTHER, "repo_gate")],
    ids=["pr", "disposition", "refusal"],
)
def test_an_earlier_claim_closed_by_a_trusted_marker_does_not_win(closer):
    gh = _gh()
    theirs = _seed_claim(gh, OTHER)
    gh.add_comment(ISSUE, closer + "\nclosed")
    sb = FakeSupabase({OTHER: "running"})
    out = _claim(gh, sb)
    assert out.owned
    assert sb.calls == []  # a closed claim is never looked up
    assert gh.deleted == []
    assert theirs in gh.comments[ISSUE]


# ---------------------------------------------------------------------------
# Faults on the post-check listing and on the DELETE: 429 and redirects
# ---------------------------------------------------------------------------


def _assert_failed_and_unowned(gh, out, run, disposer, board, code):
    assert (out.status, out.error_code) == ("failed", code)
    assert out.result() == {}
    disposer.confirm_ownership.assert_not_called()
    board.assert_not_called()
    assert gh.projects_calls() == []
    assert not any("evil.example" in c.url for c in gh.calls)
    out.report(run)
    assert run.fail.call_args.args[0] == code
    run.succeed.assert_not_called()


@pytest.mark.parametrize(
    ("faults", "code"),
    [
        ([429, 429, 429], "GITHUB_UNAVAILABLE"),
        ([redirect(301)], "GITHUB_REQUEST_REJECTED"),
        ([redirect(302)], "GITHUB_REQUEST_REJECTED"),
        ([redirect(307)], "GITHUB_REQUEST_REJECTED"),
        ([redirect(308)], "GITHUB_REQUEST_REJECTED"),
    ],
    ids=["429", "301", "302", "307", "308"],
)
def test_a_listing_429_or_redirect_never_loses_and_never_owns(faults, code):
    gh = _gh()
    _seed_claim(gh, OTHER)  # a successful listing would make this run lose
    gh.faults["comments_get"] = list(faults)
    disposer, board, run = _disposer_spy(), MagicMock(), MagicMock()
    out = _claim(gh, FakeSupabase({OTHER: "running"}), disposer=disposer, board=board, run=run)
    _assert_failed_and_unowned(gh, out, run, disposer, board, code)
    assert len(_claim_comments(gh, RUN)) == 1  # the claim stays
    assert gh.deleted == []


@pytest.mark.parametrize(
    ("faults", "code"),
    [
        ([429, 429, 429], "GITHUB_UNAVAILABLE"),
        ([redirect(301)], "GITHUB_REQUEST_REJECTED"),
        ([redirect(307)], "GITHUB_REQUEST_REJECTED"),
        ([redirect(308)], "GITHUB_REQUEST_REJECTED"),
    ],
    ids=["429", "301", "307", "308"],
)
def test_a_delete_429_or_redirect_never_ends_not_applicable_and_never_owns(faults, code):
    gh = _gh()
    theirs = _seed_claim(gh, OTHER)
    gh.faults["comment_delete"] = list(faults)
    disposer, board, run = _disposer_spy(), MagicMock(), MagicMock()
    out = _claim(gh, FakeSupabase({OTHER: "running"}), disposer=disposer, board=board, run=run)
    _assert_failed_and_unowned(gh, out, run, disposer, board, code)
    assert out.winner == OTHER
    assert gh.deleted == []
    assert theirs in gh.comments[ISSUE]
    deletes = [c for c in gh.calls if c.method == "DELETE"]
    assert deletes and all(c.path.endswith(f"/issues/comments/{out.comment_id}") for c in deletes)


# ---------------------------------------------------------------------------
# The ownership gate (D-81): confirm only after the listing and the v_runs read
# ---------------------------------------------------------------------------


def test_confirm_ownership_comes_after_the_listing_and_the_v_runs_read():
    gh = _gh()
    _seed_claim(gh, OTHER)
    timeline: list[str] = []
    sb = TimelineSupabase({OTHER: "succeeded"}, timeline)
    disposer = _disposer_spy()

    def confirm() -> None:
        lists = [c for c in gh.calls if c.method == "GET" and c.path.endswith("/comments")]
        timeline.append(f"confirm(after {len(lists)} listing)")

    disposer.confirm_ownership.side_effect = confirm
    out = _claim(gh, sb, disposer=disposer, board=lambda: timeline.append("board"))
    assert out.owned
    assert timeline == ["v_runs", "confirm(after 1 listing)", "board"]


@pytest.mark.parametrize(
    "path",
    ["post_fault", "no_id", "list_fault", "v_runs_fault", "unknown_status", "delete_fault", "lost"],
)
def test_confirm_ownership_is_never_called_off_the_won_path(path):
    gh = _gh()
    sb = FakeSupabase({OTHER: "running"})
    if path not in {"post_fault", "no_id"}:
        _seed_claim(gh, OTHER)
    if path == "post_fault":
        gh.faults["comments_post"] = [503]
    elif path == "no_id":
        gh.faults["comments_post"] = [FakeResponse(201, None)]
    elif path == "list_fault":
        gh.faults["comments_get"] = [503, 503, 503]
    elif path == "v_runs_fault":
        sb.fail = 503
    elif path == "unknown_status":
        sb.statuses[OTHER] = "paused"
    elif path == "delete_fault":
        gh.faults["comment_delete"] = [422]
    disposer, board = _disposer_spy(), MagicMock()
    out = _claim(gh, sb, disposer=disposer, board=board)
    assert out.status in {"failed", "lost"}
    disposer.confirm_ownership.assert_not_called()
    board.assert_not_called()


# ---------------------------------------------------------------------------
# Secrets never reach a log, a run event or the summary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("route", ["comments_get", "comment_delete"])
def test_a_token_in_a_transport_error_is_scrubbed_everywhere(route, caplog):
    gh = _gh()
    _seed_claim(gh, OTHER)
    leak = requests.ConnectionError(f"down with {TOKEN} and {SB_KEY}")
    gh.faults[route] = [leak, leak, leak]
    run = MagicMock()
    with caplog.at_level(logging.DEBUG):
        out = _claim(gh, FakeSupabase({OTHER: "running"}), run=run)
    assert (out.status, out.error_code) == ("failed", "GITHUB_UNAVAILABLE")
    out.report(run)
    reported = " ".join(str(a) for call in run.mock_calls for a in call.args)
    reported += " " + " ".join(str(v) for call in run.mock_calls for v in call.kwargs.values())
    for text in (caplog.text, reported, out.summary):
        assert TOKEN not in text
        assert SB_KEY not in text


# ---------------------------------------------------------------------------
# The claim body: fixed text, run link from PANEL_BASE_URL
# ---------------------------------------------------------------------------


class TestClaimBodyFromConfig:
    def _env(self, panel: str | None) -> dict[str, str]:
        env = {
            "SUPABASE_URL": "https://sb.example",
            "SUPABASE_KEY_SECRET_ID": "id/sb",
            "ANTHROPIC_KEY_SECRET_ID": "id/an",
            "MODEL_ID": "claude-sonnet-5-5",
        }
        if panel is not None:
            env["PANEL_BASE_URL"] = panel
        return env

    def test_the_config_run_link_reaches_the_body_unchanged(self):
        cfg = load_config(self._env("https://dt-agent-fleet-panel.fly.dev/"))
        link = cfg.run_link(RUN.upper())
        assert link == LINK
        body = build_claim_body(RUN, link)
        assert body == f"{build('claim', RUN)}\n{CLAIM_LINE.format(run=LINK)}"
        assert [m.kind for m in parse_block(body)] == ["claim"]

    def test_no_panel_origin_names_the_run_id(self):
        cfg = load_config(self._env(None))
        body = build_claim_body(RUN, cfg.run_link(RUN))
        assert body.endswith(CLAIM_LINE.format(run=f"`{RUN}`"))

    @pytest.mark.parametrize(
        "link",
        [
            "javascript:alert(1)",
            "http://dt-agent-fleet-panel.fly.dev/runs/x",
            "https://panel.example/runs/x\n<!-- bug-fix:pr run=x -->",
            "https://panel.example/runs/x [click](https://evil.example)",
        ],
        ids=["javascript", "http", "newline-marker", "space-markdown"],
    )
    def test_a_hostile_link_falls_back_and_adds_no_marker(self, link):
        body = build_claim_body(RUN, link)
        assert body.endswith(CLAIM_LINE.format(run=f"`{RUN}`"))
        assert [m.kind for m in parse_block(body)] == ["claim"]
        assert body.count("\n") == 1
