"""
GitHub issue I/O: comments and reactions (spec §6; S-186; D-93).

All calls use the **App installation token** (``credentials.py``), never the
Projects PAT. The agent changes no labels and no assignees (D-93), so this
module has no call for either.

Error mapping (D-67), until S-185's shared client adds retries:

- transport errors, 5xx, 429 and rate-limited 403 → :class:`GitHubUnavailable`
  (``GITHUB_UNAVAILABLE``);
- any other 4xx → :class:`GitHubRequestRejected` (``GITHUB_REQUEST_REJECTED``);
- **except reactions**: a reaction 4xx (a deleted trigger comment returns 404,
  a bad id 422) is logged and returned as ``failed``, never raised, because a
  reaction is cosmetic (DF-38).

Error messages carry the method, the path and the status only: never the
token, a request body or a response body, and transport exceptions are raised
``from None`` so their text (which may echo headers) is dropped.

Comment bodies are capped at GitHub's 65,536 characters, counted in UTF-16 code
units so astral characters (emoji) can't push a body over the limit. A lone
surrogate is replaced with U+FFFD first, so a model string can't make GitHub
reject the body.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import requests

log = logging.getLogger("bug_fix.issues")

API_URL = "https://api.github.com"
API_VERSION = "2022-11-28"
DEFAULT_TIMEOUT = 15.0
MAX_COMMENT_CHARS = 65_536
TRUNCATION_NOTICE = "\n\n… (truncated)"
REACTIONS: tuple[str, ...] = ("eyes", "rocket", "confused")
_MAX_PAGES = 100
_NAME = re.compile(r"[A-Za-z0-9._-]+")
# A pagination link's path, relative to the API base (see _check_next).
_NEXT_PATH = re.compile(
    r"/(?:repos/(?P<owner>[A-Za-z0-9._-]+)/(?P<repo>[A-Za-z0-9._-]+)"
    r"|repositories/(?P<repo_id>[1-9][0-9]*))"
    r"/issues/(?P<issue>[1-9][0-9]*)/comments"
)


class GitHubError(Exception):
    """A GitHub call failed. ``code`` is the run's ``error_code``."""

    code = "GITHUB_ERROR"

    def __init__(self, message: str, *, status: int | None = None) -> None:
        self.status = status
        super().__init__(message)


class GitHubUnavailable(GitHubError):
    code = "GITHUB_UNAVAILABLE"


class GitHubRequestRejected(GitHubError):
    code = "GITHUB_REQUEST_REJECTED"


class _Response(Protocol):
    status_code: int
    headers: Any
    links: Any

    def json(self) -> Any: ...


@dataclass(frozen=True)
class ReactionResult:
    status: str  # "added" | "skipped" | "failed"
    content: str
    http_status: int | None = None


