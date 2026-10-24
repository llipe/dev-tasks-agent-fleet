"""
GitHub issue I/O: issue facts, linked pull requests, comments and reactions
(spec §6; S-185, S-186; D-55, D-93).

All calls use the **App installation token** (``credentials.py``), never the
Projects PAT. The agent changes no labels and no assignees (D-93), so this
module has no call for either, and :class:`IssueFacts` carries no labels
(D-90).

Transport, retries and error mapping come from the shared
:class:`github_client.GitHubClient` (S-185, D-67): reads retry transient faults,
writes retry only rate limits, and failures raise :class:`GitHubUnavailable`
(``GITHUB_UNAVAILABLE``) or :class:`GitHubRequestRejected`
(``GITHUB_REQUEST_REJECTED``). The exception here: a reaction 4xx (a deleted
trigger comment returns 404, a bad id 422) is logged and returned as
``failed``, never raised, because a reaction is cosmetic (DF-38).

Linked pull requests (D-55): an **open** PR that closes the issue through a
closing reference (GraphQL ``closedByPullRequestsReferences``), or any open PR
whose head branch starts with ``issue/<N>-``, from this repository or a fork.
A fault is raised, never read as "no linked PR" (D-67).

Error messages carry the method, the path and the status only: never the
token, a request body or a response body.

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
from typing import Any
from urllib.parse import urlsplit

from github_client import (
    API_URL,
    API_VERSION,
    DEFAULT_TIMEOUT,
    GitHubClient,
    GitHubError,
    GitHubRequestRejected,
    GitHubUnavailable,
)

__all__ = [
    "API_URL",
    "API_VERSION",
    "DEFAULT_TIMEOUT",
    "MAX_COMMENT_CHARS",
    "REACTIONS",
    "GitHubError",
    "GitHubRequestRejected",
    "GitHubUnavailable",
    "IssueFacts",
    "IssuesClient",
    "ReactionResult",
    "cut_utf16",
    "truncate_comment",
    "utf16_len",
    "well_formed",
]

log = logging.getLogger("bug_fix.issues")

MAX_COMMENT_CHARS = 65_536
TRUNCATION_NOTICE = "\n\n… (truncated)"
REACTIONS: tuple[str, ...] = ("eyes", "rocket", "confused")
_MAX_PAGES = 100
_MAX_GRAPHQL_PAGES = 20
_NAME = re.compile(r"[A-Za-z0-9._-]+")
# A pagination link's path, relative to the API base (see _check_next).
_REPO_PREFIX = (
    r"/(?:repos/(?P<owner>[A-Za-z0-9._-]+)/(?P<repo>[A-Za-z0-9._-]+)"
    r"|repositories/(?P<repo_id>[1-9][0-9]*))"
)
_NEXT_COMMENTS = re.compile(_REPO_PREFIX + r"/issues/(?P<issue>[1-9][0-9]*)/comments")
_NEXT_PULLS = re.compile(_REPO_PREFIX + r"/pulls")

_CLOSING_PRS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      closedByPullRequestsReferences(first: 100, after: $after, includeClosedPrs: false) {
        nodes { number state }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
""".strip()


@dataclass(frozen=True)
class IssueFacts:
    """What the refusal checks read from ``GET /issues/{n}`` (spec §6). No labels (D-90)."""

    number: int
    state: str
    is_pull_request: bool


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


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


