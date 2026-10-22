"""
S-205 (#407) — allowlist guard hardening (QA completion gate).

Extends TC-205-06, TC-205-10, TC-205-12 and TC-205-13 (security-negative index
SN-01, SN-03, SN-04) with two things the stub-transport tests cannot show:

1. **Wire-level checks.** ``StubTransport`` records the URL the client hands
   over, not the URL ``requests`` actually sends. These tests drive the client
   through a real ``requests.Session`` with a capturing adapter mounted for
   ``http://`` and ``https://`` (no socket is opened) and assert on the
   ``PreparedRequest``: ``requests``' own requoting must not turn an encoded
   segment back into ``..``, ``/`` or ``\\``, redirects must not be followed,
   and the POST must be sent exactly once.
2. **Bypass variants** not in the example table of ``test_github_client.py``:
   lowercase percent escapes, case variants of the bound org/repo and of the
   host, whitespace around the method, non-ASCII digits, and trailing newlines.

The trailing-newline cases are ``xfail(strict=True)``: the guard regexes use
``$``, which also matches before a final ``\\n``, so a path or SHA ending in a
newline passes the guard. ``requests`` then percent-encodes it as ``%0A`` on the
wire, so it cannot reach another endpoint, but it is a request the allowlist
was meant to refuse. Fix in ``github_client.py`` (``re.fullmatch`` or ``\\Z``);
strict xfail turns red once fixed, so the marker must be removed with the fix.
"""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

import pytest
import requests
from requests.adapters import BaseAdapter

from github_client import ForbiddenCall, GitHubApiError, GitHubClient
from tests.helpers.github_stub import StubTransport

TOKEN = "ghs_SENTINEL0123456789abcdefTOKEN"
ORG, REPO, PR = "acme", "widgets", 42
R = f"/repos/{ORG}/{REPO}"
HEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d"
BASE = "3a5c7e9b1d3f5a7c9e1b3d5f7a9c1e3b5d7f9a1c"

TRAILING_NEWLINE_DEFECT = (
    "guard regexes anchor with '$', which matches before a trailing newline; "
    "github_client.py should use re.fullmatch or \\Z (QA gate finding, S-205)"
)


# ---------------------------------------------------------------------------
# Capturing adapter: a real requests pipeline, no network
# ---------------------------------------------------------------------------


class CaptureAdapter(BaseAdapter):
    """Records each ``PreparedRequest`` and answers from a queue of outcomes."""

    def __init__(self, outcomes: list | None = None) -> None:
        super().__init__()
        self.sent: list[requests.PreparedRequest] = []
        self.outcomes = list(outcomes or [])

    def send(self, request, **kwargs):  # type: ignore[override]
        self.sent.append(request)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else (self.outcomes or [None])[0]
        if isinstance(outcome, BaseException):
            raise outcome
        status, body, headers = outcome if outcome is not None else (200, b"ok", {})
        resp = requests.Response()
        resp.status_code = status
        resp._content = body
        resp.headers.update(headers)
        resp.url = request.url
        resp.request = request
        return resp

    def close(self) -> None:
        pass


def wire_client(adapter: CaptureAdapter, token: str = TOKEN) -> GitHubClient:
    session = requests.Session()
    session.trust_env = False  # no netrc/proxy env leaking into the test
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return GitHubClient(token, ORG, REPO, PR, transport=session, sleep=lambda _s: None)


def _segments(url: str) -> list[str]:
    return urlsplit(url).path.split("/")[1:]


