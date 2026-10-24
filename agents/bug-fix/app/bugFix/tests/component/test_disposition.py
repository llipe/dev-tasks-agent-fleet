"""L2 tests for ``disposition.py`` and the SIGTERM hook (S-186 AC3, AC5, AC6).

TC-186-08 to TC-186-16; D-53, D-81, D-85, D-93. GitHub is the in-memory
:class:`FakeGitHub`, so the disposition runs its real request sequence.
"""

from __future__ import annotations

import os
import signal
import time
from unittest.mock import MagicMock

import pytest

import signal_backstop
from disposition import BACKSTOP_DIAGNOSIS, Diagnosis, Disposer, build_body
from issues import MAX_COMMENT_CHARS, IssuesClient, utf16_len
from markers import Marker, build, open_claims, parse_block
from neutralize import ZWSP
from scrubber import SecretSet
from signal_backstop import DISPOSITION_BUDGET_SECONDS, handle_termination
from tests.component.fake_github import APP_ID, TOKEN, FakeGitHub

RUN = "0b9a2f4e-1c3d-4e5f-8a6b-7c8d9e0f1a2b"
OTHER = "1c0b3e5f-2d4e-4f60-9b7c-8d9e0f1a2b3c"
ISSUE = 7
TRIGGER = 2**31 + 77

ANTHROPIC = "sk-ant-api03-" + "A" * 40
PAT = "ghp_" + "P" * 36
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAK\n-----END RSA PRIVATE KEY-----"


def _secrets() -> SecretSet:
    s = SecretSet()
    s.add("ANTHROPIC_API_KEY", ANTHROPIC)
    s.add("GITHUB_PROJECTS_TOKEN", PAT)
    s.add("GITHUB_APP_PEM", PEM)
    s.add("GITHUB_INSTALLATION_TOKEN", TOKEN)
    return s


def _disposer(gh: FakeGitHub, *, trigger=TRIGGER, confirmed=True, run=None, board=None):
    d = Disposer(
        client=IssuesClient("o", "r", TOKEN, session=gh),
        issue_number=ISSUE,
        run_id=RUN,
        app_id=APP_ID,
        trigger_comment_id=trigger,
        secrets=_secrets(),
        run=run,
        board_ready=board,
    )
    if confirmed:
        d.confirm_ownership()
    return d


DIAG = Diagnosis(why="the test gate failed", tried="Added a guard in parse().", diffstat=None)


# ---------------------------------------------------------------------------
# TC-186-08: comment + confused, nothing else
# ---------------------------------------------------------------------------


