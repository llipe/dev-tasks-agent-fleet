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
    DEFAULT_BUDGET_SECONDS,
    MAX_ATTEMPTS,
    MAX_WAIT_SECONDS,
    SECONDARY_LIMIT_WAIT_SECONDS,
    GitHubClient,
    GitHubError,
    GitHubRequestRejected,
    GitHubUnavailable,
    next_link,
    parse_link_header,
)
from issues import IssuesClient
from tests.conftest import FakeClock

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
        self.kwargs: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kw: Any) -> Any:
        self.calls.append((method, url, kw.get("json")))
        self.kwargs.append(kw)
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
        # No header: GitHub's guidance for a secondary limit is at least a minute.
        assert sleeps.waits == [7.0 if headers else SECONDARY_LIMIT_WAIT_SECONDS]

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
    def test_an_unreadable_retry_after_waits_the_secondary_minimum(self, value):
        sleeps = Sleeps()
        session = Scripted(real_response(429, {}, headers={"retry-after": value}), 200)
        _client(session, sleeps).request("GET", f"{API}/x", label="x")
        assert sleeps.waits == [SECONDARY_LIMIT_WAIT_SECONDS]


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


# ---------------------------------------------------------------------------
# QA gate (S-185): bounded waits, partial GraphQL, Link-header hardening
# ---------------------------------------------------------------------------


class TestWaitsAreBounded:
    @pytest.mark.parametrize("value", ["inf", "Infinity", "1e400", "-inf"])
    def test_a_non_finite_retry_after_never_becomes_the_wait(self, value):
        sleeps = Sleeps()
        session = Scripted(real_response(429, {}, headers={"retry-after": value}), 200)
        _client(session, sleeps).request("GET", f"{API}/x", label="x")
        assert sleeps.waits == [SECONDARY_LIMIT_WAIT_SECONDS]

    def test_a_retry_after_at_the_cap_is_taken(self):
        sleeps = Sleeps()
        cap = str(MAX_WAIT_SECONDS)
        session = Scripted(real_response(429, {}, headers={"retry-after": cap}), 200)
        _client(session, sleeps).request("GET", f"{API}/x", label="x")
        assert sleeps.waits == [MAX_WAIT_SECONDS]

    @pytest.mark.parametrize("method", ["GET", "POST"])
    def test_one_call_never_waits_longer_than_its_retries_allow(self, method):
        sleeps = Sleeps()
        limited = real_response(429, {}, headers={"retry-after": str(MAX_WAIT_SECONDS)})
        session = Scripted(limited)
        with pytest.raises(GitHubUnavailable):
            _client(session, sleeps).request(method, f"{API}/x", label="x")
        assert len(session.calls) == MAX_ATTEMPTS
        assert sum(sleeps.waits) <= MAX_WAIT_SECONDS * (MAX_ATTEMPTS - 1)

    def test_a_huge_retry_after_on_a_write_gives_up_without_waiting(self):
        sleeps = Sleeps()
        session = Scripted(real_response(429, {}, headers={"retry-after": "86400"}))
        with pytest.raises(GitHubUnavailable):
            _client(session, sleeps).request("POST", f"{API}/x", label="x")
        assert sleeps.waits == [] and len(session.calls) == 1

    def test_a_far_reset_with_a_small_retry_after_honours_retry_after(self, monkeypatch):
        monkeypatch.setattr(github_client.time, "time", lambda: 1000.0)
        sleeps = Sleeps()
        limited = real_response(
            403,
            {},
            headers={
                "retry-after": "2",
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": "999999",
            },
        )
        _client(Scripted(limited, 200), sleeps).request("GET", f"{API}/x", label="x")
        assert sleeps.waits == [2.0]