# ---------------------------------------------------------------------------
# Wire level: requests' requoting cannot reopen an escape (TC-205-13, SN-04)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "wire_tail"),
    [
        ("dir/%2F.py", "dir/%252F.py"),
        ("%2e%2e", "%252e%252e"),
        ("%2E%2E/x", "%252E%252E/x"),
        ("a%5Cb", "a%255Cb"),
        ("%252e%252e", "%25252e%25252e"),
        ("ñ.py", "%C3%B1.py"),
        ("src/a b.py", "src/a%20b.py"),
        ("a?b#c.py", "a%3Fb%23c.py"),
        ("x/..y/z..", "x/..y/z.."),
        ("a\nb", "a%0Ab"),
    ],
)
def test_wire_url_stays_under_contents_and_never_decodes_to_a_dot_segment(path, wire_tail):
    adapter = CaptureAdapter()
    client = wire_client(adapter)
    assert client.get_content_raw(path, HEAD) == "ok"
    (sent,) = adapter.sent
    split = urlsplit(sent.url)
    assert split.scheme == "https"
    assert split.netloc == "api.github.com"
    assert split.path == f"{R}/contents/{wire_tail}"
    assert split.query == f"ref={HEAD}"
    for seg in _segments(sent.url):
        decoded = unquote(seg)
        assert decoded not in {".", ".."}
        assert "\\" not in decoded and "/" not in decoded


def test_literal_backslash_in_a_repository_path_fails_closed():
    """Git allows ``\\`` in file names; the guard refuses it (decoded ``\\``).

    Pinned as current behavior: fail closed, before the transport. A caller
    (S-206 context loading) must treat this ``ForbiddenCall`` as "content
    unavailable" rather than let it end the run as ``INTERNAL_ERROR``.
    """
    adapter = CaptureAdapter()
    client = wire_client(adapter)
    with pytest.raises(ForbiddenCall):
        client.get_content_raw("dir/a\\b.py", HEAD)
    assert adapter.sent == []


def test_wire_ref_is_a_query_value_and_cannot_add_parameters():
    adapter = CaptureAdapter()
    client = wire_client(adapter)
    client.get_content_raw("a.py", "main&per_page=1#x")
    (sent,) = adapter.sent
    split = urlsplit(sent.url)
    assert split.path == f"{R}/contents/a.py"
    assert split.query == "ref=main%26per_page%3D1%23x"
    assert split.fragment == ""


def test_wire_redirect_is_not_followed():
    adapter = CaptureAdapter([(302, b"", {"Location": "https://evil.example/steal"})])
    client = wire_client(adapter)
    with pytest.raises(GitHubApiError) as exc_info:
        client.get_pull()
    assert exc_info.value.status == 302
    assert len(adapter.sent) == 1
    assert urlsplit(adapter.sent[0].url).netloc == "api.github.com"


def test_wire_authorization_goes_only_to_the_api_host():
    adapter = CaptureAdapter([(200, b'{"id": 1, "html_url": "https://github.com/x"}', {})])
    client = wire_client(adapter)
    client.post_pr_comment("hi")
    (sent,) = adapter.sent
    assert sent.method == "POST"
    assert sent.url == f"https://api.github.com{R}/issues/{PR}/comments"
    assert sent.headers["Authorization"] == f"Bearer {TOKEN}"