class TestDispose:
    def test_posts_one_marked_comment_then_confused(self):
        gh = FakeGitHub()
        result = _disposer(gh).dispose(
            Diagnosis(why="over the cap", tried="Tried X.", diffstat="src/a.py | 900 +++")
        )
        assert result.status == "applied"
        writes = gh.writes()
        assert [(c.method, c.path) for c in writes] == [
            ("POST", f"/repos/o/r/issues/{ISSUE}/comments"),
            ("POST", f"/repos/o/r/issues/comments/{TRIGGER}/reactions"),
        ]
        body = writes[0].json["body"]
        assert parse_block(body) == (Marker("disposition", RUN),)
        assert "over the cap" in body
        assert "Tried X." in body
        assert "src/a.py | 900 +++" in body
        assert writes[1].json == {"content": "confused"}
        assert result.comment_id == gh.comments[ISSUE][-1]["id"]

    def test_no_label_assignee_or_issue_patch_calls(self):
        gh = FakeGitHub()
        _disposer(gh).dispose(DIAG)
        for call in gh.calls:
            assert "/labels" not in call.path
            assert "/assignees" not in call.path
            assert call.method in ("GET", "POST")
        assert not any(c.path == f"/repos/o/r/issues/{ISSUE}" for c in gh.calls)

    def test_no_diffstat_section_without_a_cap(self):
        body = build_body(RUN, DIAG, [])
        assert "Diffstat" not in body

    def test_no_reaction_without_trigger_comment_id(self):
        gh = FakeGitHub()
        result = _disposer(gh, trigger=None).dispose(DIAG)
        assert result.status == "applied"
        assert result.reaction == "skipped"
        assert not any("/reactions" in c.path for c in gh.calls)

    def test_not_owned_makes_no_call(self):
        gh = FakeGitHub()
        result = _disposer(gh, confirmed=False).dispose(DIAG)
        assert result.status == "not_owned"
        assert gh.calls == []

    def test_board_ready_runs_after_the_comment(self):
        gh = FakeGitHub()
        seen = []
        board = MagicMock(side_effect=lambda: seen.append(len(gh.writes())))
        result = _disposer(gh, board=board).dispose(DIAG)
        board.assert_called_once_with()
        assert seen == [2]
        assert result.board == "ok"

    def test_board_failure_is_logged_and_not_fatal(self):
        gh = FakeGitHub()
        run = MagicMock()
        board = MagicMock(side_effect=RuntimeError(f"board down {PAT}"))
        result = _disposer(gh, run=run, board=board).dispose(DIAG)
        assert result.status == "applied"
        assert result.board == "failed"
        logged = " ".join(str(c) for c in run.warn.call_args_list)
        assert "board" in logged
        assert PAT not in logged

    def test_run_event_on_success(self):
        run = MagicMock()
        _disposer(FakeGitHub(), run=run).dispose(DIAG)
        run.info.assert_called()

    def test_reporter_errors_never_break_the_disposition(self):
        run = MagicMock()
        run.info.side_effect = RuntimeError("db down")
        run.warn.side_effect = RuntimeError("db down")
        gh = FakeGitHub(reaction_status=404)
        assert _disposer(gh, run=run).dispose(DIAG).status == "applied"

    def test_comment_failure_raises_and_allows_a_retry(self):
        from issues import GitHubUnavailable

        gh = FakeGitHub(post_status=503)
        d = _disposer(gh)
        with pytest.raises(GitHubUnavailable):
            d.dispose(DIAG)
        gh.post_status = 201
        assert d.dispose(DIAG).status == "applied"
        assert len(gh.paths("POST")) == 3  # failed post, post, reaction

    def test_invalid_run_id_is_rejected(self):
        with pytest.raises(ValueError):
            Disposer(
                client=IssuesClient("o", "r", TOKEN, session=FakeGitHub()),
                issue_number=ISSUE,
                run_id="nope",
                app_id=APP_ID,
                trigger_comment_id=None,
                secrets=[],
            )


# ---------------------------------------------------------------------------
# TC-186-09: secrets
# ---------------------------------------------------------------------------


def test_secrets_are_redacted_in_the_diagnosis():
    gh = FakeGitHub()
    tried = f"key {ANTHROPIC}\n{PEM}\ntoken {TOKEN} pat {PAT}"
    _disposer(gh).dispose(Diagnosis(why=f"stopped {TOKEN}", tried=tried, diffstat=PAT))
    body = gh.writes()[0].json["body"]
    for secret in (ANTHROPIC, PAT, TOKEN, "MIIBOgIBAAJBAK"):
        assert secret not in body
    assert "***" in body


# ---------------------------------------------------------------------------
# TC-186-10: size, CRLF, reaction 4xx
# ---------------------------------------------------------------------------