def utf16_len(text: str) -> int:
    """Length in UTF-16 code units, the unit GitHub's body limit is safe under."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def cut_utf16(text: str, units: int) -> str:
    """The longest prefix of ``text`` of at most ``units`` UTF-16 code units."""
    used = 0
    for i, ch in enumerate(text):
        used += 2 if ord(ch) > 0xFFFF else 1
        if used > units:
            return text[:i]
    return text


def well_formed(text: str) -> str:
    """``text`` as valid Unicode: a split surrogate pair is joined, and a lone
    surrogate becomes U+FFFD. GitHub answers 422 to a body that carries one
    (QA gap 6), which would abort the post.
    """
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def truncate_comment(body: str, limit: int = MAX_COMMENT_CHARS) -> str:
    """Cut ``body`` to ``limit`` UTF-16 units, ending with a truncation notice."""
    if utf16_len(body) <= limit:
        return body
    keep = limit - utf16_len(TRUNCATION_NOTICE)
    if keep < 0:
        return cut_utf16(body, limit)
    return cut_utf16(body, keep) + TRUNCATION_NOTICE


def _rate_limited(resp: _Response) -> bool:
    headers = resp.headers or {}
    return headers.get("x-ratelimit-remaining") == "0" or "retry-after" in headers


class IssuesClient:
    """Issue comments and reactions for one repository."""

    def __init__(
        self,
        owner: str,
        repo: str,
        token: str | Callable[[], str],
        *,
        session: Any = None,
        api_url: str = API_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        for name in (owner, repo):
            if not _NAME.fullmatch(name or "") or name in (".", ".."):
                raise ValueError("owner and repo must be plain GitHub names")
        self.owner = owner
        self.repo = repo
        self._token = token
        # A ``requests.Session``, or any object with the same ``request()``.
        self.session: Any = session if session is not None else requests.Session()
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout

    # -- transport -------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        token = self._token() if callable(self._token) else self._token
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "agent-fleet-bug-fix",
        }

    def _request(
        self,
        method: str,
        url: str,
        *,
        label: str,
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> _Response:
        if not url.startswith(self.api_url + "/"):
            raise GitHubRequestRejected(f"{method} {label}: URL is not on the GitHub API host")
        try:
            resp: _Response = self.session.request(
                method,
                url,
                headers=self._headers(),
                json=json,
                params=params,
                timeout=self.timeout if timeout is None else timeout,
            )
        except requests.RequestException as exc:
            raise GitHubUnavailable(
                f"{method} {label} could not reach GitHub ({type(exc).__name__})"
            ) from None
        status = resp.status_code
        if status >= 500 or status == 429 or (status == 403 and _rate_limited(resp)):
            raise GitHubUnavailable(f"{method} {label} returned {status}", status=status)
        if status >= 400:
            raise GitHubRequestRejected(f"{method} {label} returned {status}", status=status)
        return resp

    def _path(self, suffix: str) -> str:
        return f"/repos/{self.owner}/{self.repo}{suffix}"

    # -- comments ----------------------------------------------------------------

    def list_comments(self, issue_number: int, *, timeout: float | None = None) -> list[dict]:
        """Every comment on the issue, following pagination on this resource only."""
        label = self._path(f"/issues/{issue_number}/comments")
        url: str | None = self.api_url + label
        params: dict[str, Any] | None = {"per_page": 100}
        out: list[dict] = []
        repo_ids: set[str] = set()
        for _ in range(_MAX_PAGES):
            if url is None:
                break
            resp = self._request("GET", url, label=label, params=params, timeout=timeout)
            try:
                page = resp.json()
            except ValueError:
                raise GitHubRequestRejected(f"GET {label} returned no JSON") from None
            if not isinstance(page, list):
                raise GitHubRequestRejected(f"GET {label} returned no list")
            out.extend(c for c in page if isinstance(c, dict))
            nxt = (getattr(resp, "links", None) or {}).get("next") or {}
            url = nxt.get("url")
            if url is not None:
                repo_ids = self._check_next(url, issue_number, label, repo_ids)
            params = None  # the next link carries its own query
        return out

    def _check_next(
        self, url: object, issue_number: int, label: str, repo_ids: set[str]
    ) -> set[str]:
        """Allow a ``next`` link only to this issue's comments (QA gap 5).

        The host check in :meth:`_request` keeps the token on the API host;
        this keeps it on the listed resource. GitHub writes the link either as
        ``/repos/{owner}/{repo}/issues/{n}/comments`` or as
        ``/repositories/{id}/issues/{n}/comments``; the repository id must not
        change between pages. The raw path must match exactly, so ``..``, an
        encoded ``/`` or ``.``, another issue or another resource is refused.
        Returns the repository ids seen so far.
        """
        refused = GitHubRequestRejected(f"GET {label}: next link leaves the listed comments")
        if not isinstance(url, str):
            raise refused
        parts = urlsplit(url)
        base = urlsplit(self.api_url).path.rstrip("/")
        if parts.fragment or not parts.path.startswith(base + "/"):
            raise refused
        m = _NEXT_PATH.fullmatch(parts.path[len(base) :])
        if m is None or m.group("issue") != str(issue_number):
            raise refused
        if m.group("repo_id") is not None:
            seen = repo_ids | {m.group("repo_id")}
            if len(seen) > 1:
                raise refused
            return seen
        if (m.group("owner").lower(), m.group("repo").lower()) != (
            self.owner.lower(),
            self.repo.lower(),
        ):
            raise refused
        return repo_ids

    def post_comment(
        self, issue_number: int, body: str, *, timeout: float | None = None
    ) -> dict[str, Any]:
        """Post a comment (made well-formed, then truncated to the size limit) and
        return GitHub's object."""
        label = self._path(f"/issues/{issue_number}/comments")
        resp = self._request(
            "POST",
            self.api_url + label,
            label=label,
            json={"body": truncate_comment(well_formed(body))},
            timeout=timeout,
        )
        try:
            created = resp.json()
        except ValueError:
            return {}
        return created if isinstance(created, dict) else {}

    # -- reactions ---------------------------------------------------------------

    def add_reaction(
        self, comment_id: int | None, content: str, *, timeout: float | None = None
    ) -> ReactionResult:
        """React to a comment. ``None`` skips silently; a 4xx is logged, not raised."""
        if content not in REACTIONS:
            raise ValueError(f"reaction must be one of {REACTIONS}")
        if comment_id is None:
            return ReactionResult("skipped", content)
        if not isinstance(comment_id, int) or isinstance(comment_id, bool) or comment_id < 1:
            raise ValueError("comment_id must be a positive integer")
        label = self._path(f"/issues/comments/{comment_id}/reactions")
        try:
            resp = self._request(
                "POST",
                self.api_url + label,
                label=label,
                json={"content": content},
                timeout=timeout,
            )
        except GitHubRequestRejected as exc:
            log.warning("reaction %s on comment %s failed: %s", content, comment_id, exc)
            return ReactionResult("failed", content, exc.status)
        return ReactionResult("added", content, resp.status_code)
