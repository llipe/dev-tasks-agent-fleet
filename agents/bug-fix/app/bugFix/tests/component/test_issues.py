"""L2 tests for ``issues.py``: comments and reactions (S-186 AC3; D-93; TC-186-15).

GitHub is the in-memory :class:`FakeGitHub`; ``issues.py`` builds the real
URLs, headers and bodies.
"""

from __future__ import annotations

import logging

import pytest
import requests

from issues import (
    MAX_COMMENT_CHARS,
    REACTIONS,
    GitHubRequestRejected,
    GitHubUnavailable,
    IssuesClient,
    truncate_comment,
    utf16_len,
)
from tests.component.fake_github import API, TOKEN, FakeGitHub


def _client(gh: FakeGitHub, token=TOKEN) -> IssuesClient:
    return IssuesClient("o", "r", token, session=gh)


class TestComments:
    def test_post_comment_sends_body_with_the_installation_token(self):
        gh = FakeGitHub()
        created = _client(gh).post_comment(7, "hello")
        call = gh.calls[-1]
        assert (call.method, call.path) == ("POST", "/repos/o/r/issues/7/comments")
        assert call.json == {"body": "hello"}
        assert call.headers["Authorization"] == f"Bearer {TOKEN}"
        assert call.headers["Accept"] == "application/vnd.github+json"
        assert call.timeout is not None
        assert created["id"] > 2**31

    def test_token_may_be_a_callable(self):
        gh = FakeGitHub()
        _client(gh, token=lambda: "ghs_fresh").post_comment(7, "x")
        assert gh.calls[-1].headers["Authorization"] == "Bearer ghs_fresh"

    def test_post_comment_truncates_an_oversized_body(self):
        gh = FakeGitHub()
        _client(gh).post_comment(7, "a" * (MAX_COMMENT_CHARS + 50))
        assert utf16_len(gh.calls[-1].json["body"]) <= MAX_COMMENT_CHARS

    def test_list_comments_follows_pagination(self):
        gh = FakeGitHub(per_page_cap=2)
        for i in range(5):
            gh.add_comment(7, f"c{i}")
        got = _client(gh).list_comments(7)
        assert [c["body"] for c in got] == [f"c{i}" for i in range(5)]
        assert len(gh.paths("GET")) == 3
        assert gh.calls[0].params["per_page"] == 100

    def test_next_link_to_another_host_is_not_followed(self):
        # The token must never be sent anywhere but the API host.
        gh = FakeGitHub(per_page_cap=1, next_link_override="https://evil.example/steal?page=2")
        gh.add_comment(7, "a")
        gh.add_comment(7, "b")
        with pytest.raises(GitHubRequestRejected):
            _client(gh).list_comments(7)
        assert all(c.url.startswith(API + "/") for c in gh.calls)

    def test_list_comments_4xx_is_rejected(self):
        gh = FakeGitHub(list_status=404)
        with pytest.raises(GitHubRequestRejected) as exc:
            _client(gh).list_comments(7)
        assert exc.value.code == "GITHUB_REQUEST_REJECTED"
        assert exc.value.status == 404

    def test_post_comment_4xx_is_rejected(self):
        gh = FakeGitHub(post_status=422)
        with pytest.raises(GitHubRequestRejected) as exc:
            _client(gh).post_comment(7, "x")
        assert TOKEN not in str(exc.value)

    @pytest.mark.parametrize("status", [500, 502, 503, 429])
    def test_5xx_and_429_are_unavailable(self, status):
        gh = FakeGitHub(post_status=status)
        with pytest.raises(GitHubUnavailable) as exc:
            _client(gh).post_comment(7, "x")
        assert exc.value.code == "GITHUB_UNAVAILABLE"

    def test_primary_rate_limit_403_is_unavailable(self):
        gh = FakeGitHub(post_status=403, extra_headers={"x-ratelimit-remaining": "0"})
        with pytest.raises(GitHubUnavailable):
            _client(gh).post_comment(7, "x")

    def test_plain_403_is_rejected(self):
        gh = FakeGitHub(post_status=403)
        with pytest.raises(GitHubRequestRejected):
            _client(gh).post_comment(7, "x")

    def test_transport_error_is_unavailable_and_hides_the_token(self):
        gh = FakeGitHub(raise_exc=requests.ConnectionError(f"boom Bearer {TOKEN}"))
        with pytest.raises(GitHubUnavailable) as exc:
            _client(gh).post_comment(7, "x")
        assert TOKEN not in str(exc.value)
        assert exc.value.__cause__ is None
        assert exc.value.__suppress_context__

    def test_non_json_list_response_is_rejected(self):
        class _Bad(FakeGitHub):
            def _list(self, issue, params):  # noqa: ARG002
                from tests.component.fake_github import FakeResponse

                return FakeResponse(200, None)

        with pytest.raises(GitHubRequestRejected):
            _client(_Bad()).list_comments(7)

    def test_default_session_is_a_requests_session(self):
        assert isinstance(IssuesClient("o", "r", TOKEN).session, requests.Session)

    @pytest.mark.parametrize(("owner", "repo"), [("o/x", "r"), ("o", "r/../x"), ("", "r")])
    def test_rejects_unsafe_owner_or_repo(self, owner, repo):
        with pytest.raises(ValueError):
            IssuesClient(owner, repo, TOKEN)