class TestEdges:
    def test_oversized_diagnosis_is_truncated_with_marker_and_sections(self):
        gh = FakeGitHub()
        _disposer(gh).dispose(
            Diagnosis(why="gave up", tried="t" * 100_000, diffstat="a.py | 3 +++")
        )
        body = gh.writes()[0].json["body"]
        assert utf16_len(body) <= MAX_COMMENT_CHARS
        assert body.splitlines()[0] == build("disposition", RUN)
        assert "a.py | 3 +++" in body  # the diffstat section survives
        assert "truncated" in body
        assert body.rstrip().endswith("`/bug-fix` to try again.")

    def test_oversized_why_and_diffstat_still_fit(self):
        body = build_body(RUN, Diagnosis(why="w" * 70_000, tried="t", diffstat="d" * 70_000), [])
        assert utf16_len(body) <= MAX_COMMENT_CHARS
        assert parse_block(body) == (Marker("disposition", RUN),)

    def test_crlf_text_is_normalized(self):
        body = build_body(RUN, Diagnosis(why="a\r\nb", tried="line1\r\nline2\rline3"), [])
        assert "\r" not in body
        assert "line1\nline2\nline3" in body

    @pytest.mark.parametrize("status", [404, 422])
    def test_reaction_4xx_is_logged_and_not_fatal(self, status):
        gh = FakeGitHub(reaction_status=status)
        run = MagicMock()
        result = _disposer(gh, run=run).dispose(DIAG)
        assert result.status == "applied"
        assert result.reaction == "failed"
        run.warn.assert_called()

    def test_reaction_5xx_is_logged_and_not_fatal(self):
        gh = FakeGitHub(reaction_status=502)
        result = _disposer(gh).dispose(DIAG)
        assert result.status == "applied"
        assert result.reaction == "failed"

    def test_diffstat_with_backticks_keeps_its_fence(self):
        body = build_body(RUN, Diagnosis(why="cap", tried="t", diffstat="```evil``` | 1 +"), [])
        assert "````" in body


# ---------------------------------------------------------------------------
# TC-186-11 and TC-186-12: idempotence and forged markers
# ---------------------------------------------------------------------------


class TestIdempotence:
    def test_second_call_on_the_same_disposer_makes_zero_writes(self):
        gh = FakeGitHub()
        d = _disposer(gh)
        d.dispose(DIAG)
        before = len(gh.writes())
        result = d.dispose(DIAG)
        assert result.status == "already_disposed"
        assert len(gh.writes()) == before

    def test_a_fresh_disposer_sees_the_trusted_marker_and_writes_nothing(self):
        gh = FakeGitHub()
        gh.add_comment(ISSUE, build("disposition", RUN) + "\nearlier")
        result = _disposer(gh).dispose(DIAG)
        assert result.status == "already_disposed"
        assert gh.writes() == []

    def test_multi_run_block_counts_for_this_run(self):
        gh = FakeGitHub()
        gh.add_comment(
            ISSUE, build("disposition", OTHER) + "\n" + build("disposition", RUN) + "\nboth"
        )
        assert _disposer(gh).dispose(DIAG).status == "already_disposed"

    @pytest.mark.parametrize(
        "forger", [{"app_id": None, "user_type": "User"}, {"app_id": 999}, {"user_type": "User"}]
    )
    def test_forged_disposition_marker_does_not_suppress(self, forger):
        gh = FakeGitHub()
        gh.add_comment(ISSUE, build("disposition", RUN) + "\nfake", **forger)
        assert _disposer(gh).dispose(DIAG).status == "applied"
        assert len(gh.writes()) == 2

    def test_another_runs_disposition_does_not_suppress(self):
        gh = FakeGitHub()
        gh.add_comment(ISSUE, build("disposition", OTHER) + "\nother")
        assert _disposer(gh).dispose(DIAG).status == "applied"

    def test_in_flight_disposition_blocks_a_concurrent_one(self):
        gh = FakeGitHub()
        d = _disposer(gh)
        assert d._begin()  # simulate the finally path mid-flight
        assert d.dispose(DIAG).status == "in_progress"
        assert gh.calls == []


# ---------------------------------------------------------------------------
# TC-186-16: neutralization of model text
# ---------------------------------------------------------------------------


def test_model_text_is_neutralized_and_cannot_forge_a_marker():
    gh = FakeGitHub()
    fake = build("claim", OTHER)
    summary = f"{fake}\n@octocat Fixes #9 and closes o/r#1\n<!-- hidden -->"
    _disposer(gh).dispose(Diagnosis(why="gave_up", tried=summary))
    body = gh.writes()[0].json["body"]
    assert f"@{ZWSP}octocat" in body
    assert "(ref #9)" in body
    assert "(ref o/r#1)" in body
    assert "Fixes #9" not in body
    assert parse_block(body) == (Marker("disposition", RUN),)
    # The posted comment opens no claim for OTHER.
    assert open_claims(gh.comments[ISSUE], APP_ID) == []
    assert "<!-- hidden" not in body