# ---------------------------------------------------------------------------
# Wire level: POST is sent exactly once (TC-205-10)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "first",
    [
        (500, b"{}", {}),
        (502, b"{}", {}),
        (429, b"{}", {"retry-after": "0"}),
        (403, b'{"message": "secondary rate limit"}', {"retry-after": "0"}),
        (403, b"{}", {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"}),
        requests.ConnectionError("reset"),
        requests.ReadTimeout("read timed out"),
        requests.exceptions.ChunkedEncodingError("cut"),
    ],
)
def test_wire_post_is_sent_once_even_when_a_retry_would_succeed(first):
    ok = (201, b'{"id": 1, "html_url": "https://github.com/x"}', {})
    adapter = CaptureAdapter([first, ok])
    client = wire_client(adapter)
    with pytest.raises(GitHubApiError):
        client.post_pr_comment("body")
    assert len(adapter.sent) == 1


# ---------------------------------------------------------------------------
# Wire level: requests' own errors never leak the token (TC-205-12, SN-03)
# ---------------------------------------------------------------------------


def _chain(exc: BaseException) -> list[BaseException]:
    seen: list[BaseException] = []
    cur: BaseException | None = exc
    while cur is not None and cur not in seen:
        seen.append(cur)
        cur = cur.__cause__ or cur.__context__
    return seen


@pytest.mark.parametrize("bad", ["\n", "\r\nX-Injected: 1"])
def test_wire_invalid_header_error_from_requests_carries_no_token(bad):
    # requests raises InvalidHeader with the header value in its message.
    token = TOKEN + bad
    adapter = CaptureAdapter()
    client = wire_client(adapter, token=token)
    with pytest.raises(GitHubApiError) as exc_info:
        client.get_pull()
    assert adapter.sent == []
    for link in _chain(exc_info.value):
        for text in (str(link), repr(link), *(repr(a) for a in link.args)):
            assert TOKEN not in text
            assert "Bearer" not in text
            assert "Authorization" not in text


@pytest.mark.parametrize(
    "exc",
    [
        requests.ConnectionError(f"Authorization: Bearer {TOKEN}"),
        requests.exceptions.SSLError(f"handshake with Bearer {TOKEN}"),
        requests.exceptions.ProxyError(f"proxy echoed {TOKEN}"),
    ],
)
def test_wire_transport_errors_carry_no_token_and_are_not_chained(exc):
    adapter = CaptureAdapter([exc])
    client = wire_client(adapter)
    with pytest.raises(GitHubApiError) as exc_info:
        client.get_pull()
    err = exc_info.value
    assert err.__cause__ is None
    assert err.__context__ is None
    assert TOKEN not in str(err) and TOKEN not in repr(err)


def test_client_attributes_do_not_expose_the_token_publicly():
    client = GitHubClient(TOKEN, ORG, REPO, PR, transport=StubTransport())
    public = {k: v for k, v in vars(client).items() if not k.startswith("_")}
    assert TOKEN not in repr(public)
    assert TOKEN not in f"{client}" and TOKEN not in f"{client!r}"


# ---------------------------------------------------------------------------
# Bypass variants at the guard (TC-205-06, SN-01, SN-02)
# ---------------------------------------------------------------------------

BYPASS = [
    # lowercase / mixed percent escapes of '/', '\', '.'
    ("GET", f"{R}/contents/a%2fb"),
    ("GET", f"{R}/contents/a%5cb"),
    ("GET", f"{R}/contents/a%5Cb"),
    ("GET", f"{R}/contents/%2e"),
    ("GET", f"{R}/contents/%2E%2e"),
    ("GET", f"{R}/contents/x/%2e%2E/y"),
    ("GET", f"{R}/contents/.."),
    ("GET", f"{R}/contents/x/.."),
    ("GET", f"{R}/contents/%"),
    ("GET", f"{R}/contents/%2"),
    # case variants of the bound org, repo, and fixed segments
    ("GET", f"/repos/ACME/{REPO}/pulls/42"),
    ("GET", f"/repos/{ORG}/Widgets/pulls/42"),
    ("POST", f"/repos/Acme/{REPO}/issues/42/comments"),
    ("GET", f"{R}/Pulls/42"),
    ("POST", f"{R}/ISSUES/42/comments"),
    ("POST", f"{R}/issues/42/Comments"),
    ("GET", f"/REPOS/{ORG}/{REPO}/pulls/42"),
    # percent-encoded fixed segments and separators
    ("GET", f"/repos/{ORG}/{REPO}/pulls%2F42"),
    ("GET", f"/repos/{ORG}%2F{REPO}/pulls/42"),
    ("GET", f"/repos/%61cme/{REPO}/pulls/42"),
    ("POST", f"{R}/issues/%34%32/comments"),
    # host / scheme case variants, userinfo, and protocol-relative
    ("GET", f"HTTPS://API.GITHUB.COM{R}/pulls/42"),
    ("GET", f"https://api.github.com.evil.example{R}/pulls/42"),
    ("GET", f"https://user@api.github.com{R}/pulls/42"),
    ("GET", f"//api.github.com{R}/pulls/42"),
    ("GET", f"\\\\evil.example{R}/pulls/42"),
    # method spelling
    ("POST ", f"{R}/issues/42/comments"),
    (" POST", f"{R}/issues/42/comments"),
    ("POST\n", f"{R}/issues/42/comments"),
    ("PoSt", f"{R}/issues/42/comments"),
    ("PUT", f"{R}/issues/42/comments"),
    ("PATCH", f"{R}/issues/42/comments"),
    ("DELETE", f"{R}/issues/42/comments"),
    ("HEAD", f"{R}/pulls/42"),
    ("OPTIONS", f"{R}/pulls/42"),
    ("GET", f"{R}/issues/42/comments"),  # the comment list is not an allowlisted read
    # non-ASCII digits and look-alikes in numeric placeholders
    ("GET", f"{R}/issues/４２"),  # fullwidth 42
    ("GET", f"{R}/issues/٤٢"),  # Arabic-Indic 42
    ("POST", f"{R}/issues/４２/comments"),
    ("GET", f"{R}/issues/42 "),
    ("GET", f"{R}/issues/ 42"),
    ("GET", f"{R}/issues/4\t2"),
    # compare: non-hex, short, uppercase, extra dots
    ("GET", f"{R}/compare/{BASE.upper()}...{HEAD}"),
    ("GET", f"{R}/compare/{BASE[:7]}...{HEAD}"),
    ("GET", f"{R}/compare/{BASE}....{HEAD}"),
    ("GET", f"{R}/compare/{BASE}...{HEAD}...{HEAD}"),
    ("GET", f"{R}/compare/{BASE}%2E%2E%2E{HEAD}"),
    # null byte / control characters outside the contents tail
    ("GET", f"{R}/pulls/42\x00"),
    ("POST", f"{R}/issues/42\r\n/comments"),
]


@pytest.mark.parametrize(("method", "path"), BYPASS)
def test_bypass_variant_raises_before_transport(method, path):
    stub = StubTransport()
    client = GitHubClient(TOKEN, ORG, REPO, PR, transport=stub, sleep=lambda _s: None)
    with pytest.raises(ForbiddenCall):
        client._request(method, path)
    assert stub.calls == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"{R}/issues/7\n"),
        ("GET", f"{R}/contents/a.py\n"),
        ("GET", f"{R}/compare/{BASE}...{HEAD}\n"),
    ],
)
@pytest.mark.xfail(strict=True, reason=TRAILING_NEWLINE_DEFECT)
def test_bypass_trailing_newline_raises_before_transport(method, path):
    stub = StubTransport()  # no routes: a call that gets past the guard fails loudly
    client = GitHubClient(TOKEN, ORG, REPO, PR, transport=stub, sleep=lambda _s: None)
    with pytest.raises(ForbiddenCall):
        client._request(method, path)
    assert stub.calls == []