class IssuesClient(GitHubClient):
    """Issue facts, linked PRs, comments and reactions for one repository."""

    def __init__(
        self,
        owner: str,
        repo: str,
        token: str | Callable[[], str],
        *,
        session: Any = None,
        api_url: str = API_URL,
        timeout: float = DEFAULT_TIMEOUT,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        for name in (owner, repo):
            if not _NAME.fullmatch(name or "") or name in (".", ".."):
                raise ValueError("owner and repo must be plain GitHub names")
        super().__init__(token, session=session, api_url=api_url, timeout=timeout, sleep=sleep)
        self.owner = owner
        self.repo = repo
        self._open_pulls: list[dict] | None = None

    def _path(self, suffix: str) -> str:
        return f"/repos/{self.owner}/{self.repo}{suffix}"

    def _check_next(
        self,
        url: object,
        pattern: re.Pattern[str],
        label: str,
        repo_ids: set[str],
        issue: int | None,
    ) -> set[str]:
        """Allow a ``next`` link only to the listed resource (QA gap 5).

        The host check in :meth:`request` keeps the token on the API host;
        this keeps it on the listed resource. GitHub writes the link either as
        ``/repos/{owner}/{repo}/…`` or as ``/repositories/{id}/…``; the
        repository id must not change between pages. The raw path must match
        exactly, so ``..``, an encoded ``/`` or ``.``, another issue or another
        resource is refused. Returns the repository ids seen so far.
        """
        refused = GitHubRequestRejected(f"GET {label}: next link leaves the listed resource")
        if not isinstance(url, str):
            raise refused
        parts = urlsplit(url)
        base = urlsplit(self.api_url).path.rstrip("/")
        if parts.fragment or not parts.path.startswith(base + "/"):
            raise refused
        m = pattern.fullmatch(parts.path[len(base) :])
        if m is None or (issue is not None and m.group("issue") != str(issue)):
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

    def _paged(
        self,
        suffix: str,
        pattern: re.Pattern[str],
        params: dict[str, Any],
        *,
        issue: int | None = None,
        timeout: float | None = None,
    ) -> list[Any]:
        label = self._path(suffix)
        repo_ids: set[str] = set()

        def allow(url: object) -> None:
            nonlocal repo_ids
            repo_ids = self._check_next(url, pattern, label, repo_ids, issue)

        return self.get_paged(
            self.api_url + label,
            label=label,
            params=params,
            allow_next=allow,
            max_pages=_MAX_PAGES,
            timeout=timeout,
        )

    # -- issue facts (S-185) -------------------------------------------------------

    def get_issue(self, issue_number: int, *, timeout: float | None = None) -> IssueFacts | None:
        """The issue's ``state`` and whether it is a pull request; ``None`` on a 404."""
        label = self._path(f"/issues/{issue_number}")
        resp = self.request(
            "GET", self.api_url + label, label=label, timeout=timeout, not_found_ok=True
        )
        if resp is None:
            return None
        try:
            payload = resp.json()
        except ValueError:
            raise GitHubRequestRejected(f"GET {label} returned no JSON") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("state"), str):
            raise GitHubRequestRejected(f"GET {label} returned no issue")
        return IssueFacts(
            number=issue_number,
            state=payload["state"],
            is_pull_request=payload.get("pull_request") is not None,
        )

    # -- linked pull requests (S-185, D-55) ------------------------------------------

    def closing_prs(self, issue_number: int) -> list[int]:
        """Open PRs whose closing reference names the issue, in GitHub's order.

        Pages until one is found or the connection ends. Reaching
        ``_MAX_GRAPHQL_PAGES`` with none found and pages still left is
        :class:`GitHubUnavailable`, and ``hasNextPage`` without a cursor is
        :class:`GitHubRequestRejected`: neither is read as "no linked PR" (D-67).
        """
        label = "POST /graphql (closedByPullRequestsReferences)"
        found: list[int] = []
        after: str | None = None
        for _ in range(_MAX_GRAPHQL_PAGES):
            data = self.graphql(
                _CLOSING_PRS_QUERY,
                {"owner": self.owner, "name": self.repo, "number": issue_number, "after": after},
                label="closedByPullRequestsReferences",
            )
            conn = _closing_connection(data)
            for node in conn["nodes"]:
                number = _positive_int(node.get("number")) if isinstance(node, dict) else None
                if number is not None and node.get("state") == "OPEN":
                    found.append(number)
            page = conn["pageInfo"]
            if page.get("hasNextPage") is not True:
                return found
            cursor = page.get("endCursor")
            if not isinstance(cursor, str) or not cursor:
                raise GitHubRequestRejected(f"{label} returned a next page with no cursor")
            if found:
                return found
            after = cursor
        raise GitHubUnavailable(f"{label} has more than {_MAX_GRAPHQL_PAGES} pages")

    def open_pulls(self) -> list[dict]:
        """Every open PR of the repository, fetched once per client and paged."""
        if self._open_pulls is None:
            items = self._paged("/pulls", _NEXT_PULLS, {"state": "open", "per_page": 100})
            self._open_pulls = [p for p in items if isinstance(p, dict)]
        return self._open_pulls

    def branch_prs(self, issue_number: int) -> list[int]:
        """Open PRs whose head branch starts with ``issue/<N>-``, forks included."""
        prefix = f"issue/{issue_number}-"
        found: list[int] = []
        for pr in self.open_pulls():
            number = _positive_int(pr.get("number"))
            head = pr.get("head")
            ref = head.get("ref") if isinstance(head, dict) else None
            if number is None or pr.get("state", "open") != "open" or not isinstance(ref, str):
                continue
            if ref.startswith(prefix):
                found.append(number)
        return found

    def linked_pr(self, issue_number: int) -> int | None:
        """The lowest-numbered open linked PR (D-55), or ``None``.

        The closing references are asked first; open PRs are listed only when
        none is found.
        """
        found = self.closing_prs(issue_number) or self.branch_prs(issue_number)
        return min(found) if found else None

    # -- comments ----------------------------------------------------------------

    def list_comments(self, issue_number: int, *, timeout: float | None = None) -> list[dict]:
        """Every comment on the issue, following pagination on this resource only."""
        items = self._paged(
            f"/issues/{issue_number}/comments",
            _NEXT_COMMENTS,
            {"per_page": 100},
            issue=issue_number,
            timeout=timeout,
        )
        return [c for c in items if isinstance(c, dict)]

    def post_comment(
        self, issue_number: int, body: str, *, timeout: float | None = None
    ) -> dict[str, Any]:
        """Post a comment (made well-formed, then truncated to the size limit) and
        return GitHub's object."""
        label = self._path(f"/issues/{issue_number}/comments")
        resp = self.request(
            "POST",
            self.api_url + label,
            label=label,
            json={"body": truncate_comment(well_formed(body))},
            timeout=timeout,
        )
        assert resp is not None  # not_found_ok is False
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
            resp = self.request(
                "POST",
                self.api_url + label,
                label=label,
                json={"content": content},
                timeout=timeout,
            )
        except GitHubRequestRejected as exc:
            log.warning("reaction %s on comment %s failed: %s", content, comment_id, exc)
            return ReactionResult("failed", content, exc.status)
        assert resp is not None  # not_found_ok is False
        return ReactionResult("added", content, resp.status_code)


def _closing_connection(data: dict[str, Any]) -> dict[str, Any]:
    """``closedByPullRequestsReferences`` from the query's ``data``, checked.

    A missing repository or issue is a fault (GitHub answers it with an error,
    or with ``null``), never "no linked PR" (D-67).
    """
    label = "POST /graphql (closedByPullRequestsReferences)"
    repo = data.get("repository")
    issue = repo.get("issue") if isinstance(repo, dict) else None
    conn = issue.get("closedByPullRequestsReferences") if isinstance(issue, dict) else None
    if not isinstance(conn, dict):
        raise GitHubRequestRejected(f"{label} returned no issue")
    nodes = conn.get("nodes")
    page = conn.get("pageInfo")
    if not isinstance(nodes, list) or not isinstance(page, dict):
        raise GitHubRequestRejected(f"{label} returned a malformed connection")
    return {"nodes": nodes, "pageInfo": page}
