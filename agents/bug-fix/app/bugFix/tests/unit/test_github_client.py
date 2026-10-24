"""L1 tests for the shared GitHub client (S-185 AC5; TC-185-14; D-67; DF-186-02).

The transport is a scripted ``request()`` double, or real ``requests.Response``
objects with a real ``Link`` header, so the parser the L2 double skips
(``fake_github.py`` hands over pre-parsed ``links``) is exercised here.
"""

from __future__ import annotations

import json as jsonlib
import logging
from collections.abc import Callable
from typing import Any

import pytest
import requests

import github_client
from github_client import (
    MAX_ATTEMPTS,
    MAX_WAIT_SECONDS,
    GitHubClient,
    GitHubError,
    GitHubRequestRejected,
    GitHubUnavailable,
    next_link,
    parse_link_header,
)
from issues import IssuesClient

API = "https://api.github.com"
TOKEN = "ghs_" + "Z" * 36


def real_response(
    status: int, payload: Any = None, *, headers: dict[str, str] | None = None, url: str = ""
) -> requests.Response:
    """A genuine ``requests.Response``: its ``links`` come from the ``Link`` header."""
    resp = requests.Response()
    resp.status_code = status
    resp._content = b"" if payload is None else jsonlib.dumps(payload).encode()
    resp.headers.update(headers or {})
    resp.url = url
    resp.encoding = "utf-8"
    return resp