class TestGraphQLPartialAndShape:
    def test_data_with_errors_is_rejected_not_returned(self):
        payload = {"data": {"repository": {"issue": None}}, "errors": [{"type": "FORBIDDEN"}]}
        with pytest.raises(GitHubRequestRejected):
            _client(Scripted(real_response(200, payload))).graphql("query { x }", {}, label="q")

    @pytest.mark.parametrize("errors", ["boom", {"type": "X"}, [{"message": "no type"}], [1]])
    def test_malformed_errors_are_still_errors(self, errors):
        payload = {"data": {"x": 1}, "errors": errors}
        with pytest.raises(GitHubRequestRejected):
            _client(Scripted(real_response(200, payload))).graphql("query { x }", {}, label="q")

    @pytest.mark.parametrize("query", ["  mutation { x }", "MUTATION { x }", "\nmutation m { x }"])
    def test_a_mutation_in_any_spelling_is_refused(self, query):
        session = Scripted(200)
        with pytest.raises(ValueError):
            _client(session).graphql(query, {}, label="m")
        assert session.calls == []


class TestClosingQueryUsesVariables:
    """GraphQL injection: owner, repo and number travel as variables only."""

    def test_the_query_text_is_constant_and_values_are_variables(self):
        import issues

        page = {
            "data": {
                "repository": {
                    "issue": {
                        "closedByPullRequestsReferences": {
                            "nodes": [],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            }
        }
        session = Scripted(real_response(200, page))
        IssuesClient("my-org", "my.repo_1", TOKEN, session=session).closing_prs(987654)
        (_, url, body) = session.calls[0]
        assert url == f"{API}/graphql"
        assert body["query"] == issues._CLOSING_PRS_QUERY
        assert "987654" not in body["query"] and "my-org" not in body["query"]
        assert body["variables"] == {
            "owner": "my-org",
            "name": "my.repo_1",
            "number": 987654,
            "after": None,
        }

    @pytest.mark.parametrize(
        "owner,repo",
        [
            ('o") { x } #', "r"),
            ("o", "r\n}"),
            ("o/../x", "r"),
            ("..", "r"),
            ("o", ""),
            ("o", "r$x"),
        ],
    )
    def test_a_hostile_owner_or_repo_is_refused_before_any_call(self, owner, repo):
        session = Scripted(200)
        with pytest.raises(ValueError):
            IssuesClient(owner, repo, TOKEN, session=session)
        assert session.calls == []


class TestNextLinkPinningAfterTheRefactor:
    """QA gap 5 holds on top of github_client.py: a ``next`` link stays on the resource."""

    @pytest.mark.parametrize(
        "link",
        [
            "https://api.github.com@evil.example/repos/o/r/issues/7/comments?page=2",
            "https://evil.example/repos/o/r/issues/7/comments?page=2",
            "http://api.github.com/repos/o/r/issues/7/comments?page=2",
            "https://api.github.com:8443/repos/o/r/issues/7/comments?page=2",
            "//api.github.com/repos/o/r/issues/7/comments?page=2",
            "https://api.github.com/repos/o/r/issues/7/comments/../../8/comments?page=2",
            "https://api.github.com/repos/o/r/issues/7%2fcomments?page=2",
            "https://api.github.com/repos/other/r/issues/7/comments?page=2",
            "https://api.github.com/repos/o/r/issues/7/comments#frag",
            "https://api.github.com/user?page=2",
        ],
    )
    def test_a_real_header_off_the_resource_is_refused(self, link):
        session = Scripted(real_response(200, [], headers={"Link": f'<{link}>; rel="next"'}))
        with pytest.raises(GitHubRequestRejected):
            IssuesClient("o", "r", TOKEN, session=session).list_comments(7)
        assert len(session.calls) == 1

    def test_a_repository_id_change_between_pages_is_refused(self):
        p2 = f"{API}/repositories/1/pulls?page=2"
        p3 = f"{API}/repositories/2/pulls?page=3"
        session = Scripted(
            real_response(200, [], headers={"Link": f'<{p2}>; rel="next"'}),
            real_response(200, [], headers={"Link": f'<{p3}>; rel="next"'}),
        )
        with pytest.raises(GitHubRequestRejected):
            IssuesClient("o", "r", TOKEN, session=session).open_pulls()
        assert len(session.calls) == 2

    @pytest.mark.parametrize(
        "header",
        [
            '<https://api.github.com/x?page=2>; xrel="next"',
            "<https://api.github.com/x?page=2>; xrel=next",
            '<https://api.github.com/x?page=2>; relx="next"',
            '<https://api.github.com/x?page=2>; title="rel=next"',
            '<https://api.github.com/x?page=2>; title="a; rel=next"',
            '<https://api.github.com/x?page=2>; title="a\\"; rel=next"',
            '<https://api.github.com/x?page=2>; title="a, <https://e/>; rel=next"',
            '<https://api.github.com/x?page=2>; anchor="#rel=next"; rel="prev"',
            '<https://api.github.com/x?page=2>; rel="prev"; rel="next"',
            "<https://api.github.com/x?page=2>; rel=",
            '<https://api.github.com/x?page=2>; title="unterminated; rel=next',
        ],
    )
    def test_only_a_rel_parameter_names_a_relation(self, header):
        """QA 4: ``rel`` is a whole parameter name, and quoted text is never a parameter."""
        assert "next" not in parse_link_header(header)
        assert next_link(real_response(200, [], headers={"Link": header})) is None

    @pytest.mark.parametrize(
        "header",
        [
            '<https://api.github.com/x?page=2>; REL="next"',
            '<https://api.github.com/x?page=2> ; rel = "next"',
            '<https://api.github.com/x?page=2>; title="a; b, c"; rel=next',
            '<https://api.github.com/x?page=1>; title="rel=next", '
            '<https://api.github.com/x?page=2>; rel="next"',
        ],
    )
    def test_a_real_rel_parameter_still_parses(self, header):
        assert parse_link_header(header)["next"] == "https://api.github.com/x?page=2"

    def test_a_header_wins_over_requests_own_link_parsing(self):
        """``requests`` splits parameters on every ``;``, even inside quotes."""
        header = '<https://api.github.com/x?page=2>; title="a; rel=next"'
        resp = real_response(200, [], headers={"Link": header})
        assert "next" in resp.links  # requests' parser is fooled
        assert next_link(resp) is None


@pytest.mark.parametrize("page", [{"message": "x"}, None, "x"])
def test_a_page_that_is_not_a_list_is_rejected_not_read_as_empty(page):
    """D-67: a malformed comments page must not read as "no claims"."""
    resp = real_response(200, page) if page is not None else real_response(200)
    with pytest.raises(GitHubRequestRejected):
        IssuesClient("o", "r", TOKEN, session=Scripted(resp)).list_comments(7)


# ---------------------------------------------------------------------------
# QA 1: a page cap is a fault, never a silent "no match"
# ---------------------------------------------------------------------------


def _page(n: int, *, more: bool) -> requests.Response:
    headers = {"Link": f'<{API}/x?page={n + 1}>; rel="next"'} if more else {}
    return real_response(200, [n], headers=headers)


class TestPageCap:
    def test_more_pages_than_the_cap_is_unavailable(self):
        session = Scripted(_page(1, more=True), _page(2, more=True), _page(3, more=False))
        with pytest.raises(GitHubUnavailable) as exc:
            _client(session).get_paged(
                f"{API}/x", label="GET /x", params=None, allow_next=lambda _u: None, max_pages=2
            )
        assert exc.value.code == "GITHUB_UNAVAILABLE"
        assert "2 pages" in str(exc.value)
        assert len(session.calls) == 2

    def test_exactly_the_cap_with_no_next_page_returns_every_item(self):
        session = Scripted(_page(1, more=True), _page(2, more=False))
        got = _client(session).get_paged(
            f"{API}/x", label="GET /x", params=None, allow_next=lambda _u: None, max_pages=2
        )
        assert got == [1, 2]


# ---------------------------------------------------------------------------
# QA 3: redirects are never followed; a 3xx is a typed fault
# ---------------------------------------------------------------------------


def _redirect(status: int) -> requests.Response:
    return real_response(status, None, headers={"Location": "https://evil.example/steal"})


class TestNoRedirects:
    @pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE"])
    def test_every_request_disables_redirects(self, method):
        session = Scripted(200)
        _client(session).request(method, f"{API}/x", label="x")
        assert session.kwargs[0]["allow_redirects"] is False

    def test_a_graphql_query_disables_redirects(self):
        session = Scripted(real_response(200, {"data": {}}))
        _client(session).graphql("query { x }", {}, label="q")
        assert session.kwargs[0]["allow_redirects"] is False

    @pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
    def test_a_read_redirect_is_rejected_and_not_retried(self, status):
        session = Scripted(_redirect(status))
        with pytest.raises(GitHubRequestRejected) as exc:
            _client(session).request("GET", f"{API}/repos/o/r/issues/1", label="GET issue")
        assert exc.value.code == "GITHUB_REQUEST_REJECTED"
        assert exc.value.status == status
        assert "redirect" in str(exc.value)
        assert "evil.example" not in str(exc.value)
        assert len(session.calls) == 1

    @pytest.mark.parametrize("status", [301, 302, 307, 308])
    def test_a_write_redirect_is_rejected_never_a_success(self, status):
        session = Scripted(_redirect(status))
        with pytest.raises(GitHubRequestRejected):
            _client(session).request("POST", f"{API}/repos/o/r/issues/1/comments", label="x")
        assert len(session.calls) == 1

    def test_a_redirect_with_not_found_ok_is_still_rejected(self):
        with pytest.raises(GitHubRequestRejected):
            _client(Scripted(_redirect(301))).request(
                "GET", f"{API}/repos/o/r/issues/1", label="x", not_found_ok=True
            )

    def test_a_graphql_redirect_is_rejected(self):
        with pytest.raises(GitHubRequestRejected):
            _client(Scripted(_redirect(307))).graphql("query { x }", {}, label="q")

    def test_a_paged_redirect_is_rejected_not_read_as_the_last_page(self):
        session = Scripted(_redirect(302))
        with pytest.raises(GitHubRequestRejected):
            IssuesClient("o", "r", TOKEN, session=session).list_comments(7)


# ---------------------------------------------------------------------------
# QA 5 / DF-185-06: Retry-After up to 60 s, inside one total wait budget
# ---------------------------------------------------------------------------


def _timed(session: Any, clock: FakeClock, **kw: Any) -> GitHubClient:
    return GitHubClient(TOKEN, session=session, sleep=clock.sleep, clock=clock, **kw)


def _secondary(retry_after: str | None = None) -> requests.Response:
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    return real_response(
        403, {"message": "You have exceeded a secondary rate limit."}, headers=headers
    )


class TestWaitBudget:
    def test_the_defaults(self):
        assert DEFAULT_BUDGET_SECONDS == 120.0
        assert MAX_WAIT_SECONDS == SECONDARY_LIMIT_WAIT_SECONDS == 60.0
        assert GitHubClient(TOKEN).budget == DEFAULT_BUDGET_SECONDS

    def test_the_common_retry_after_60_is_retried(self):
        clock = FakeClock()
        session = Scripted(_secondary("60"), real_response(200, {}))
        resp = _timed(session, clock).request("GET", f"{API}/x", label="x")
        assert resp is not None and resp.status_code == 200
        assert clock.waits == [60.0]

    def test_a_retry_after_over_60_gives_up_at_once(self):
        clock = FakeClock()
        session = Scripted(_secondary("61"))
        with pytest.raises(GitHubUnavailable):
            _timed(session, clock).request("GET", f"{API}/x", label="x")
        assert clock.waits == [] and len(session.calls) == 1

    def test_without_a_header_a_secondary_limit_waits_a_minute(self):
        clock = FakeClock()
        session = Scripted(_secondary(), real_response(200, {}))
        _timed(session, clock).request("GET", f"{API}/x", label="x")
        assert clock.waits == [SECONDARY_LIMIT_WAIT_SECONDS]

    def test_a_wait_past_the_deadline_is_never_taken(self):
        clock = FakeClock()
        session = Scripted(_secondary())
        with pytest.raises(GitHubUnavailable) as exc:
            _timed(session, clock, budget=100).request("GET", f"{API}/x", label="GET /x")
        # 60 s fits; a second 60 s would end at 120 s, past the 100 s budget.
        assert clock.waits == [60.0]
        assert len(session.calls) == 2
        assert exc.value.code == "GITHUB_UNAVAILABLE"
        assert "budget" in str(exc.value)

    def test_a_caller_set_deadline_bounds_every_wait(self):
        clock = FakeClock()
        client = _timed(Scripted(_secondary("45")), clock)
        with pytest.raises(GitHubUnavailable), client.deadline(30):
            client.request("GET", f"{API}/x", label="x")
        assert clock.waits == []

    def test_a_nested_deadline_keeps_the_outer_one(self):
        clock = FakeClock()
        client = _timed(Scripted(_secondary("20"), _secondary("20"), 200), clock)
        with pytest.raises(GitHubUnavailable), client.deadline(30), client.deadline(500):
            client.request("GET", f"{API}/x", label="x")
        assert clock.waits == [20.0]

    def test_each_operation_gets_its_own_budget(self):
        clock = FakeClock()
        session = Scripted(_secondary("60"), 200, _secondary("60"), 200)
        client = _timed(session, clock, budget=90)
        client.request("GET", f"{API}/x", label="x")
        client.request("GET", f"{API}/y", label="y")
        assert clock.waits == [60.0, 60.0]

    def test_graphql_rate_limits_and_http_retries_share_one_budget(self):
        clock = FakeClock()
        limited = real_response(200, {"errors": [{"type": "RATE_LIMITED", "message": "x"}]})
        session = Scripted(502, 502, limited, limited, real_response(200, {"data": {}}))
        with pytest.raises(GitHubUnavailable):
            _timed(session, clock).graphql("query { x }", {}, label="q")
        # HTTP backoff 1 s + 2 s, one GraphQL wait of 60 s; a second would pass 120 s.
        assert clock.waits == [1.0, 2.0, 60.0]
        assert sum(clock.waits) <= DEFAULT_BUDGET_SECONDS

    def test_pages_share_one_budget(self):
        clock = FakeClock()
        answers = []
        for n in range(1, 4):
            answers += [_secondary(), _page(n, more=True)]
        session = Scripted(*answers)
        with pytest.raises(GitHubUnavailable):
            _timed(session, clock).get_paged(
                f"{API}/x", label="GET /x", params=None, allow_next=lambda _u: None, max_pages=5
            )
        # Page 1 waits 60 s; page 2's 60 s would reach the 120 s deadline.
        assert clock.waits == [60.0]
        assert len(session.calls) == 3
        assert clock.now - 1_000.0 < DEFAULT_BUDGET_SECONDS

    def test_slow_requests_use_up_the_budget_too(self):
        clock = FakeClock()

        class Slow(Scripted):
            def request(self, method, url, **kw):
                clock.now += 50
                return super().request(method, url, **kw)

        session = Slow(502)
        with pytest.raises(GitHubUnavailable):
            _timed(session, clock, budget=100).request("GET", f"{API}/x", label="x")
        # 50 + 1 + 50 = 101: the third attempt never starts.
        assert len(session.calls) == 2
        # A request never waits on the network past the deadline either.
        assert session.kwargs[1]["timeout"] <= 100 - 51

    def test_a_write_rate_limit_wait_stays_in_the_budget(self):
        clock = FakeClock()
        session = Scripted(_secondary("60"), _secondary("60"), 201)
        with pytest.raises(GitHubUnavailable):
            _timed(session, clock, budget=100).request("POST", f"{API}/x", label="x")
        assert clock.waits == [60.0]


# ---------------------------------------------------------------------------
# DF-185-05: GraphQL errors[] are classified, and neither class is "no data"
# ---------------------------------------------------------------------------


def _gql_errors(*errors: dict) -> requests.Response:
    return real_response(200, {"data": None, "errors": list(errors)})


TRANSIENT_ERRORS = [
    {"type": "RATE_LIMITED", "message": "x"},
    {"type": "INTERNAL", "message": "x"},
    {"type": "SERVER_ERROR", "message": "x"},
    {"type": "TIMEOUT", "message": "x"},
    {"type": "SERVICE_UNAVAILABLE", "message": "x"},
    {
        "message": "Something went wrong while executing your query. This may be the result of a timeout"
    },
    {"message": "502 Bad Gateway"},
    {"message": "Internal server error"},
]
PERMANENT_ERRORS = [
    {"type": "NOT_FOUND", "message": "Could not resolve"},
    {"type": "FORBIDDEN", "message": "x"},
    {"type": "UNPROCESSABLE", "message": "x"},
    {"type": "SOMETHING_NEW", "message": "x"},
    {"message": "Field 'x' doesn't exist on type 'Query'"},
    {"type": "INTERNAL_ish", "message": "x"},
]


class TestGraphQLErrorClasses:
    @pytest.mark.parametrize("error", TRANSIENT_ERRORS, ids=str)
    def test_a_transient_error_is_retried_then_unavailable(self, error):
        clock = FakeClock()
        session = Scripted(_gql_errors(error))
        with pytest.raises(GitHubUnavailable) as exc:
            _timed(session, clock).graphql("query { x }", {}, label="q")
        assert exc.value.code == "GITHUB_UNAVAILABLE"
        # A RATE_LIMITED wait is 60 s, so the budget allows one retry, not two.
        assert 2 <= len(session.calls) <= MAX_ATTEMPTS
        assert sum(clock.waits) < DEFAULT_BUDGET_SECONDS

    @pytest.mark.parametrize("error", TRANSIENT_ERRORS, ids=str)
    def test_a_transient_error_then_data_recovers(self, error):
        session = Scripted(_gql_errors(error), real_response(200, {"data": {"ok": 1}}))
        assert _client(session).graphql("query { x }", {}, label="q") == {"ok": 1}
        assert len(session.calls) == 2

    def test_a_non_rate_limit_transient_error_backs_off(self):
        clock = FakeClock()
        session = Scripted(_gql_errors({"type": "INTERNAL"}))
        with pytest.raises(GitHubUnavailable):
            _timed(session, clock).graphql("query { x }", {}, label="q")
        assert clock.waits == [1.0, 2.0]

    @pytest.mark.parametrize("error", PERMANENT_ERRORS, ids=str)
    def test_a_permanent_error_is_rejected_at_once(self, error):
        session = Scripted(_gql_errors(error))
        with pytest.raises(GitHubRequestRejected) as exc:
            _client(session).graphql("query { x }", {}, label="q")
        assert exc.value.code == "GITHUB_REQUEST_REJECTED"
        assert len(session.calls) == 1

    def test_a_permanent_error_next_to_a_transient_one_is_rejected(self):
        session = Scripted(_gql_errors({"type": "RATE_LIMITED"}, {"type": "NOT_FOUND"}))
        with pytest.raises(GitHubRequestRejected):
            _client(session).graphql("query { x }", {}, label="q")
        assert len(session.calls) == 1

    def test_no_error_message_reaches_the_exception(self):
        session = Scripted(_gql_errors({"message": f"502 upstream for {TOKEN}"}))
        with pytest.raises(GitHubUnavailable) as exc:
            _client(session).graphql("query { x }", {}, label="q")
        assert TOKEN not in str(exc.value) and "upstream" not in str(exc.value)