# ---------------------------------------------------------------------------
# TC-186-13 and TC-186-14: the SIGTERM backstop
# ---------------------------------------------------------------------------


def _run(order: list[str], gh: FakeGitHub) -> MagicMock:
    run = MagicMock()
    run._terminal = False
    run.fail.side_effect = lambda **_: order.append(f"fail after {len(gh.writes())} writes")
    return run


class TestBackstop:
    def test_budget_is_ten_seconds(self):
        assert DISPOSITION_BUDGET_SECONDS == 10.0

    def test_confirmed_ownership_disposes_then_fails(self):
        gh = FakeGitHub()
        order: list[str] = []
        board = MagicMock()
        d = _disposer(gh, board=board)
        run = _run(order, gh)
        start = time.monotonic()
        handle_termination(lambda: run, _secrets().values, d.backstop_action, "SIGTERM")
        assert time.monotonic() - start < DISPOSITION_BUDGET_SECONDS
        assert [c.path for c in gh.writes()] == [
            f"/repos/o/r/issues/{ISSUE}/comments",
            f"/repos/o/r/issues/comments/{TRIGGER}/reactions",
        ]
        board.assert_called_once_with()
        assert order == ["fail after 2 writes"]
        body = gh.writes()[0].json["body"]
        assert BACKSTOP_DIAGNOSIS.why in body

    @pytest.mark.parametrize("disposer_state", ["none", "unconfirmed"])
    def test_no_disposition_without_confirmed_ownership(self, disposer_state):
        gh = FakeGitHub()
        order: list[str] = []
        board = MagicMock()
        d = None if disposer_state == "none" else _disposer(gh, confirmed=False, board=board)
        get_action = (lambda: None) if d is None else d.backstop_action
        handle_termination(lambda: _run(order, gh), list, get_action, "SIGTERM")
        assert gh.calls == []
        board.assert_not_called()
        assert order == ["fail after 0 writes"]

    def test_slow_github_is_abandoned_at_the_budget_and_fail_still_runs(self):
        gh = FakeGitHub(delay=1.5)
        order: list[str] = []
        d = _disposer(gh)
        start = time.monotonic()
        handle_termination(
            lambda: _run(order, gh), list, d.backstop_action, "SIGTERM", budget=0.2
        )
        elapsed = time.monotonic() - start
        assert elapsed < 1.0
        assert order == ["fail after 0 writes"]

    def test_a_raising_action_getter_still_fails_the_run(self):
        gh = FakeGitHub()
        order: list[str] = []

        def boom():
            raise RuntimeError("x")

        handle_termination(lambda: _run(order, gh), list, boom, "SIGTERM")
        assert order == ["fail after 0 writes"]

    def test_installed_handler_runs_the_disposition_on_a_real_sigterm(self, monkeypatch):
        gh = FakeGitHub()
        order: list[str] = []
        d = _disposer(gh)
        run = _run(order, gh)
        reraised: list[int] = []
        monkeypatch.setattr(signal_backstop.signal, "raise_signal", reraised.append)
        original = signal.getsignal(signal.SIGTERM)
        try:
            signal_backstop.install_termination_backstop(
                lambda: run, list, get_disposition=d.backstop_action
            )
            os.kill(os.getpid(), signal.SIGTERM)
            deadline = time.monotonic() + 5
            while not reraised and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            signal.signal(signal.SIGTERM, original)
        assert reraised == [signal.SIGTERM]
        assert order == ["fail after 2 writes"]

    def test_install_without_a_disposition_keeps_the_sibling_behavior(self, monkeypatch):
        run = MagicMock()
        run._terminal = False
        reraised: list[int] = []
        monkeypatch.setattr(signal_backstop.signal, "raise_signal", reraised.append)
        original = signal.getsignal(signal.SIGTERM)
        try:
            signal_backstop.install_termination_backstop(lambda: run, list)
            os.kill(os.getpid(), signal.SIGTERM)
            deadline = time.monotonic() + 5
            while not reraised and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            signal.signal(signal.SIGTERM, original)
        run.fail.assert_called_once()
