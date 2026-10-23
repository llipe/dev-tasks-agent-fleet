"""
GitHub REST client with a write allowlist (S-205, spec §6.2, §9, §12, §13).

Every GitHub call the agent makes goes through ``GitHubClient``. Before a
request is sent, its method and path are checked against ``ALLOWLIST``, the
seven (method, template) pairs of spec §6.2, bound to the constructor's
``org``, ``repo``, and ``pr_number``. Anything else raises ``ForbiddenCall``
and the transport is never touched. The only write is ``post_pr_comment``, a
comment on the invoked PR (PRD FR-27, AC-10).

Retries (spec §9): GETs are retried twice (3 attempts) on 5xx, connection
errors or timeouts, and rate limits (403/429 with ``retry-after``, a "rate
limit" message, or ``x-ratelimit-remaining: 0``). Waits honor ``retry-after``
and are capped at ``MAX_WAIT_SECONDS``. The comment POST is never retried, so a
failure cannot post twice.

Errors (spec §13): 401 and non-rate-limit 403 raise ``GitHubPermissionDenied``.
404 raises ``GitHubNotFound`` for the PR, compare, and issue reads, is ``None``
for file contents and ``[]`` for a directory listing. Everything else raises
``GitHubApiError``. No error carries the token, a header, or a response body,
and none chains the transport exception.

Untrusted repository paths are only ever API path parameters, percent-encoded
per segment; nothing here touches a local filesystem.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote, unquote

import requests

__all__ = [
    "ALLOWLIST",
    "API_VERSION",
    "MAX_FILE_PAGES",
    "MAX_WAIT_SECONDS",
    "AllowedCall",
    "Comparison",
    "DirEntry",
    "ForbiddenCall",
    "GitHubApiError",
    "GitHubClient",
    "GitHubError",
    "GitHubMalformedResponse",
    "GitHubNotFound",
    "GitHubPermissionDenied",
    "Issue",
    "PostedComment",
    "PullFile",
    "PullFiles",
    "PullRequest",
]

API_BASE = "https://api.github.com"
API_VERSION = "2022-11-28"
ACCEPT_JSON = "application/vnd.github+json"
ACCEPT_RAW = "application/vnd.github.raw"
USER_AGENT = "dev-tasks-code-review-agent"

MAX_ATTEMPTS = 3  # one try + two retries (spec §9)
MAX_WAIT_SECONDS = 30.0
BACKOFF_SECONDS = (1.0, 2.0)
RATE_LIMIT_FALLBACK_SECONDS = MAX_WAIT_SECONDS
FILES_PER_PAGE = 100
MAX_FILE_PAGES = 30
DEFAULT_TIMEOUT: tuple[float, float] = (5.0, 30.0)  # (connect, read) seconds; DF-14


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ForbiddenCall(Exception):
    """A request outside ``ALLOWLIST``. Raised before anything is sent.

    Deliberately not a ``GitHubError``: a guard trip is a defect, and a caller
    catching API failures must not swallow it.
    """

    code = "INTERNAL_ERROR"


class GitHubError(Exception):
    """Base for GitHub API failures. ``status`` is the HTTP status, if any."""

    code = "GITHUB_API_ERROR"

    def __init__(self, message: str, *, status: int | None = None) -> None:
        self.status = status
        super().__init__(message)


class GitHubApiError(GitHubError):
    """5xx, network, rate limit after retries, other 4xx, or a malformed body."""

    code = "GITHUB_API_ERROR"


class GitHubMalformedResponse(GitHubApiError):
    """A 2xx response whose body could not be read (not JSON, or a field missing).

    Still a ``GitHubApiError`` for every reader. The comment ``POST`` caller
    tells it apart: the request succeeded, so a comment exists (S-213, QA-213-05).
    """


class GitHubPermissionDenied(GitHubError):
    """401, or a 403 that is not a rate limit."""

    code = "GITHUB_PERMISSION_DENIED"


class GitHubNotFound(GitHubError):
    """404 on a read where absence is meaningful (PR, compare, issue)."""

    code = "GITHUB_NOT_FOUND"


# ---------------------------------------------------------------------------
# Allowlist (spec §6.2) — CT-04 snapshots this exactly
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AllowedCall:
    purpose: str
    method: str
    template: str
    query: frozenset[str] = frozenset()


ALLOWLIST: tuple[AllowedCall, ...] = (
    AllowedCall("load_pr", "GET", "/repos/{o}/{r}/pulls/{n}"),
    AllowedCall(
        "changed_files",
        "GET",
        "/repos/{o}/{r}/pulls/{n}/files",
        frozenset({"per_page", "page"}),
    ),
    AllowedCall("merge_base", "GET", "/repos/{o}/{r}/compare/{base_sha}...{head_sha}"),
    AllowedCall("file_content", "GET", "/repos/{o}/{r}/contents/{path}", frozenset({"ref"})),
    AllowedCall("directory_listing", "GET", "/repos/{o}/{r}/contents/{dir}", frozenset({"ref"})),
    AllowedCall("linked_issue", "GET", "/repos/{o}/{r}/issues/{m}"),
    AllowedCall("post_comment", "POST", "/repos/{o}/{r}/issues/{n}/comments"),
)

_ORG_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
_REPO_RE = re.compile(r"[A-Za-z0-9._-]{1,100}")
_NUMBER_RE = re.compile(r"[1-9][0-9]{0,9}")
_SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
# An already-encoded path segment: unreserved characters or %XX escapes only.
_ENCODED_SEGMENT_RE = re.compile(r"(?:[A-Za-z0-9_.~-]|%[0-9A-Fa-f]{2})+")
_MAX_REF_LEN = 255
_MAX_QUERY_INT = 10_000


def _fits(placeholder: str, segment: str, bound: Mapping[str, str]) -> bool:
    if placeholder in bound:
        return segment == bound[placeholder]
    if placeholder == "m":
        return bool(_NUMBER_RE.fullmatch(segment))
    if placeholder == "base_sha...head_sha":
        base, sep, head = segment.partition("...")
        return bool(sep) and bool(_SHA_RE.fullmatch(base)) and bool(_SHA_RE.fullmatch(head))
    return False  # pragma: no cover - every template placeholder is handled above


def _safe_encoded_segment(segment: str) -> bool:
    if not _ENCODED_SEGMENT_RE.fullmatch(segment):
        return False
    decoded = unquote(segment)
    return decoded not in {".", ".."} and "/" not in decoded and "\\" not in decoded


def _match(path: str, template: str, bound: Mapping[str, str]) -> bool:
    segs = path.split("/")[1:]
    tsegs = template.split("/")[1:]
    if tsegs[-1] in {"{path}", "{dir}"}:
        head, rest = segs[: len(tsegs) - 1], segs[len(tsegs) - 1 :]
        if len(head) != len(tsegs) - 1 or not rest:
            return False
        if not all(_safe_encoded_segment(s) for s in rest):
            return False
        segs, tsegs = head, tsegs[:-1]
    if len(segs) != len(tsegs):
        return False
    for seg, tseg in zip(segs, tsegs, strict=True):
        if tseg.startswith("{"):
            key = "base_sha...head_sha" if "..." in tseg else tseg[1:-1]
            if not _fits(key, seg, bound):
                return False
        elif seg != tseg:
            return False
    return True


# ---------------------------------------------------------------------------
# Typed results (CT-05)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PullRequest:
    number: int
    state: str
    merged: bool
    draft: bool
    title: str
    body: str
    head_sha: str
    head_ref: str
    base_sha: str
    base_ref: str


@dataclass(frozen=True)
class PullFile:
    filename: str
    status: str
    additions: int
    deletions: int
    previous_filename: str | None = None
    patch: str | None = None


@dataclass(frozen=True)
class PullFiles:
    files: tuple[PullFile, ...]
    truncated: bool  # True when page MAX_FILE_PAGES was full


@dataclass(frozen=True)
class Comparison:
    merge_base_sha: str


@dataclass(frozen=True)
class DirEntry:
    name: str
    path: str
    type: str


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    labels: tuple[str, ...]
    is_pull_request: bool


@dataclass(frozen=True)
class PostedComment:
    id: int
    html_url: str


class _Malformed(Exception):
    """Internal: a response field is missing or has the wrong type."""


def _obj(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _Malformed(what)
    return value


def _str(d: Mapping[str, Any], key: str, what: str) -> str:
    value = d.get(key)
    if not isinstance(value, str):
        raise _Malformed(f"{what}.{key}")
    return value


def _opt_str(d: Mapping[str, Any], key: str, what: str) -> str | None:
    value = d.get(key)
    if value is not None and not isinstance(value, str):
        raise _Malformed(f"{what}.{key}")
    return value


def _text(d: Mapping[str, Any], key: str, what: str) -> str:
    """A nullable or absent text field (``body``): ``None`` -> ``""``."""
    return _opt_str(d, key, what) or ""


def _int(d: Mapping[str, Any], key: str, what: str) -> int:
    value = d.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise _Malformed(f"{what}.{key}")
    return value


def _bool(d: Mapping[str, Any], key: str, what: str, default: bool | None = None) -> bool:
    value = d.get(key, default)
    if not isinstance(value, bool):
        raise _Malformed(f"{what}.{key}")
    return value


def _parse_pull(data: Any) -> PullRequest:
    d = _obj(data, "pull")
    head = _obj(d.get("head"), "pull.head")
    base = _obj(d.get("base"), "pull.base")
    return PullRequest(
        number=_int(d, "number", "pull"),
        state=_str(d, "state", "pull"),
        merged=_bool(d, "merged", "pull"),
        draft=_bool(d, "draft", "pull", default=False),
        title=_str(d, "title", "pull"),
        body=_text(d, "body", "pull"),
        head_sha=_str(head, "sha", "pull.head"),
        head_ref=_str(head, "ref", "pull.head"),
        base_sha=_str(base, "sha", "pull.base"),
        base_ref=_str(base, "ref", "pull.base"),
    )


def _parse_file(item: Any) -> PullFile:
    d = _obj(item, "file")
    return PullFile(
        filename=_str(d, "filename", "file"),
        status=_str(d, "status", "file"),
        additions=_int(d, "additions", "file"),
        deletions=_int(d, "deletions", "file"),
        previous_filename=_opt_str(d, "previous_filename", "file"),
        patch=_opt_str(d, "patch", "file"),
    )


def _parse_compare(data: Any) -> Comparison:
    d = _obj(data, "compare")
    mb = _obj(d.get("merge_base_commit"), "compare.merge_base_commit")
    return Comparison(merge_base_sha=_str(mb, "sha", "compare.merge_base_commit"))


def _labels(value: Any) -> tuple[str, ...]:
    """Label names; tolerates strings or objects and skips anything else."""
    if not isinstance(value, list):
        return ()
    names: list[str] = []
    for item in value:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, Mapping) and isinstance(item.get("name"), str):
            names.append(item["name"])
    return tuple(names)


def _parse_issue(data: Any) -> Issue:
    d = _obj(data, "issue")
    return Issue(
        number=_int(d, "number", "issue"),
        title=_str(d, "title", "issue"),
        body=_text(d, "body", "issue"),
        labels=_labels(d.get("labels")),
        is_pull_request="pull_request" in d,
    )


def _parse_dir(data: Any) -> list[DirEntry]:
    if not isinstance(data, list):
        return []  # the path is a file, not a directory
    entries = []
    for item in data:
        d = _obj(item, "dir_entry")
        entries.append(
            DirEntry(_str(d, "name", "entry"), _str(d, "path", "entry"), _str(d, "type", "entry"))
        )
    return entries


def _parse_comment(data: Any) -> PostedComment:
    d = _obj(data, "comment")
    return PostedComment(id=_int(d, "id", "comment"), html_url=_str(d, "html_url", "comment"))


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class Transport(Protocol):
    """The ``requests.Session.request`` subset the client uses.

    The returned object needs ``status_code``, ``headers``, ``content``, and
    ``json()`` (a ``requests.Response`` or the tests' ``StubResponse``).
    """

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, Any] | None,
        json: Any,
        timeout: Any,
        allow_redirects: bool,
    ) -> Any: ...


Timeout = float | tuple[float, float]

# Retried for GETs. Anything else from requests (InvalidURL, TooManyRedirects…)
# is an immediate GitHubApiError; non-requests exceptions are not wrapped.
_TRANSIENT = (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError)


def _positive_finite(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _check_timeout(timeout: Any) -> Timeout:
    if isinstance(timeout, tuple):
        if len(timeout) == 2 and all(_positive_finite(t) for t in timeout):
            return (float(timeout[0]), float(timeout[1]))
    elif _positive_finite(timeout):
        return float(timeout)
    raise ValueError("timeout must be a positive finite number or a (connect, read) pair")


def _encode_path(path: str) -> str:
    """Percent-encode a repository path per segment; refuse dot/empty segments."""
    if not isinstance(path, str):
        raise ForbiddenCall("repository path must be a string")
    segments = path.split("/")
    if any(s in {"", ".", ".."} for s in segments):
        raise ForbiddenCall("repository path has an empty or dot segment")
    return "/".join(quote(s, safe="") for s in segments)


def _check_ref(ref: str) -> str:
    if (
        not isinstance(ref, str)
        or not ref
        or len(ref) > _MAX_REF_LEN
        or any(ord(c) < 0x20 or ord(c) == 0x7F for c in ref)
    ):
        raise ForbiddenCall("invalid ref")
    return ref


def _lower_headers(resp: Any) -> dict[str, str]:
    headers = getattr(resp, "headers", None) or {}
    return {str(k).lower(): str(v) for k, v in headers.items()}


def _body_text(resp: Any) -> str:
    content = getattr(resp, "content", b"") or b""
    return content[:4096].decode("utf-8", errors="replace")


def _is_rate_limited(resp: Any) -> bool:
    if resp.status_code == 429:
        return True
    if resp.status_code != 403:
        return False
    h = _lower_headers(resp)
    if "retry-after" in h or h.get("x-ratelimit-remaining") == "0":
        return True
    return "rate limit" in _body_text(resp).lower()


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


def _default_session() -> requests.Session:
    """A session that ignores the environment.

    With ``trust_env=True`` a ``.netrc`` entry for api.github.com would replace
    the Bearer header, and proxy variables would reroute the token-bearing call.
    """
    session = requests.Session()
    session.trust_env = False
    return session


class GitHubClient:
    """Allowlisted GitHub REST client bound to one repository and one PR."""

    def __init__(
        self,
        token: str,
        org: str,
        repo: str,
        pr_number: int,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        timeout: Any = DEFAULT_TIMEOUT,
    ) -> None:
        if not isinstance(token, str) or not token:
            raise ValueError("token is required")
        if not isinstance(org, str) or not _ORG_RE.fullmatch(org):
            raise ValueError("invalid org")
        if not isinstance(repo, str) or not _REPO_RE.fullmatch(repo) or repo in {".", ".."}:
            raise ValueError("invalid repo")
        if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number < 1:
            raise ValueError("pr_number must be a positive integer")
        self._token = token
        self.org = org
        self.repo = repo
        self.pr_number = pr_number
        self._transport: Any = transport if transport is not None else _default_session()
        self._sleep = sleep
        self._clock = clock
        self._timeout = _check_timeout(timeout)
        self._bound = {"o": org, "r": repo, "n": str(pr_number)}
        self._prefix = f"/repos/{org}/{repo}"

    def __repr__(self) -> str:
        return f"GitHubClient(org={self.org!r}, repo={self.repo!r}, pr_number={self.pr_number})"

    # -- public API (spec §6.2) ---------------------------------------------

    def get_pull(self) -> PullRequest:
        """The invoked PR. 404 -> ``GitHubNotFound`` (not a PR, or gone)."""
        resp = self._request("GET", f"{self._prefix}/pulls/{self.pr_number}", not_found="raise")
        return self._parse(resp, _parse_pull)

    def list_pull_files(self) -> PullFiles:
        """Changed files, ``per_page=100``, at most ``MAX_FILE_PAGES`` pages."""
        files: list[PullFile] = []
        path = f"{self._prefix}/pulls/{self.pr_number}/files"
        for page in range(1, MAX_FILE_PAGES + 1):
            resp = self._request(
                "GET", path, params={"per_page": FILES_PER_PAGE, "page": page}, not_found="raise"
            )
            items = self._parse(resp, lambda data: data if isinstance(data, list) else None)
            if items is None:
                raise GitHubMalformedResponse("malformed response: files page is not a list")
            files.extend(self._parse_each(items, _parse_file))
            if len(items) < FILES_PER_PAGE:
                return PullFiles(tuple(files), truncated=False)
        return PullFiles(tuple(files), truncated=True)

    def compare(self, base_sha: str, head_sha: str) -> Comparison:
        """Merge base of ``base_sha...head_sha`` (D-26)."""
        for sha in (base_sha, head_sha):
            if not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
                raise ForbiddenCall("compare requires full hex commit SHAs")
        resp = self._request(
            "GET", f"{self._prefix}/compare/{base_sha}...{head_sha}", not_found="raise"
        )
        return self._parse(resp, _parse_compare)

    def get_content_raw(self, path: str, ref: str) -> str | None:
        """Raw file content at ``ref`` (UTF-8, errors replaced). 404 -> ``None``."""
        content = self.get_content_bytes(path, ref)
        if content is None:
            return None
        return content.decode("utf-8", errors="replace")

    def get_content_bytes(self, path: str, ref: str) -> bytes | None:
        """Raw file bytes at ``ref``, undecoded. 404 -> ``None``.

        Same allowlisted call as ``get_content_raw``; callers that need byte
        offsets (the binary NUL check, S-206) decode afterwards.
        """
        resp = self._request(
            "GET",
            f"{self._prefix}/contents/{_encode_path(path)}",
            params={"ref": _check_ref(ref)},
            accept=ACCEPT_RAW,
            not_found="none",
        )
        if resp is None:
            return None
        return bytes(resp.content or b"")

    def list_dir(self, path: str, ref: str) -> list[DirEntry]:
        """Directory entries at ``ref``. 404, or a file path -> ``[]``."""
        resp = self._request(
            "GET",
            f"{self._prefix}/contents/{_encode_path(path)}",
            params={"ref": _check_ref(ref)},
            not_found="none",
        )
        if resp is None:
            return []
        return self._parse(resp, _parse_dir)

    def get_issue(self, number: int) -> Issue:
        """Issue ``number`` in the bound repo. 404 -> ``GitHubNotFound``."""
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise ForbiddenCall("issue number must be a positive integer")
        resp = self._request("GET", f"{self._prefix}/issues/{number}", not_found="raise")
        return self._parse(resp, _parse_issue)

    def post_pr_comment(self, body: str) -> PostedComment:
        """The only write: one comment on the invoked PR. Never retried."""
        if not isinstance(body, str):
            raise TypeError("comment body must be a string")
        resp = self._request(
            "POST",
            f"{self._prefix}/issues/{self.pr_number}/comments",
            json={"body": body},
            not_found="raise_api",
        )
        return self._parse(resp, _parse_comment)

    # -- guard ---------------------------------------------------------------

    def _check(self, method: str, path: str, params: Mapping[str, Any] | None) -> AllowedCall:
        if not isinstance(method, str) or not isinstance(path, str):
            raise ForbiddenCall("method and path must be strings")
        if not path.startswith(self._prefix + "/") or any(c in path for c in "?#\\"):
            raise ForbiddenCall(f"{method} {path!r} is not an allowlisted GitHub call")
        for entry in ALLOWLIST:
            if entry.method == method and _match(path, entry.template, self._bound):
                for key, value in (params or {}).items():
                    if key not in entry.query:
                        raise ForbiddenCall(f"query parameter {key!r} not allowed for {method}")
                    if not isinstance(value, str | int) or isinstance(value, bool):
                        raise ForbiddenCall(f"query parameter {key!r} has an invalid type")
                    if isinstance(value, int) and not 0 < value <= _MAX_QUERY_INT:
                        raise ForbiddenCall(f"query parameter {key!r} is out of range")
                return entry
        raise ForbiddenCall(f"{method} {path!r} is not an allowlisted GitHub call")

    # -- transport -----------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        accept: str = ACCEPT_JSON,
        not_found: str = "raise",
    ) -> Any:
        """Check, send, retry (GET only), and map errors.

        ``not_found``: ``"raise"`` -> ``GitHubNotFound``; ``"none"`` -> return
        ``None``; ``"raise_api"`` -> ``GitHubApiError``.
        """
        self._check(method, path, params)
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": accept,
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
        }
        attempts = MAX_ATTEMPTS if method == "GET" else 1
        where = f"{method} {path}"
        for attempt in range(1, attempts + 1):
            failure: str | None = None
            resp: Any = None
            try:
                resp = self._transport.request(
                    method,
                    API_BASE + path,
                    headers=headers,
                    params=dict(params) if params else None,
                    json=json,
                    timeout=self._timeout,
                    allow_redirects=False,
                )
            except _TRANSIENT as exc:
                failure = type(exc).__name__
            except requests.RequestException as exc:
                # Not transient: fail now, without chaining the exception.
                failure = type(exc).__name__
                attempts = attempt
            last = attempt == attempts
            if failure is not None:
                if last:
                    raise GitHubApiError(f"{where} failed: {failure} after {attempt} attempt(s)")
                self._sleep(BACKOFF_SECONDS[attempt - 1])
                continue

            status = resp.status_code
            if 200 <= status < 300:
                return resp
            if _is_rate_limited(resp):
                if last:
                    raise GitHubApiError(
                        f"{where} rate limited (HTTP {status}) after {attempt} attempt(s)",
                        status=status,
                    )
                self._sleep(self._rate_limit_wait(resp))
                continue
            if status in (401, 403):
                raise GitHubPermissionDenied(f"{where} denied (HTTP {status})", status=status)
            if status == 404:
                if not_found == "none":
                    return None
                if not_found == "raise":
                    raise GitHubNotFound(f"{where} not found (HTTP 404)", status=404)
                raise GitHubApiError(f"{where} failed (HTTP 404)", status=404)
            if status >= 500 and not last:
                self._sleep(BACKOFF_SECONDS[attempt - 1])
                continue
            raise GitHubApiError(f"{where} failed (HTTP {status})", status=status)
        raise AssertionError("unreachable")  # pragma: no cover

    def _rate_limit_wait(self, resp: Any) -> float:
        h = _lower_headers(resp)
        retry_after = h.get("retry-after")
        if retry_after is not None:
            try:
                value = float(retry_after)
            except ValueError:
                value = math.nan
            if math.isfinite(value) and value >= 0:
                return min(value, MAX_WAIT_SECONDS)
            return RATE_LIMIT_FALLBACK_SECONDS
        reset = h.get("x-ratelimit-reset")
        if h.get("x-ratelimit-remaining") == "0" and reset is not None:
            try:
                wait = float(reset) - self._clock()
            except ValueError:
                wait = math.nan
            if math.isfinite(wait):
                return min(max(wait, 0.0), MAX_WAIT_SECONDS)
        return RATE_LIMIT_FALLBACK_SECONDS

    # -- parsing ---------------------------------------------------------------

    @staticmethod
    def _parse(resp: Any, parser: Callable[[Any], Any]) -> Any:
        problem: str | None = None
        try:
            data = resp.json()
        except ValueError:
            problem = "body is not JSON"
        else:
            try:
                return parser(data)
            except _Malformed as exc:
                problem = f"field {exc.args[0]} missing or mistyped"
        raise GitHubMalformedResponse(f"malformed response: {problem}")

    @staticmethod
    def _parse_each(items: list[Any], parser: Callable[[Any], Any]) -> list[Any]:
        problem: str | None = None
        try:
            return [parser(item) for item in items]
        except _Malformed as exc:
            problem = f"field {exc.args[0]} missing or mistyped"
        raise GitHubMalformedResponse(f"malformed response: {problem}")
