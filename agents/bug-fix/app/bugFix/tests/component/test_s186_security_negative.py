"""Security-negative gap tests for S-186 (#368), added at the QA completion gate.

They pin marker trust, neutralizer, token-hygiene, host-pinning, truncation and
SIGTERM-backstop cases the story's own suites did not exercise. GitHub is the
in-memory :class:`FakeGitHub`, so the code under test builds its real requests.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from unittest.mock import MagicMock

import pytest

import signal_backstop
from disposition import Diagnosis, Disposer, build_body
from issues import (
    MAX_COMMENT_CHARS,
    GitHubError,
    GitHubRequestRejected,
    IssuesClient,
    truncate_comment,
    utf16_len,
)
from markers import Marker, build, is_trusted, parse_block, trusted_markers
from neutralize import neutralize
from scrubber import SecretSet
from signal_backstop import handle_termination
from tests.component.fake_github import API, APP_ID, TOKEN, FakeGitHub

RUN = "0b9a2f4e-1c3d-4e5f-8a6b-7c8d9e0f1a2b"
ISSUE = 7
TRIGGER = 2**31 + 77


def _secrets() -> SecretSet:
    s = SecretSet()
    s.add("GITHUB_INSTALLATION_TOKEN", TOKEN)
    return s


def _client(gh: FakeGitHub) -> IssuesClient:
    return IssuesClient("o", "r", TOKEN, session=gh)


def _disposer(gh: FakeGitHub, *, run=None, board=None) -> Disposer:
    d = Disposer(
        client=_client(gh),
        issue_number=ISSUE,
        run_id=RUN,
        app_id=APP_ID,
        trigger_comment_id=TRIGGER,
        secrets=_secrets(),
        run=run,
        board_ready=board,
    )
    d.confirm_ownership()
    return d


def _comment(body: str, *, app=APP_ID, user_type="Bot", cid=10) -> dict:
    return {
        "id": cid,
        "body": body,
        "user": {"login": "agent-fleet[bot]", "type": user_type},
        "performed_via_github_app": {"id": app},
    }


# ---------------------------------------------------------------------------
# Marker trust: spoofed user.type, lookalikes and HTML-comment nesting
# ---------------------------------------------------------------------------


class TestMarkerTrustNegative:
    @pytest.mark.parametrize("user_type", ["bot", "BOT", " Bot", "Bot ", "Bot\u200b", None, 1])
    def test_user_type_must_be_exactly_bot(self, user_type):
        assert not is_trusted(_comment(build("claim", RUN), user_type=user_type), APP_ID)

    @pytest.mark.parametrize(
        "app",
        [
            {"id": APP_ID},  # a dict where an int belongs
            [APP_ID],
            APP_ID + 1,
            -APP_ID,
            APP_ID * 1.0,
        ],
    )
    def test_app_id_lookalikes_are_untrusted(self, app):
        assert trusted_markers([_comment(build("claim", RUN), app=app)], APP_ID) == []

    @pytest.mark.parametrize(
        "line",
        [
            # Nested comment injection on line 1: the outer wrapper is not the grammar.
            f"<!-- {build('claim', RUN)} -->",
            f"<!-- <!-- agent-fleet:bug-fix:claim run_id={RUN} --> -->",
            build("claim", RUN).replace("<!--", "<!--\u200b"),
            # Lookalike digits or letters inside the UUID.
            build("claim", RUN).replace("0b9a", "\uff10b9a"),  # fullwidth zero
            build("claim", RUN).replace("0b9a", "0\u04329a"),  # Cyrillic ve
            build("claim", RUN).replace("0b9a", "0b\u03019a"),  # combining mark
            # Lookalike punctuation in the fixed parts.
            build("claim", RUN).replace("<", "\uff1c"),
            build("claim", RUN).replace("bug-fix", "bug\u2011fix"),
            build("claim", RUN).replace("-->", "\u2014>"),
            # Separators that are not a plain newline.
            build("claim", RUN) + "\u2028" + build("pr", RUN),
            build("claim", RUN) + "\r\r",
        ],
    )
    def test_injected_or_lookalike_first_line_is_not_parsed(self, line):
        assert parse_block(line) == ()

    def test_a_trusted_comment_trusts_only_its_leading_block(self):
        body = "\n".join([build("claim", RUN), "fixed text", build("disposition", RUN)])
        assert [m for _, m in trusted_markers([_comment(body)], APP_ID)] == [Marker("claim", RUN)]


# ---------------------------------------------------------------------------
# Neutralizer: keyword, separator and reference variants
# ---------------------------------------------------------------------------

_KEYWORDS = (
    "close",
    "closes",
    "closed",
    "fix",
    "fixes",
    "fixed",
    "resolve",
    "resolves",
    "resolved",
)


class TestNeutralizerVariants:
    @pytest.mark.parametrize("kw", _KEYWORDS)
    @pytest.mark.parametrize("case", [str.lower, str.upper, str.title, str.swapcase])
    @pytest.mark.parametrize("sep", [": ", ":\t", " ", "\u00a0", "\u2003", "  \n"])
    def test_every_keyword_case_and_separator(self, kw, case, sep):
        text = f"{case(kw)}{sep}#12"
        assert neutralize(text) == "(ref #12)"

    @pytest.mark.parametrize("prefix", ["- ", "* ", "1. ", "> ", "(", "**", "\u200b"])
    def test_keyword_after_markdown_or_zero_width_prefix(self, prefix):
        assert neutralize(f"{prefix}Fixes #3") == f"{prefix}(ref #3)"

    @pytest.mark.parametrize(
        "ref",
        [
            "https://github.com/o/r/issues/4#issuecomment-1",
            "HTTP://WWW.GITHUB.COM/o/r/pull/4",
            "o.r/x-y#4",
            "gh-4",
        ],
    )
    def test_reference_variants_are_neutralized(self, ref):
        out = neutralize(f"Resolves {ref}")
        assert out.startswith("(ref ")
        assert "Resolves" not in out

    def test_existing_zero_width_characters_are_preserved_and_idempotent(self):
        text = "@\u200buser @\u2060team fixes\u200b #1"
        once = neutralize(text)
        assert once == neutralize(once)
        assert "@\u200b\u200b" not in once


# ---------------------------------------------------------------------------
# Host pinning: lookalike hosts in a pagination "next" link
# ---------------------------------------------------------------------------


class TestHostPinning:
    @pytest.mark.parametrize(
        "next_url",
        [
            "https://api.github.com.evil.example/repos/o/r/issues/7/comments?page=2",
            "https://api.github.com@evil.example/repos/o/r/issues/7/comments?page=2",
            "https://api.github.com\\@evil.example/x",
            "https://api.github.com:8443/repos/o/r/issues/7/comments?page=2",
            "http://api.github.com/repos/o/r/issues/7/comments?page=2",
            "//evil.example/x",
            "/repos/o/r/issues/7/comments?page=2",
        ],
    )
    def test_lookalike_next_links_are_never_requested(self, next_url):
        gh = FakeGitHub(per_page_cap=1, next_link_override=next_url)
        gh.add_comment(ISSUE, "a")
        gh.add_comment(ISSUE, "b")
        with pytest.raises(GitHubRequestRejected) as exc:
            _client(gh).list_comments(ISSUE)
        assert len(gh.calls) == 1
        assert all(c.url.startswith(API + "/") for c in gh.calls)
        assert TOKEN not in str(exc.value)


# ---------------------------------------------------------------------------
# Token hygiene: no error path or log line carries the installation token
# ---------------------------------------------------------------------------


class TestTokenNeverLeaks:
    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429, 500, 503])
    @pytest.mark.parametrize("op", ["list", "post", "react"])
    def test_errors_and_logs_name_no_token(self, status, op, caplog):
        gh = FakeGitHub(list_status=status, post_status=status, reaction_status=status)
        client = _client(gh)
        caplog.set_level(logging.DEBUG)
        message = ""
        try:
            if op == "list":
                client.list_comments(ISSUE)
            elif op == "post":
                client.post_comment(ISSUE, "x")
            else:
                message = repr(client.add_reaction(TRIGGER, "confused"))
        except GitHubError as exc:
            message = f"{exc!s} {exc!r} {exc.args!r}"
        assert message
        assert TOKEN not in message
        assert TOKEN not in caplog.text

    def test_reaction_and_board_exceptions_carrying_the_token_are_scrubbed(self, caplog):
        gh = FakeGitHub()
        run = MagicMock()
        leaking = RuntimeError(f"Authorization: Bearer {TOKEN}")

        class _Raising(IssuesClient):
            def add_reaction(self, *a, **k):  # noqa: ARG002
                raise leaking

        d = _disposer(gh, run=run, board=MagicMock(side_effect=leaking))
        d.client = _Raising("o", "r", TOKEN, session=gh)
        caplog.set_level(logging.DEBUG)
        result = d.dispose(Diagnosis(why=f"token {TOKEN}", tried=f"used {TOKEN}"))
        assert (result.reaction, result.board) == ("failed", "failed")
        assert TOKEN not in caplog.text
        assert TOKEN not in str(run.mock_calls)
        assert TOKEN not in gh.writes()[0].json["body"]


# ---------------------------------------------------------------------------
# Truncation: never split a surrogate pair or the marker block
# ---------------------------------------------------------------------------


class TestTruncation:
    @pytest.mark.parametrize("pad", range(0, 4))
    def test_astral_text_at_every_alignment(self, pad):
        marker = build("disposition", RUN)
        body = marker + "\n" + "a" * pad + "\U0001f600" * MAX_COMMENT_CHARS
        out = truncate_comment(body)
        assert utf16_len(out) <= MAX_COMMENT_CHARS
        out.encode("utf-8")  # raises on a lone surrogate
        assert parse_block(out) == (Marker("disposition", RUN),)

    @pytest.mark.parametrize("pad", range(0, 4))
    def test_disposition_body_keeps_marker_and_pairs(self, pad):
        tried = "x" * pad + "\U0001f41b" * MAX_COMMENT_CHARS
        why = "\U0001f525" * (MAX_COMMENT_CHARS // 3)
        diffstat = " a.py | 1 +\n" + "\U0001f4a5" * (MAX_COMMENT_CHARS // 3)
        body = build_body(RUN, Diagnosis(why=why, tried=tried, diffstat=diffstat), [])
        assert utf16_len(body) <= MAX_COMMENT_CHARS
        body.encode("utf-8")
        assert parse_block(body) == (Marker("disposition", RUN),)
        assert "Comment `/bug-fix` to try again." in body


# ---------------------------------------------------------------------------
# SIGTERM while the main path's disposition is in flight
# ---------------------------------------------------------------------------


class _FrozenFirstList(FakeGitHub):
    """The first comment listing blocks, as the main thread does while the
    SIGTERM handler runs on it; later calls (the backstop's) go through."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self._first = True

    def request(self, method, url, **kwargs):
        if method == "GET" and self._first:
            self._first = False
            self.entered.set()
            self.release.wait(10)
        return super().request(method, url, **kwargs)


def test_sigterm_during_an_in_flight_disposition_still_posts_it():
    gh = _FrozenFirstList()
    d = _disposer(gh)
    main = threading.Thread(target=d.dispose, args=(Diagnosis(why="w", tried="t"),), daemon=True)
    main.start()
    assert gh.entered.wait(2)
    run = MagicMock()
    run._terminal = False
    try:
        start = time.monotonic()
        handle_termination(lambda: run, list, d.backstop_action, "SIGTERM", budget=2.0)
        assert time.monotonic() - start < 3.0
        # At this point the real process re-raises SIGTERM and dies.
        posted = [c for c in gh.writes() if c.path.endswith(f"/issues/{ISSUE}/comments")]
        assert len(posted) == 1
    finally:
        gh.release.set()
        main.join(5)


def _comment_posts(gh: FakeGitHub) -> list:
    return [c for c in gh.writes() if c.path.endswith(f"/issues/{ISSUE}/comments")]


def test_a_preempted_list_phase_owner_never_posts_after_it_resumes():
    """DF-186-04: once the backstop has taken over, the resumed owner can't post too."""
    gh = _FrozenFirstList()
    d = _disposer(gh)
    results: list = []
    main = threading.Thread(
        target=lambda: results.append(d.dispose(Diagnosis(why="w", tried="t"))), daemon=True
    )
    main.start()
    assert gh.entered.wait(2)
    run = MagicMock()
    run._terminal = False
    handle_termination(lambda: run, list, d.backstop_action, "SIGTERM", budget=2.0)
    gh.release.set()
    main.join(5)
    assert len(_comment_posts(gh)) == 1
    assert gh.reactions == [(TRIGGER, "confused")]
    assert results[0].status in ("already_disposed", "in_progress")
    assert run.fail.call_args.kwargs["error_message"].endswith(
        "Disposition posted before stopping."
    )


class _SignalDuring(FakeGitHub):
    """Delivers a real SIGTERM to this process while the main thread is inside
    the first ``method`` call, so the handler runs on the suspended owner's
    thread. For a POST the comment is recorded first: the post has landed."""

    def __init__(self, method: str, reraised: list[int]) -> None:
        super().__init__()
        self.method = method
        self.reraised = reraised
        self._first = True

    def request(self, method, url, **kwargs):
        if method != self.method or not self._first:
            return super().request(method, url, **kwargs)
        self._first = False
        resp = super().request(method, url, **kwargs)
        os.kill(os.getpid(), signal.SIGTERM)
        deadline = time.monotonic() + 5
        while not self.reraised and time.monotonic() < deadline:
            time.sleep(0.005)  # the handler runs here, on this (main) thread
        return resp


@pytest.mark.parametrize(
    ("method", "detail"),
    [
        ("GET", "Disposition posted before stopping."),
        ("POST", "Disposition was already posted for this run; nothing new was written."),
    ],
)
def test_real_sigterm_on_the_owner_thread_disposes_exactly_once(monkeypatch, method, detail):
    """The finally path runs on the main thread and SIGTERM suspends it mid-call.

    GET: the listing had not seen a marker, so the backstop posts the disposition.
    POST: the interrupted post had already landed, so the backstop's re-list sees
    its trusted marker and posts nothing; it still adds the missing 😕.
    """
    assert threading.current_thread() is threading.main_thread()
    reraised: list[int] = []
    monkeypatch.setattr(signal_backstop.signal, "raise_signal", reraised.append)
    gh = _SignalDuring(method, reraised)
    d = _disposer(gh)
    run = MagicMock()
    run._terminal = False
    original = signal.getsignal(signal.SIGTERM)
    try:
        signal_backstop.install_termination_backstop(
            lambda: run, list, get_disposition=d.backstop_action, budget=3.0
        )
        result = d.dispose(Diagnosis(why="w", tried="t"))
    finally:
        signal.signal(signal.SIGTERM, original)
    assert reraised == [signal.SIGTERM]
    assert len(_comment_posts(gh)) == 1
    assert gh.reactions == [(TRIGGER, "confused")]
    assert run.fail.call_args.kwargs["error_message"].endswith(detail)
    # The resumed owner sees it was taken over and writes nothing more.
    assert result.status in ("already_disposed", "in_progress")


class _SlowFirstPost(FakeGitHub):
    def __init__(self) -> None:
        super().__init__()
        self.posting = threading.Event()
        self._first = True

    def request(self, method, url, **kwargs):
        if method == "POST" and self._first and url.endswith("/comments"):
            self._first = False
            self.posting.set()
            time.sleep(0.3)
        return super().request(method, url, **kwargs)


def test_a_live_owner_already_posting_is_waited_for_not_duplicated():
    """An owner on another, running thread that is mid-post finishes its post;
    the backstop waits for it instead of posting a second comment."""
    gh = _SlowFirstPost()
    d = _disposer(gh)
    main = threading.Thread(target=d.dispose, args=(Diagnosis(why="w", tried="t"),), daemon=True)
    main.start()
    assert gh.posting.wait(2)
    run = MagicMock()
    run._terminal = False
    handle_termination(lambda: run, list, d.backstop_action, "SIGTERM", budget=2.0)
    main.join(5)
    assert len(_comment_posts(gh)) == 1
    assert gh.reactions == [(TRIGGER, "confused")]
    assert run.fail.call_args.kwargs["error_message"].endswith(
        "Disposition was already posted for this run; nothing new was written."
    )