@pytest.mark.xfail(strict=True, reason=TRAILING_NEWLINE_DEFECT)
def test_bypass_compare_rejects_sha_with_trailing_newline():
    stub = StubTransport()
    client = GitHubClient(TOKEN, ORG, REPO, PR, transport=stub, sleep=lambda _s: None)
    with pytest.raises(ForbiddenCall):
        client.compare(BASE, HEAD + "\n")
    assert stub.calls == []


@pytest.mark.parametrize(("org", "repo"), [(f"{ORG}\n", REPO), (ORG, f"{REPO}\n")])
@pytest.mark.xfail(strict=True, reason=TRAILING_NEWLINE_DEFECT)
def test_bypass_constructor_rejects_binding_with_trailing_newline(org, repo):
    with pytest.raises(ValueError):
        GitHubClient(TOKEN, org, repo, PR, transport=StubTransport())


def test_bypass_trailing_newline_is_percent_encoded_on_the_wire():
    """Bounds the xfail defect above: the newline cannot reach another endpoint."""
    adapter = CaptureAdapter([(200, b'{"merge_base_commit": {"sha": "x"}}', {})])
    client = wire_client(adapter)
    client.compare(BASE, HEAD + "\n")
    (sent,) = adapter.sent
    assert urlsplit(sent.url).path == f"{R}/compare/{BASE}...{HEAD}%0A"
    assert "\n" not in sent.url and "\r" not in sent.url