class TestReactions:
    def test_reaction_set(self):
        assert REACTIONS == ("eyes", "rocket", "confused")

    @pytest.mark.parametrize("content", REACTIONS)
    def test_adds_each_reaction(self, content):
        gh = FakeGitHub()
        result = _client(gh).add_reaction(55, content)
        call = gh.calls[-1]
        assert (call.method, call.path) == ("POST", "/repos/o/r/issues/comments/55/reactions")
        assert call.json == {"content": content}
        assert result.status == "added"

    def test_already_present_reaction_returns_200_and_counts_as_added(self):
        gh = FakeGitHub(reaction_status=200)
        assert _client(gh).add_reaction(55, "eyes").status == "added"

    def test_missing_comment_id_skips_silently(self):
        gh = FakeGitHub()
        result = _client(gh).add_reaction(None, "confused")
        assert result.status == "skipped"
        assert gh.calls == []

    @pytest.mark.parametrize("content", ["-1", "+1", "heart", "EYES", ""])
    def test_rejects_other_content(self, content):
        with pytest.raises(ValueError):
            _client(FakeGitHub()).add_reaction(55, content)

    @pytest.mark.parametrize("status", [404, 410, 422])
    def test_reaction_4xx_is_logged_and_not_fatal(self, status, caplog):
        gh = FakeGitHub(reaction_status=status)
        with caplog.at_level(logging.WARNING, logger="bug_fix.issues"):
            result = _client(gh).add_reaction(55, "confused")
        assert result.status == "failed"
        assert result.http_status == status
        assert any("reaction" in r.getMessage() for r in caplog.records)

    def test_reaction_5xx_raises_unavailable(self):
        gh = FakeGitHub(reaction_status=502)
        with pytest.raises(GitHubUnavailable):
            _client(gh).add_reaction(55, "rocket")


class TestTruncation:
    def test_short_body_unchanged(self):
        assert truncate_comment("abc") == "abc"

    def test_long_body_fits_and_says_so(self):
        out = truncate_comment("x" * 70_000)
        assert utf16_len(out) <= MAX_COMMENT_CHARS
        assert out.endswith("(truncated)")

    def test_astral_characters_count_as_two_units(self):
        body = "😕" * 40_000  # 80,000 UTF-16 code units
        out = truncate_comment(body)
        assert utf16_len(out) <= MAX_COMMENT_CHARS
        assert "\ud83d" not in out  # never a split surrogate

    def test_tiny_limit(self):
        assert utf16_len(truncate_comment("abcdef", limit=3)) <= 3


class TestEdgesOfTheClient:
    @pytest.mark.parametrize("cid", [0, -3, True, "55"])
    def test_reaction_rejects_an_invalid_comment_id(self, cid):
        with pytest.raises(ValueError):
            _client(FakeGitHub()).add_reaction(cid, "eyes")

    @pytest.mark.parametrize("payload", [None, ["not", "an", "object"]])
    def test_post_comment_without_a_json_object_returns_empty(self, payload):
        from tests.component.fake_github import FakeResponse

        class _NoJson(FakeGitHub):
            def request(self, method, url, **kw):
                super().request(method, url, **kw)
                return FakeResponse(201, payload)

        assert _client(_NoJson()).post_comment(7, "body") == {}
