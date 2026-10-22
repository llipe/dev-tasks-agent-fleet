"""
S-205 (#407) — GitHub client with a write allowlist.

Covers TC-205-01..15 and CT-04 of the compliance test plan
(``workstream/test-plan-prd-code-review-agent.md`` §4.2, §6) and the S-205 rows
of the security-negative index (SN-01..SN-04). Every test drives the client
through ``StubTransport``; nothing touches the network.

AC mapping (story S-205): AC-1 -> ``test_method_*``/``test_paging_*``/
``test_contents_*``/``test_timeout_*``; AC-2 -> ``test_forbidden_*``/
``test_allowlist_*``; AC-3 -> ``test_retry_*``; AC-4 -> ``test_error_mapping_*``/
``test_no_token_*``; AC-5 -> ``test_encoding_*``/``test_static_*``.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
import requests

import github_client
from github_client import (
    ALLOWLIST,
    API_VERSION,
    MAX_FILE_PAGES,
    MAX_WAIT_SECONDS,
    Comparison,
    DirEntry,
    ForbiddenCall,
    GitHubApiError,
    GitHubClient,
    GitHubError,
    GitHubNotFound,
    GitHubPermissionDenied,
    Issue,
    PostedComment,
    PullFile,
    PullRequest,
)
from tests.helpers.github_stub import (
    StubTransport,
    fixture_json,
    json_response,
    load_fixture,
    text_response,
)

PKG = Path(__file__).resolve().parents[2]

TOKEN = "ghs_SENTINEL0123456789abcdefTOKEN"
ORG, REPO, PR = "acme", "widgets", 42
R = f"/repos/{ORG}/{REPO}"
HEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d"
BASE = "3a5c7e9b1d3f5a7c9e1b3d5f7a9c1e3b5d7f9a1c"
MERGE_BASE = "7e1d3c5b9a8f6e4d2c0b1a3f5e7d9c8b6a4f2e0d"


class Sleeper:
    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def make_client(transport: StubTransport | None = None, **kw) -> tuple[GitHubClient, Sleeper]:
    sleeper = kw.pop("sleep", None) or Sleeper()
    client = GitHubClient(
        TOKEN,
        ORG,
        REPO,
        PR,
        transport=transport if transport is not None else StubTransport(),
        sleep=sleeper,
        clock=kw.pop("clock", lambda: 1_000_000.0),
        **kw,
    )
    return client, sleeper


@pytest.fixture
def sample():
    stub = load_fixture("sample-pr")
    client, sleeper = make_client(stub)
    return client, stub, sleeper


# ---------------------------------------------------------------------------
# CT-04 — allowlist snapshot equals spec §6.2 exactly
# ---------------------------------------------------------------------------

SPEC_6_2 = (
    ("GET", "/repos/{o}/{r}/pulls/{n}"),
    ("GET", "/repos/{o}/{r}/pulls/{n}/files"),
    ("GET", "/repos/{o}/{r}/compare/{base_sha}...{head_sha}"),
    ("GET", "/repos/{o}/{r}/contents/{path}"),
    ("GET", "/repos/{o}/{r}/contents/{dir}"),
    ("GET", "/repos/{o}/{r}/issues/{m}"),
    ("POST", "/repos/{o}/{r}/issues/{n}/comments"),
)


def test_allowlist_snapshot_equals_spec_6_2():
    assert tuple((e.method, e.template) for e in ALLOWLIST) == SPEC_6_2


def test_allowlist_has_exactly_one_write():
    writes = [e for e in ALLOWLIST if e.method != "GET"]
    assert [(e.method, e.template) for e in writes] == [
        ("POST", "/repos/{o}/{r}/issues/{n}/comments")
    ]


def test_allowlist_has_no_wildcards():
    for entry in ALLOWLIST:
        assert "*" not in entry.template
        assert ".*" not in entry.template
        assert entry.method in {"GET", "POST"}


def test_allowlist_is_immutable():
    assert isinstance(ALLOWLIST, tuple)
    with pytest.raises(AttributeError):
        ALLOWLIST[0].method = "PUT"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TC-205-01 — each method issues exactly the spec §6.2 method, path, headers
# ---------------------------------------------------------------------------


def _assert_common_headers(call, accept="application/vnd.github+json"):
    assert call.headers["Authorization"] == f"Bearer {TOKEN}"
    assert call.headers["Accept"] == accept
    assert call.headers["X-GitHub-Api-Version"] == API_VERSION
    assert call.url.startswith("https://api.github.com/")
    assert call.allow_redirects is False


def test_method_get_pull(sample):
    client, stub, _ = sample
    pull = client.get_pull()
    assert isinstance(pull, PullRequest)
    (call,) = stub.calls
    assert (call.method, call.path, call.params) == ("GET", f"{R}/pulls/42", {})
    _assert_common_headers(call)
    assert pull.number == 42
    assert pull.state == "open"
    assert pull.merged is False
    assert pull.draft is False
    assert pull.head_sha == HEAD
    assert pull.head_ref == "issue/41-widget-sizes"
    assert pull.base_sha == BASE
    assert pull.base_ref == "main"
    assert pull.title == "feat(widgets): add widget sizes"
    assert pull.body.startswith("Closes #41")


def test_method_list_pull_files(sample):
    client, stub, _ = sample
    result = client.list_pull_files()
    (call,) = stub.calls
    assert (call.method, call.path) == ("GET", f"{R}/pulls/42/files")
    assert call.params == {"per_page": 100, "page": 1}
    _assert_common_headers(call)
    assert result.truncated is False
    names = [f.filename for f in result.files]
    assert names == [
        "src/app.py",
        "docs/notes with space.md",
        "src/new_name.py",
        "pnpm-lock.yaml",
        "assets/logo.png",
    ]
    renamed = result.files[2]
    assert isinstance(renamed, PullFile)
    assert renamed.status == "renamed"
    assert renamed.previous_filename == "src/old_name.py"
    assert (renamed.additions, renamed.deletions) == (1, 1)
    assert result.files[4].patch is None
    assert result.files[0].previous_filename is None


def test_method_compare(sample):
    client, stub, _ = sample
    cmp = client.compare(BASE, HEAD)
    assert cmp == Comparison(merge_base_sha=MERGE_BASE)
    (call,) = stub.calls
    assert (call.method, call.path) == ("GET", f"{R}/compare/{BASE}...{HEAD}")
    _assert_common_headers(call)


def test_method_get_content_raw_uses_raw_media_type_and_ref(sample):
    client, stub, _ = sample
    text = client.get_content_raw("src/app.py", HEAD)
    assert text == fixture_text("app_py_head.txt")
    (call,) = stub.calls
    assert (call.method, call.path) == ("GET", f"{R}/contents/src/app.py")
    assert call.params == {"ref": HEAD}
    _assert_common_headers(call, accept="application/vnd.github.raw")


def test_method_get_content_raw_at_merge_base(sample):
    client, _, _ = sample
    assert client.get_content_raw("src/app.py", MERGE_BASE) == fixture_text("app_py_base.txt")


def test_method_list_dir(sample):
    client, stub, _ = sample
    entries = client.list_dir("docs/adr", HEAD)
    (call,) = stub.calls
    assert (call.method, call.path, call.params) == ("GET", f"{R}/contents/docs/adr", {"ref": HEAD})
    _assert_common_headers(call)
    assert entries == [
        DirEntry("ADR-001-use-python.md", "docs/adr/ADR-001-use-python.md", "file"),
        DirEntry("ADR-002-sizes.md", "docs/adr/ADR-002-sizes.md", "file"),
        DirEntry("drafts", "docs/adr/drafts", "dir"),
    ]


def test_method_get_issue(sample):
    client, stub, _ = sample
    issue = client.get_issue(41)
    assert isinstance(issue, Issue)
    (call,) = stub.calls
    assert (call.method, call.path) == ("GET", f"{R}/issues/41")
    _assert_common_headers(call)
    assert issue.number == 41
    assert issue.labels == ("prd:widgets", "type:feature")
    assert issue.is_pull_request is False


def test_method_get_issue_flags_a_pull_request(sample):
    client, _, _ = sample
    issue = client.get_issue(40)
    assert issue.is_pull_request is True
    assert issue.body == ""  # body: null -> ""


def test_method_post_pr_comment(sample):
    client, stub, _ = sample
    posted = client.post_pr_comment("## Code review: **clear**")
    assert posted == PostedComment(
        id=2000001, html_url="https://github.com/acme/widgets/pull/42#issuecomment-2000001"
    )
    (call,) = stub.calls
    assert (call.method, call.path) == ("POST", f"{R}/issues/42/comments")
    assert call.json == {"body": "## Code review: **clear**"}
    _assert_common_headers(call)


def fixture_text(name: str) -> str:
    return (PKG / "tests" / "fixtures" / "github" / "sample-pr" / name).read_text()


# ---------------------------------------------------------------------------
# TC-205-02 — paging (per_page=100, <= 30 pages, truncation reported)
# ---------------------------------------------------------------------------


def _file(i: int) -> dict:
    return {"filename": f"f{i}.py", "status": "modified", "additions": 1, "deletions": 0}


def test_paging_follows_pages_until_a_short_page():
    stub = StubTransport()
    for page in (1, 2):
        stub.add(
            ("GET", f"{R}/pulls/42/files", (("page", str(page)), ("per_page", "100"))),
            json_response([_file(i) for i in range(100)]),
        )
    stub.add(
        ("GET", f"{R}/pulls/42/files", (("page", "3"), ("per_page", "100"))),
        json_response([_file(i) for i in range(7)]),
    )
    client, _ = make_client(stub)
    result = client.list_pull_files()
    assert len(result.files) == 207
    assert result.truncated is False
    assert [c.params["page"] for c in stub.calls] == [1, 2, 3]


def test_paging_stops_at_30_pages_and_reports_truncation():
    stub = StubTransport({("GET", f"{R}/pulls/42/files"): json_response([_file(0)] * 100)})
    client, _ = make_client(stub)
    result = client.list_pull_files()
    assert MAX_FILE_PAGES == 30
    assert len(stub.calls) == 30  # no 31st request
    assert len(result.files) == 3000
    assert result.truncated is True


def test_paging_empty_first_page():
    stub = StubTransport({("GET", f"{R}/pulls/42/files"): json_response([])})
    client, _ = make_client(stub)
    result = client.list_pull_files()
    assert result.files == ()
    assert result.truncated is False


def test_paging_non_list_page_is_api_error():
    stub = StubTransport({("GET", f"{R}/pulls/42/files"): json_response({"message": "x"})})
    client, _ = make_client(stub)
    with pytest.raises(GitHubApiError):
        client.list_pull_files()


# ---------------------------------------------------------------------------
# TC-205-03 — contents 404 -> None; list_dir 404 -> []; empty 200 -> ""
# ---------------------------------------------------------------------------


def test_contents_404_is_none(sample):
    client, _, _ = sample
    assert client.get_content_raw("workstream/specification-prd-widgets.md", HEAD) is None


def test_contents_list_dir_404_is_empty(sample):
    client, _, _ = sample
    assert client.list_dir("workstream", HEAD) == []


def test_contents_empty_200_is_empty_string_not_none():
    stub = StubTransport({("GET", f"{R}/contents/empty.txt"): text_response("")})
    client, _ = make_client(stub)
    assert client.get_content_raw("empty.txt", HEAD) == ""


def test_contents_invalid_utf8_is_replaced_not_raised():
    from tests.helpers.github_stub import StubResponse

    stub = StubTransport({("GET", f"{R}/contents/bin.dat"): StubResponse(200, b"\x00\xffok")})
    client, _ = make_client(stub)
    assert client.get_content_raw("bin.dat", HEAD) == "\x00�ok"


def test_contents_list_dir_on_a_file_is_empty():
    stub = StubTransport(
        {("GET", f"{R}/contents/README.md"): json_response({"type": "file", "name": "README.md"})}
    )
    client, _ = make_client(stub)
    assert client.list_dir("README.md", HEAD) == []


# ---------------------------------------------------------------------------
# TC-205-04 — disallowed verbs/paths raise ForbiddenCall before transport
# ---------------------------------------------------------------------------

FORBIDDEN = [
    ("PUT", f"{R}/pulls/42/merge"),
    ("POST", f"{R}/pulls/42/reviews"),
    ("POST", f"{R}/pulls/42/reviews/9/events"),
    ("POST", f"{R}/pulls/42/requested_reviewers"),
    ("POST", f"{R}/issues/42/labels"),
    ("PATCH", f"{R}/issues/comments/9"),
    ("DELETE", f"{R}/issues/comments/9"),
    ("POST", f"{R}/issues"),
    ("POST", f"{R}/pulls"),
    ("PATCH", f"{R}/pulls/42"),
    ("PUT", f"{R}/contents/src/app.py"),
    ("POST", f"{R}/git/refs"),
    ("POST", f"{R}/check-runs"),
    ("POST", f"{R}/statuses/{HEAD}"),
    ("POST", "/graphql"),
    ("DELETE", f"{R}/pulls/42"),
    ("DELETE", f"{R}/issues/42/comments"),
    ("DELETE", f"{R}/contents/src/app.py"),
    ("POST", f"{R}/pulls/42/merge"),
    ("POST", f"{R}/issues/42/comments/9"),
    ("POST", f"{R}/pulls/42/comments"),
    ("GET", f"{R}/pulls/42/merge"),
    ("GET", f"{R}/pulls/42/reviews"),
    ("GET", f"{R}/issues/42/comments"),
    ("GET", "/user"),
    ("GET", "/installation/repositories"),
    ("HEAD", f"{R}/pulls/42"),
    ("OPTIONS", f"{R}/pulls/42"),
]


@pytest.mark.parametrize(("method", "path"), FORBIDDEN)
def test_forbidden_call_raises_before_transport(method, path):
    stub = StubTransport()
    client, _ = make_client(stub)
    with pytest.raises(ForbiddenCall):
        client._request(method, path)
    assert stub.calls == []


def test_forbidden_call_is_not_a_github_api_error():
    # Callers that catch GitHubError for API failures must not swallow a guard trip.
    assert not issubclass(ForbiddenCall, GitHubError)


# ---------------------------------------------------------------------------
# TC-205-05 — comment only on the invoked PR; bound to org/repo
# ---------------------------------------------------------------------------


def test_forbidden_comment_on_another_issue():
    stub = StubTransport()
    client, _ = make_client(stub)
    for other in (41, 43, 1, 420):
        with pytest.raises(ForbiddenCall):
            client._request("POST", f"{R}/issues/{other}/comments", json={"body": "x"})
    assert stub.calls == []


def test_forbidden_post_pr_comment_takes_no_number():
    params = list(inspect.signature(GitHubClient.post_pr_comment).parameters)
    assert params == ["self", "body"]


@pytest.mark.parametrize(
    "path",
    [
        "/repos/other/x/pulls/42",
        "/repos/other/widgets/pulls/42",
        "/repos/acme/other/pulls/42",
        "/repos/ACME/widgets/pulls/42",
        "/repos/other/x/issues/42/comments",
        "/repos/other/x/contents/README.md",
    ],
)
def test_forbidden_other_repository_even_for_get(path):
    stub = StubTransport()
    client, _ = make_client(stub)
    method = "POST" if path.endswith("/comments") else "GET"
    with pytest.raises(ForbiddenCall):
        client._request(method, path)
    assert stub.calls == []


def test_forbidden_reads_of_another_pull():
    stub = StubTransport()
    client, _ = make_client(stub)
    for path in (f"{R}/pulls/41", f"{R}/pulls/43/files"):
        with pytest.raises(ForbiddenCall):
            client._request("GET", path)
    assert stub.calls == []


@pytest.mark.parametrize(
    ("org", "repo", "pr"),
    [
        ("acme/evil", "widgets", 1),
        ("acme", "../x", 1),
        ("acme", "w", 0),
        ("acme", "w", -1),
        ("acme", "w", True),
        ("", "w", 1),
        ("acme", "", 1),
        ("acme", "..", 1),
    ],
)
def test_forbidden_constructor_rejects_bad_binding(org, repo, pr):
    with pytest.raises(ValueError):
        GitHubClient(TOKEN, org, repo, pr, transport=StubTransport())


def test_forbidden_constructor_rejects_empty_token():
    with pytest.raises(ValueError):
        GitHubClient("", ORG, REPO, PR, transport=StubTransport())


# ---------------------------------------------------------------------------
# TC-205-06 — anchored, normalized template matching
# ---------------------------------------------------------------------------

SMUGGLED = [
    ("POST", f"{R}/issues/42/comments/../../../pulls/42/merge"),
    ("GET", f"{R}/issues/42/comments/../../../pulls/42/merge"),
    ("GET", f"{R}/contents/src/../../../pulls/42/merge"),
    ("GET", f"{R}/contents/%2e%2e/%2e%2e/pulls/42"),
    ("GET", f"{R}/contents/%2E%2E/x"),
    ("GET", f"{R}/contents/./x"),
    ("GET", f"{R}/contents/a%2Fb"),
    ("POST", f"{R}/issues/42/comments?x=/comments"),
    ("GET", f"{R}/pulls/42?x=/comments"),
    ("GET", f"{R}/pulls/42#frag"),
    ("POST", f"{R}/issues/42/comments/"),
    ("GET", f"{R}/pulls/42/"),
    ("GET", f"{R}//pulls/42"),
    ("post", f"{R}/issues/42/comments"),
    ("Get", f"{R}/pulls/42"),
    ("POST", f"https://evil.example{R}/issues/42/comments"),
    ("GET", f"https://api.github.com{R}/pulls/42"),
    ("GET", f"http://api.github.com{R}/pulls/42"),
    ("GET", f"//evil.example{R}/pulls/42"),
    ("GET", f"repos/{ORG}/{REPO}/pulls/42"),
    ("GET", f"{R}/pulls/042"),
    ("GET", f"{R}/pulls/+42"),
    ("GET", f"{R}/issues/0"),
    ("GET", f"{R}/issues/-1"),
    ("GET", f"{R}/issues/1e3"),
    ("GET", f"{R}/contents/src/a b.py"),
    ("GET", f"{R}/contents/src/a\nb.py"),
    ("GET", f"{R}/contents/%zz"),
    ("GET", f"{R}/compare/{BASE}..{HEAD}"),
    ("GET", f"{R}/compare/main...{HEAD}"),
    ("GET", f"{R}/compare/{BASE}...{HEAD}/x"),
    ("GET", f"{R}/contents"),
]


@pytest.mark.parametrize(("method", "path"), SMUGGLED)
def test_forbidden_smuggled_paths(method, path):
    stub = StubTransport()
    client, _ = make_client(stub)
    with pytest.raises(ForbiddenCall):
        client._request(method, path)
    assert stub.calls == []


def test_forbidden_unknown_query_keys():
    stub = StubTransport()
    client, _ = make_client(stub)
    with pytest.raises(ForbiddenCall):
        client._request("GET", f"{R}/pulls/42", params={"ref": HEAD})
    with pytest.raises(ForbiddenCall):
        client._request("POST", f"{R}/issues/42/comments", params={"x": "1"}, json={"body": "b"})
    with pytest.raises(ForbiddenCall):
        client._request("GET", f"{R}/contents/a.py", params={"ref": HEAD, "url": "x"})
    assert stub.calls == []


def test_forbidden_guard_message_carries_no_token():
    client, _ = make_client()
    with pytest.raises(ForbiddenCall) as exc_info:
        client._request("PUT", f"{R}/pulls/42/merge")
    assert TOKEN not in str(exc_info.value)
    assert TOKEN not in repr(exc_info.value)


# ---------------------------------------------------------------------------
# TC-205-08 — GET retries twice on 5xx / connection errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_retry_get_5xx_three_attempts_then_api_error(status):
    stub = StubTransport({("GET", f"{R}/pulls/42"): json_response({"m": 1}, status=status)})
    client, sleeper = make_client(stub)
    with pytest.raises(GitHubApiError) as exc_info:
        client.get_pull()
    assert len(stub.calls) == 3
    assert len(sleeper.waits) == 2
    assert all(0 < w <= MAX_WAIT_SECONDS for w in sleeper.waits)
    assert exc_info.value.status == status
    assert exc_info.value.code == "GITHUB_API_ERROR"


@pytest.mark.parametrize(
    "exc",
    [requests.ConnectionError("boom"), requests.Timeout("slow"), requests.ReadTimeout("slow")],
)
def test_retry_get_connection_error_three_attempts_then_api_error(exc):
    stub = StubTransport({("GET", f"{R}/pulls/42"): exc})
    client, sleeper = make_client(stub)
    with pytest.raises(GitHubApiError) as exc_info:
        client.get_pull()
    assert len(stub.calls) == 3
    assert len(sleeper.waits) == 2
    assert exc_info.value.status is None


def test_retry_get_success_on_second_attempt(sample):
    _, fixture_stub, _ = sample
    good = fixture_stub.routes[("GET", f"{R}/pulls/42")][0]
    stub = StubTransport({("GET", f"{R}/pulls/42"): [json_response({}, status=502), good]})
    client, sleeper = make_client(stub)
    assert client.get_pull().head_sha == HEAD
    assert len(stub.calls) == 2
    assert len(sleeper.waits) == 1


def test_retry_get_connection_error_then_success():
    stub = StubTransport(
        {
            ("GET", f"{R}/contents/a.py"): [
                requests.ConnectionError("reset"),
                text_response("ok"),
            ]
        }
    )
    client, _ = make_client(stub)
    assert client.get_content_raw("a.py", HEAD) == "ok"
    assert len(stub.calls) == 2


def test_retry_not_on_4xx():
    for status in (400, 404, 409, 410, 422):
        stub = StubTransport({("GET", f"{R}/compare/{BASE}...{HEAD}"): json_response({}, status)})
        client, sleeper = make_client(stub)
        with pytest.raises((GitHubApiError, GitHubNotFound)):
            client.compare(BASE, HEAD)
        assert len(stub.calls) == 1, status
        assert sleeper.waits == []


def test_retry_does_not_wrap_non_transport_exceptions():
    # A programming error inside the transport is not a GitHub failure.
    stub = StubTransport({("GET", f"{R}/pulls/42"): KeyError("bug")})
    client, _ = make_client(stub)
    with pytest.raises(KeyError):
        client.get_pull()
    assert len(stub.calls) == 1


# ---------------------------------------------------------------------------
# TC-205-09 — secondary rate limit vs. permission 403
# ---------------------------------------------------------------------------


def test_retry_secondary_rate_limit_honors_retry_after():
    stub = StubTransport(
        {
            ("GET", f"{R}/issues/41"): [
                json_response(
                    {"message": "You have exceeded a secondary rate limit."},
                    status=403,
                    headers={"retry-after": "5"},
                ),
                json_response({"number": 41, "title": "t", "body": "b", "labels": []}),
            ]
        }
    )
    client, sleeper = make_client(stub)
    assert client.get_issue(41).number == 41
    assert sleeper.waits == [5.0]
    assert len(stub.calls) == 2


def test_retry_after_is_capped_at_30_seconds():
    stub = StubTransport(
        {
            ("GET", f"{R}/pulls/42"): json_response(
                {"message": "secondary rate limit"}, status=403, headers={"Retry-After": "120"}
            )
        }
    )
    client, sleeper = make_client(stub)
    with pytest.raises(GitHubApiError) as exc_info:
        client.get_pull()
    assert MAX_WAIT_SECONDS == 30
    assert sleeper.waits == [30.0, 30.0]
    assert len(stub.calls) == 3
    # Rate-limited to exhaustion is an API error, not a permission denial.
    assert not isinstance(exc_info.value, GitHubPermissionDenied)


def test_retry_secondary_rate_limit_from_body_without_header():
    stub = StubTransport(
        {
            ("GET", f"{R}/pulls/42"): json_response(
                {
                    "message": "You have exceeded a secondary rate limit. Please wait a few "
                    "minutes before you try again."
                },
                status=403,
            )
        }
    )
    client, sleeper = make_client(stub)
    with pytest.raises(GitHubApiError):
        client.get_pull()
    assert len(stub.calls) == 3
    assert all(0 < w <= 30 for w in sleeper.waits)


def test_retry_primary_rate_limit_waits_until_reset_capped():
    now = 1_000_000.0
    stub = StubTransport(
        {
            ("GET", f"{R}/pulls/42"): json_response(
                {"message": "API rate limit exceeded"},
                status=403,
                headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(now) + 12)},
            )
        }
    )
    client, sleeper = make_client(stub, clock=lambda: now)
    with pytest.raises(GitHubApiError):
        client.get_pull()
    assert sleeper.waits == [12.0, 12.0]


def test_retry_429_is_rate_limited():
    stub = StubTransport(
        {("GET", f"{R}/pulls/42"): json_response({}, status=429, headers={"retry-after": "1"})}
    )
    client, sleeper = make_client(stub)
    with pytest.raises(GitHubApiError):
        client.get_pull()
    assert sleeper.waits == [1.0, 1.0]


@pytest.mark.parametrize("bad", ["soon", "-5", "", "nan", "inf"])
def test_retry_after_unparseable_falls_back_within_cap(bad):
    stub = StubTransport(
        {("GET", f"{R}/pulls/42"): json_response({}, status=429, headers={"retry-after": bad})}
    )
    client, sleeper = make_client(stub)
    with pytest.raises(GitHubApiError):
        client.get_pull()
    assert len(sleeper.waits) == 2
    assert all(0 <= w <= 30 for w in sleeper.waits)


def test_retry_not_on_permission_403():
    stub = StubTransport(
        {
            ("GET", f"{R}/issues/41"): json_response(
                {"message": "Resource not accessible by integration"}, status=403
            )
        }
    )
    client, sleeper = make_client(stub)
    with pytest.raises(GitHubPermissionDenied):
        client.get_issue(41)
    assert len(stub.calls) == 1
    assert sleeper.waits == []


# ---------------------------------------------------------------------------
# TC-205-10 — POST never retries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome",
    [
        json_response({}, status=500),
        json_response({}, status=502),
        json_response(
            {"message": "secondary rate limit"}, status=403, headers={"retry-after": "1"}
        ),
        json_response({}, status=429, headers={"retry-after": "1"}),
        requests.ConnectionError("reset"),
        requests.ReadTimeout("read timed out"),
    ],
)
def test_retry_never_on_post(outcome):
    stub = StubTransport({("POST", f"{R}/issues/42/comments"): outcome})
    client, sleeper = make_client(stub)
    with pytest.raises(GitHubApiError):
        client.post_pr_comment("body")
    assert len(stub.calls) == 1
    assert sleeper.waits == []


# ---------------------------------------------------------------------------
# TC-205-11 — error mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403])
def test_error_mapping_permission_denied_on_get(status):
    stub = StubTransport({("GET", f"{R}/pulls/42"): json_response({"message": "no"}, status)})
    client, _ = make_client(stub)
    with pytest.raises(GitHubPermissionDenied) as exc_info:
        client.get_pull()
    assert exc_info.value.status == status
    assert exc_info.value.code == "GITHUB_PERMISSION_DENIED"


@pytest.mark.parametrize("status", [401, 403])
def test_error_mapping_permission_denied_on_post(status):
    stub = StubTransport({("POST", f"{R}/issues/42/comments"): json_response({}, status)})
    client, _ = make_client(stub)
    with pytest.raises(GitHubPermissionDenied):
        client.post_pr_comment("b")
    assert len(stub.calls) == 1


@pytest.mark.parametrize("status", [401, 403])
def test_error_mapping_permission_denied_on_contents(status):
    stub = StubTransport({("GET", f"{R}/contents/a.py"): json_response({}, status)})
    client, _ = make_client(stub)
    with pytest.raises(GitHubPermissionDenied):
        client.get_content_raw("a.py", HEAD)


def test_error_mapping_get_pull_404_is_not_found():
    stub = StubTransport({("GET", f"{R}/pulls/42"): json_response({"message": "Not Found"}, 404)})
    client, _ = make_client(stub)
    with pytest.raises(GitHubNotFound) as exc_info:
        client.get_pull()
    assert exc_info.value.status == 404
    assert exc_info.value.code == "GITHUB_NOT_FOUND"
    assert not isinstance(exc_info.value, GitHubApiError)
    assert not isinstance(exc_info.value, GitHubPermissionDenied)


def test_error_mapping_get_issue_and_compare_404_are_not_found():
    stub = StubTransport(
        {
            ("GET", f"{R}/issues/7"): json_response({}, 404),
            ("GET", f"{R}/compare/{BASE}...{HEAD}"): json_response({}, 404),
        }
    )
    client, _ = make_client(stub)
    with pytest.raises(GitHubNotFound):
        client.get_issue(7)
    with pytest.raises(GitHubNotFound):
        client.compare(BASE, HEAD)


@pytest.mark.parametrize("status", [400, 409, 410, 422, 451])
def test_error_mapping_other_4xx_is_api_error(status):
    stub = StubTransport({("GET", f"{R}/pulls/42"): json_response({}, status)})
    client, _ = make_client(stub)
    with pytest.raises(GitHubApiError) as exc_info:
        client.get_pull()
    assert exc_info.value.status == status


def test_error_mapping_post_404_and_422_are_api_errors():
    for status in (404, 422):
        stub = StubTransport({("POST", f"{R}/issues/42/comments"): json_response({}, status)})
        client, _ = make_client(stub)
        with pytest.raises(GitHubApiError):
            client.post_pr_comment("b")


@pytest.mark.parametrize("status", [301, 302, 307])
def test_error_mapping_redirect_is_not_followed(status):
    stub = StubTransport(
        {
            ("GET", f"{R}/pulls/42"): json_response(
                {}, status, headers={"Location": "https://evil.example/x"}
            )
        }
    )
    client, _ = make_client(stub)
    with pytest.raises(GitHubApiError):
        client.get_pull()
    assert len(stub.calls) == 1


def test_error_mapping_invalid_json_is_api_error():
    from tests.helpers.github_stub import StubResponse

    stub = StubTransport({("GET", f"{R}/pulls/42"): StubResponse(200, b"<html>oops")})
    client, _ = make_client(stub)
    with pytest.raises(GitHubApiError):
        client.get_pull()


def test_error_mapping_errors_carry_spec_13_codes():
    assert GitHubPermissionDenied.code == "GITHUB_PERMISSION_DENIED"
    assert GitHubApiError.code == "GITHUB_API_ERROR"
    assert issubclass(GitHubPermissionDenied, GitHubError)
    assert issubclass(GitHubApiError, GitHubError)
    assert not issubclass(GitHubPermissionDenied, GitHubApiError)


# ---------------------------------------------------------------------------
# TC-205-12 — no token text anywhere in raised errors
# ---------------------------------------------------------------------------


def _chain(exc: BaseException):
    seen = []
    cur: BaseException | None = exc
    while cur is not None and cur not in seen:
        seen.append(cur)
        cur = cur.__cause__ or cur.__context__
    return seen


def _assert_clean(exc: BaseException):
    for link in _chain(exc):
        for text in (str(link), repr(link), *(repr(a) for a in link.args)):
            assert TOKEN not in text
            assert "Authorization" not in text
            assert "Bearer" not in text


ECHO = {"message": f"Bad credentials for token {TOKEN}", "Authorization": f"Bearer {TOKEN}"}


@pytest.mark.parametrize(
    ("method", "outcome"),
    [
        ("GET", json_response(ECHO, 401)),
        ("GET", json_response(ECHO, 403)),
        ("GET", json_response(ECHO, 422)),
        ("GET", json_response(ECHO, 500)),
        ("GET", json_response(ECHO, 404)),
        ("GET", text_response(f"not json {TOKEN}", 200)),
        ("GET", requests.ConnectionError(f"proxy said Bearer {TOKEN}")),
        ("POST", json_response(ECHO, 401)),
        ("POST", json_response(ECHO, 500)),
        ("POST", requests.ReadTimeout(f"Authorization: Bearer {TOKEN}")),
    ],
)
def test_no_token_in_any_raised_error(method, outcome):
    if method == "GET":
        stub = StubTransport({("GET", f"{R}/pulls/42"): outcome})
        client, _ = make_client(stub)
        call = client.get_pull
    else:
        stub = StubTransport({("POST", f"{R}/issues/42/comments"): outcome})
        client, _ = make_client(stub)

        def call():
            return client.post_pr_comment("b")

    with pytest.raises(GitHubError) as exc_info:
        call()
    _assert_clean(exc_info.value)


def test_no_token_in_client_repr():
    client, _ = make_client()
    assert TOKEN not in repr(client)
    assert TOKEN not in str(client)


def test_no_token_in_malformed_response_error():
    stub = StubTransport({("GET", f"{R}/pulls/42"): json_response({"token": TOKEN})})
    client, _ = make_client(stub)
    with pytest.raises(GitHubApiError) as exc_info:
        client.get_pull()
    _assert_clean(exc_info.value)


# ---------------------------------------------------------------------------
# TC-205-13 — per-segment URL encoding, prefix cannot be escaped
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "encoded"),
    [
        ("src/a b.py", "src/a%20b.py"),
        ("a#b.py", "a%23b.py"),
        ("a?b.py", "a%3Fb.py"),
        ("ñ.py", "%C3%B1.py"),
        ("dir/%2F.py", "dir/%252F.py"),
        ("docs/notes with space.md", "docs/notes%20with%20space.md"),
        ("a+b&c=d;e.py", "a%2Bb%26c%3Dd%3Be.py"),
        ("x/..y/z..", "x/..y/z.."),
        (".github/workflows/ci.yml", ".github/workflows/ci.yml"),
    ],
)
def test_encoding_per_segment(path, encoded):
    stub = StubTransport({("GET", f"{R}/contents/{encoded}"): text_response("ok")})
    client, _ = make_client(stub)
    assert client.get_content_raw(path, HEAD) == "ok"
    (call,) = stub.calls
    assert call.path == f"{R}/contents/{encoded}"
    assert call.path.startswith(f"{R}/contents/")


def test_encoding_fixture_path_with_space(sample):
    client, stub, _ = sample
    assert client.get_content_raw("docs/notes with space.md", HEAD) == fixture_text("notes_head.md")
    assert stub.calls[0].path == f"{R}/contents/docs/notes%20with%20space.md"


@pytest.mark.parametrize(
    "path",
    [
        "../../pulls/42/merge",
        "src/../../../pulls/42",
        "./x",
        "a/./b",
        "a/..",
        "..",
        "",
        "/abs",
        "trailing/",
        "a//b",
    ],
)
def test_encoding_dot_segments_and_empty_paths_cannot_escape(path):
    stub = StubTransport()
    client, _ = make_client(stub)
    with pytest.raises(ForbiddenCall):
        client.get_content_raw(path, HEAD)
    with pytest.raises(ForbiddenCall):
        client.list_dir(path, HEAD)
    assert stub.calls == []


@pytest.mark.parametrize("ref", ["", "a\nb", "x" * 300])
def test_encoding_bad_ref_is_rejected(ref):
    stub = StubTransport()
    client, _ = make_client(stub)
    with pytest.raises(ForbiddenCall):
        client.get_content_raw("a.py", ref)
    assert stub.calls == []


def test_encoding_branch_ref_with_slash_is_a_query_value():
    stub = StubTransport({("GET", f"{R}/contents/a.py"): text_response("ok")})
    client, _ = make_client(stub)
    assert client.get_content_raw("a.py", "issue/41-widget-sizes") == "ok"
    assert stub.calls[0].params == {"ref": "issue/41-widget-sizes"}


@pytest.mark.parametrize(
    ("base", "head"),
    [
        ("main", HEAD),
        (BASE, "x" * 40),
        (BASE, ""),
        (f"{BASE}/..", HEAD),
        (BASE, HEAD.upper() + "g"),
    ],
)
def test_encoding_compare_requires_hex_shas(base, head):
    stub = StubTransport()
    client, _ = make_client(stub)
    with pytest.raises(ForbiddenCall):
        client.compare(base, head)
    assert stub.calls == []


@pytest.mark.parametrize("number", [0, -1, True, 1.5, "41"])
def test_encoding_get_issue_requires_positive_int(number):
    stub = StubTransport()
    client, _ = make_client(stub)
    with pytest.raises(ForbiddenCall):
        client.get_issue(number)  # type: ignore[arg-type]
    assert stub.calls == []


# ---------------------------------------------------------------------------
# TC-205-15 — every request has an explicit, finite timeout (DF-14)
# ---------------------------------------------------------------------------


def test_timeout_passed_on_every_request(sample):
    client, stub, _ = sample
    client.get_pull()
    client.list_pull_files()
    client.compare(BASE, HEAD)
    client.get_content_raw("src/app.py", HEAD)
    client.list_dir("docs/adr", HEAD)
    client.get_issue(41)
    client.post_pr_comment("b")
    assert len(stub.calls) == 7
    for call in stub.calls:
        assert call.timeout is not None
        parts = call.timeout if isinstance(call.timeout, tuple) else (call.timeout,)
        assert all(0 < float(p) <= 60 for p in parts), call.timeout


def test_timeout_is_configurable():
    stub = StubTransport({("GET", f"{R}/pulls/42"): json_response({}, 500)})
    client, _ = make_client(stub, timeout=(1.0, 2.0))
    with pytest.raises(GitHubApiError):
        client.get_pull()
    assert {c.timeout for c in stub.calls} == {(1.0, 2.0)}


@pytest.mark.parametrize("bad", [None, 0, -1, (5.0, None), (0, 5), float("inf")])
def test_timeout_must_be_finite_and_positive(bad):
    with pytest.raises(ValueError):
        GitHubClient(TOKEN, ORG, REPO, PR, transport=StubTransport(), timeout=bad)


def test_timeout_hung_get_surfaces_as_api_error_not_a_hang():
    stub = StubTransport({("GET", f"{R}/pulls/42"): requests.ReadTimeout("read timed out")})
    client, sleeper = make_client(stub)
    with pytest.raises(GitHubApiError):
        client.get_pull()
    # Bounded: 3 attempts, 2 capped waits.
    assert len(stub.calls) == 3
    assert sum(sleeper.waits) <= 2 * MAX_WAIT_SECONDS


def test_timeout_default_transport_is_a_requests_session():
    client = GitHubClient(TOKEN, ORG, REPO, PR)
    assert isinstance(client._transport, requests.Session)


# ---------------------------------------------------------------------------
# TC-205-07 / TC-205-14 — static scans
# ---------------------------------------------------------------------------


def _package_sources():
    for path in PKG.rglob("*.py"):
        rel = path.relative_to(PKG)
        if rel.parts[0] in {".venv", "build", "dist", "tests"}:
            continue
        yield rel, path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    return mods


def test_static_only_three_modules_import_http_libraries():
    allowed = {"github_client.py", "credentials.py", "agent_reporter.py"}
    offenders = [
        str(rel)
        for rel, path in _package_sources()
        if _imports(path) & {"requests", "urllib3", "httpx", "http", "urllib"}
        and str(rel) not in allowed
    ]
    assert offenders == []


def test_static_api_github_com_only_in_client_and_token_exchange():
    """No module except ``github_client.py`` targets ``api.github.com``.

    ``credentials.py`` (copied from the sibling, D-20) is the one exception: its
    App-JWT -> installation-token exchange must reach GitHub before any client
    exists. Its single occurrence is pinned to that endpoint so it cannot grow.
    """
    for rel, path in _package_sources():
        text = path.read_text()
        if "api.github.com" not in text or str(rel) == "github_client.py":
            continue
        assert str(rel) == "credentials.py", rel
        lines = [ln for ln in text.splitlines() if "api.github.com" in ln]
        assert len(lines) == 1
        assert "/app/installations/{installation_id}/access_tokens" in lines[0]


def _local_io_offenders(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in {"open", "exec", "eval", "Path"}:
                bad.append(fn.id)
            if isinstance(fn, ast.Attribute) and fn.attr in {
                "read_text",
                "read_bytes",
                "write_text",
                "write_bytes",
                "open",
                "system",
                "popen",
            }:
                bad.append(fn.attr)
        if isinstance(node, ast.Import | ast.ImportFrom):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for name in names:
                if name.split(".")[0] in {"os", "pathlib", "subprocess", "shutil", "tempfile"}:
                    bad.append(f"import {name}")
    return bad


def test_static_no_local_filesystem_use_in_client_or_context():
    targets = [PKG / "github_client.py", *sorted((PKG / "context").glob("*.py"))]
    for path in targets:
        assert _local_io_offenders(path) == [], path


def test_static_scan_detects_offenders(tmp_path):
    # Guard the guard: the scanner must flag the patterns it claims to.
    sample = tmp_path / "x.py"
    sample.write_text(
        "import os.path\nimport subprocess\nfrom pathlib import Path\n"
        "open('a')\nPath('a').read_text()\n"
    )
    found = _local_io_offenders(sample)
    assert "import os.path" in found
    assert "import subprocess" in found
    assert "open" in found
    assert "read_text" in found


def test_static_module_exports():
    for name in (
        "GitHubClient",
        "ForbiddenCall",
        "GitHubPermissionDenied",
        "GitHubApiError",
        "GitHubNotFound",
        "ALLOWLIST",
    ):
        assert name in github_client.__all__


def test_static_fixtures_contain_no_real_tokens():
    import re

    pattern = re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")
    for path in (PKG / "tests" / "fixtures" / "github").rglob("*"):
        if path.is_file():
            assert not pattern.search(path.read_text(errors="replace")), path


def test_static_fixture_shape_is_github_shaped():
    pull = fixture_json("sample-pr", "pull.json")
    assert {"number", "state", "merged", "draft", "head", "base", "title", "body"} <= set(pull)


# ---------------------------------------------------------------------------
# Guard and transport edge branches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        requests.TooManyRedirects("loop"),
        requests.exceptions.InvalidURL("bad"),
        requests.RequestException("x"),
    ],
)
def test_retry_not_on_non_transient_request_exception(exc):
    stub = StubTransport({("GET", f"{R}/pulls/42"): exc})
    client, sleeper = make_client(stub)
    with pytest.raises(GitHubApiError) as exc_info:
        client.get_pull()
    assert len(stub.calls) == 1
    assert sleeper.waits == []
    _assert_clean(exc_info.value)


@pytest.mark.parametrize(
    "params",
    [
        {"per_page": True, "page": 1},
        {"per_page": 1.5, "page": 1},
        {"per_page": None, "page": 1},
        {"per_page": 100, "page": 0},
        {"per_page": 100, "page": 10_001},
        {"per_page": -1, "page": 1},
    ],
)
def test_forbidden_query_value_type_and_range(params):
    stub = StubTransport()
    client, _ = make_client(stub)
    with pytest.raises(ForbiddenCall):
        client._request("GET", f"{R}/pulls/42/files", params=params)
    assert stub.calls == []


@pytest.mark.parametrize(("method", "path"), [(None, f"{R}/pulls/42"), ("GET", None), ("GET", 42)])
def test_forbidden_non_string_method_or_path(method, path):
    stub = StubTransport()
    client, _ = make_client(stub)
    with pytest.raises(ForbiddenCall):
        client._request(method, path)  # type: ignore[arg-type]
    assert stub.calls == []


def test_forbidden_non_string_repository_path():
    stub = StubTransport()
    client, _ = make_client(stub)
    with pytest.raises(ForbiddenCall):
        client.get_content_raw(["a"], HEAD)  # type: ignore[arg-type]
    assert stub.calls == []


def test_post_pr_comment_rejects_non_string_body():
    stub = StubTransport()
    client, _ = make_client(stub)
    with pytest.raises(TypeError):
        client.post_pr_comment({"body": "x"})  # type: ignore[arg-type]
    assert stub.calls == []


def test_timeout_scalar_is_accepted():
    stub = StubTransport({("GET", f"{R}/pulls/42"): json_response({}, 422)})
    client, _ = make_client(stub, timeout=7)
    with pytest.raises(GitHubApiError):
        client.get_pull()
    assert stub.calls[0].timeout == 7.0


def test_retry_primary_rate_limit_with_bad_reset_falls_back_within_cap():
    stub = StubTransport(
        {
            ("GET", f"{R}/pulls/42"): json_response(
                {}, 403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "soon"}
            )
        }
    )
    client, sleeper = make_client(stub)
    with pytest.raises(GitHubApiError):
        client.get_pull()
    assert sleeper.waits == [MAX_WAIT_SECONDS, MAX_WAIT_SECONDS]


def test_retry_primary_rate_limit_reset_in_the_past_waits_zero():
    stub = StubTransport(
        {
            ("GET", f"{R}/pulls/42"): json_response(
                {}, 403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "10"}
            )
        }
    )
    client, sleeper = make_client(stub, clock=lambda: 1_000_000.0)
    with pytest.raises(GitHubApiError):
        client.get_pull()
    assert sleeper.waits == [0.0, 0.0]