class Scripted:
    """A session whose answers are a fixed script; records (method, url, json)."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, str, Any]] = []

    def request(self, method: str, url: str, **kw: Any) -> Any:
        self.calls.append((method, url, kw.get("json")))
        item = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, int):
            return real_response(item, {"message": "x"})
        return item


class Sleeps:
    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def _client(session: Any, sleep: Callable[[float], None] | None = None) -> GitHubClient:
    return GitHubClient(TOKEN, session=session, sleep=sleep or Sleeps())


GITHUB_LINK = (
    '<https://api.github.com/repositories/1300192/issues/7/comments?per_page=100&page=2>; rel="next", '
    '<https://api.github.com/repositories/1300192/issues/7/comments?per_page=100&page=5>; rel="last", '
    '<https://api.github.com/repositories/1300192/issues/7/comments?per_page=100&page=1>; rel="first", '
    '<https://api.github.com/repositories/1300192/issues/7/comments?per_page=100&page=1>; rel="prev"'
)


# ---------------------------------------------------------------------------
# Link header (DF-186-02): parser level, on GitHub's real header format
# ---------------------------------------------------------------------------


class TestLinkHeader:
    def test_parses_githubs_four_relations(self):
        links = parse_link_header(GITHUB_LINK)
        assert set(links) == {"next", "last", "first", "prev"}
        assert links["next"].endswith("/repositories/1300192/issues/7/comments?per_page=100&page=2")
        assert links["last"].endswith("page=5")

    @pytest.mark.parametrize("value", ["", "   ", "garbage", "<>; rel=", 'rel="next"', None])
    def test_garbage_or_empty_yields_no_links(self, value):
        assert "next" not in parse_link_header(value)

    def test_quoted_and_unquoted_rel_and_extra_params(self):
        header = '<https://api.github.com/x?page=2>; type="text"; rel=next'
        assert parse_link_header(header) == {"next": "https://api.github.com/x?page=2"}

    def test_a_multi_valued_rel_names_each_relation(self):
        links = parse_link_header('<https://api.github.com/x?page=9>; rel="last next"')
        assert links["next"] == links["last"] == "https://api.github.com/x?page=9"

    def test_next_link_reads_a_real_response_header(self):
        resp = real_response(200, [], headers={"Link": GITHUB_LINK})
        assert next_link(resp) == parse_link_header(GITHUB_LINK)["next"]

    def test_next_link_is_none_on_the_last_page(self):
        last = GITHUB_LINK.split(", ", 1)[1]  # drop rel="next"
        assert next_link(real_response(200, [], headers={"Link": last})) is None
        assert next_link(real_response(200, [])) is None

    def test_next_link_accepts_a_pre_parsed_links_dict(self):
        class Parsed:
            headers: dict = {}
            links = {"next": {"url": "https://api.github.com/x?page=2"}}

        assert next_link(Parsed()) == "https://api.github.com/x?page=2"

    def test_issues_client_pages_through_real_link_headers(self):
        comment = {"id": 1, "body": "a", "user": {"type": "User"}}
        page2 = f"{API}/repos/o/r/issues/7/comments?per_page=100&page=2"
        session = Scripted(
            real_response(200, [comment], headers={"Link": f'<{page2}>; rel="next"'}),
            real_response(200, [{**comment, "id": 2}]),
        )
        got = IssuesClient("o", "r", TOKEN, session=session).list_comments(7)
        assert [c["id"] for c in got] == [1, 2]
        assert session.calls[1][1] == page2

    def test_a_real_next_link_off_the_resource_is_refused(self):
        evil = "https://api.github.com/repos/o/r/issues/8/comments?page=2"
        session = Scripted(real_response(200, [], headers={"Link": f'<{evil}>; rel="next"'}))
        with pytest.raises(GitHubRequestRejected):
            IssuesClient("o", "r", TOKEN, session=session).list_comments(7)
        assert len(session.calls) == 1


# ---------------------------------------------------------------------------
# Retry policy (D-67): reads retry transient faults; writes retry only limits
# ---------------------------------------------------------------------------


class TestReadRetries:
    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_5xx_is_retried_then_succeeds(self, status):
        sleeps = Sleeps()
        session = Scripted(status, status, real_response(200, {"ok": 1}))
        resp = _client(session, sleeps).request("GET", f"{API}/repos/o/r/issues/1", label="x")
        assert resp is not None and resp.status_code == 200
        assert len(session.calls) == 3
        assert sleeps.waits == [1.0, 2.0]

    def test_5xx_on_every_attempt_is_unavailable(self):
        session = Scripted(502)
        with pytest.raises(GitHubUnavailable) as exc:
            _client(session).request("GET", f"{API}/repos/o/r/issues/1", label="GET issue")
        assert exc.value.code == "GITHUB_UNAVAILABLE"
        assert exc.value.status == 502
        assert len(session.calls) == MAX_ATTEMPTS == 3

    def test_transport_errors_are_retried_and_hide_the_token(self):
        session = Scripted(requests.ConnectionError(f"boom Bearer {TOKEN}"))
        with pytest.raises(GitHubUnavailable) as exc:
            _client(session).request("GET", f"{API}/repos/o/r/issues/1", label="x")
        assert len(session.calls) == 3
        assert TOKEN not in str(exc.value)
        assert exc.value.__cause__ is None and exc.value.__suppress_context__

    @pytest.mark.parametrize(
        "headers,payload",
        [
            ({"retry-after": "7"}, {"message": "slow down"}),
            ({}, {"message": "You have exceeded a secondary rate limit."}),
        ],
    )
    def test_secondary_rate_limit_403_is_retried_honouring_retry_after(self, headers, payload):
        sleeps = Sleeps()
        session = Scripted(real_response(403, payload, headers=headers), real_response(200, {}))
        _client(session, sleeps).request("GET", f"{API}/repos/o/r/issues/1", label="x")
        assert len(session.calls) == 2
        assert sleeps.waits == [7.0 if headers else 1.0]

    def test_429_is_retried(self):
        sleeps = Sleeps()
        session = Scripted(real_response(429, {}, headers={"Retry-After": "2"}), 200)
        _client(session, sleeps).request("GET", f"{API}/x", label="x")
        assert sleeps.waits == [2.0]

    def test_a_retry_after_beyond_the_cap_gives_up_without_waiting(self):
        sleeps = Sleeps()
        big = str(int(MAX_WAIT_SECONDS) + 1)
        session = Scripted(real_response(429, {}, headers={"retry-after": big}))
        with pytest.raises(GitHubUnavailable):
            _client(session, sleeps).request("GET", f"{API}/x", label="x")
        assert len(session.calls) == 1
        assert sleeps.waits == []

    def test_primary_limit_waits_until_reset_when_it_is_near(self, monkeypatch):
        monkeypatch.setattr(github_client.time, "time", lambda: 1000.0)
        sleeps = Sleeps()
        limited = real_response(
            403, {}, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1004"}
        )
        session = Scripted(limited, 200)
        _client(session, sleeps).request("GET", f"{API}/x", label="x")
        assert sleeps.waits == [4.0]

    def test_primary_limit_far_from_reset_gives_up_at_once(self, monkeypatch):
        monkeypatch.setattr(github_client.time, "time", lambda: 1000.0)
        limited = real_response(
            403, {}, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "4600"}
        )
        session = Scripted(limited)
        with pytest.raises(GitHubUnavailable):
            _client(session).request("GET", f"{API}/x", label="x")
        assert len(session.calls) == 1

    @pytest.mark.parametrize("value", ["soon", "-3", "nan", ""])
    def test_an_unreadable_retry_after_falls_back_to_backoff(self, value):
        sleeps = Sleeps()
        session = Scripted(real_response(429, {}, headers={"retry-after": value}), 200)
        _client(session, sleeps).request("GET", f"{API}/x", label="x")
        assert sleeps.waits == [1.0]


class TestWrites:
    @pytest.mark.parametrize("status", [500, 502, 503])
    def test_a_write_5xx_is_not_retried(self, status):
        """A 5xx after GitHub applied a POST would duplicate the comment on retry."""
        session = Scripted(status)
        with pytest.raises(GitHubUnavailable):
            _client(session).request("POST", f"{API}/repos/o/r/issues/1/comments", label="x")
        assert len(session.calls) == 1

    def test_a_write_transport_error_is_not_retried(self):
        session = Scripted(requests.Timeout("t"))
        with pytest.raises(GitHubUnavailable):
            _client(session).request("POST", f"{API}/repos/o/r/issues/1/comments", label="x")
        assert len(session.calls) == 1

    def test_a_write_rate_limit_is_retried(self):
        """GitHub refuses a rate-limited request before applying it, so a retry is safe."""
        session = Scripted(real_response(429, {}, headers={"retry-after": "1"}), 201)
        resp = _client(session).request("POST", f"{API}/repos/o/r/issues/1/comments", label="x")
        assert resp is not None and resp.status_code == 201
        assert len(session.calls) == 2

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 410, 422])
    def test_an_unexpected_write_4xx_is_rejected(self, status):
        session = Scripted(status)
        with pytest.raises(GitHubRequestRejected) as exc:
            _client(session).request("POST", f"{API}/repos/o/r/issues/1/comments", label="x")
        assert exc.value.code == "GITHUB_REQUEST_REJECTED"
        assert exc.value.status == status
        assert len(session.calls) == 1

    def test_a_write_404_may_be_data_when_asked(self):
        session = Scripted(404)
        got = _client(session).request(
            "DELETE", f"{API}/repos/o/r/issues/comments/9", label="x", not_found_ok=True
        )
        assert got is None


class TestReads:
    def test_a_read_404_is_data_when_asked(self):
        got = _client(Scripted(404)).request(
            "GET", f"{API}/repos/o/r/issues/9", label="x", not_found_ok=True
        )
        assert got is None

    def test_a_read_404_is_rejected_by_default(self):
        with pytest.raises(GitHubRequestRejected):
            _client(Scripted(404)).request("GET", f"{API}/repos/o/r/issues/9", label="x")

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.example/repos/o/r",
            "https://api.github.com.evil.example/x",
            "http://api.github.com/x",
            "/repos/o/r",
        ],
    )
    def test_a_url_off_the_api_host_is_refused_before_sending(self, url):
        session = Scripted(200)
        with pytest.raises(GitHubRequestRejected):
            _client(session).request("GET", url, label="x")
        assert session.calls == []

    def test_headers_carry_the_token_and_api_version(self):
        captured: dict[str, Any] = {}

        class Capture:
            def request(self, method, url, **kw):
                captured.update(kw["headers"])
                return real_response(200, {})

        GitHubClient(lambda: TOKEN, session=Capture()).request("GET", f"{API}/x", label="x")
        assert captured["Authorization"] == f"Bearer {TOKEN}"
        assert captured["X-GitHub-Api-Version"] == github_client.API_VERSION

    def test_default_session_and_sleep(self):
        client = GitHubClient(TOKEN)
        assert isinstance(client.session, requests.Session)


# ---------------------------------------------------------------------------
# GraphQL
# ---------------------------------------------------------------------------


class TestGraphQL:
    def test_returns_data(self):
        session = Scripted(real_response(200, {"data": {"viewer": {"login": "x"}}}))
        assert _client(session).graphql("query { viewer { login } }", {}, label="q") == {
            "viewer": {"login": "x"}
        }
        method, url, body = session.calls[0]
        assert (method, url) == ("POST", f"{API}/graphql")
        assert body == {"query": "query { viewer { login } }", "variables": {}}

    def test_a_query_is_retried_on_5xx(self):
        session = Scripted(502, 502, real_response(200, {"data": {}}))
        assert _client(session).graphql("query { x }", {}, label="q") == {}
        assert len(session.calls) == 3

    def test_a_query_5xx_on_every_attempt_is_unavailable(self):
        session = Scripted(503)
        with pytest.raises(GitHubUnavailable):
            _client(session).graphql("query { x }", {}, label="q")
        assert len(session.calls) == 3

    def test_graphql_errors_are_rejected_and_name_no_message(self):
        payload = {"data": None, "errors": [{"type": "NOT_FOUND", "message": f"tok {TOKEN}"}]}
        with pytest.raises(GitHubRequestRejected) as exc:
            _client(Scripted(real_response(200, payload))).graphql("query { x }", {}, label="q")
        assert TOKEN not in str(exc.value)
        assert "NOT_FOUND" in str(exc.value)

    def test_a_graphql_rate_limit_is_retried_then_unavailable(self):
        limited = real_response(200, {"errors": [{"type": "RATE_LIMITED", "message": "x"}]})
        session = Scripted(limited)
        with pytest.raises(GitHubUnavailable):
            _client(session).graphql("query { x }", {}, label="q")
        assert len(session.calls) == 3

    @pytest.mark.parametrize("payload", [None, [], {"data": "x"}, {"nodata": 1}])
    def test_a_malformed_body_is_rejected(self, payload):
        resp = real_response(200, payload) if payload is not None else real_response(200)
        with pytest.raises(GitHubRequestRejected):
            _client(Scripted(resp)).graphql("query { x }", {}, label="q")

    def test_a_mutation_is_refused(self):
        session = Scripted(200)
        with pytest.raises(ValueError):
            _client(session).graphql("mutation { x }", {}, label="m")
        assert session.calls == []


# ---------------------------------------------------------------------------
# Token hygiene
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429, 500, 503])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_no_error_or_log_line_carries_the_token(status, method, caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(GitHubError) as exc:
        _client(Scripted(status)).request(method, f"{API}/x", label=f"{method} /x")
    text = f"{exc.value!s} {exc.value!r} {exc.value.args!r}"
    assert TOKEN not in text
    assert TOKEN not in caplog.text
