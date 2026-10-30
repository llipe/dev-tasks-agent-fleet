"""An in-memory GitHub REST and GraphQL double for L2 component tests.

It stands in for ``requests.Session`` at the transport boundary: the code
under test builds real URLs, headers and JSON bodies, and this fake records
every request and answers the endpoints the agent uses. It keeps the package
free of an extra HTTP-mocking dependency (TESTING.md: ``requests`` is mocked as
in the siblings; DF-186-02: this double is the L2 standard, not ``responses``).

Served (S-186): issue comments (list, paged; post) and comment reactions.
Served (S-185): issue facts (``GET /repos/o/r/issues/{n}``), open pull requests
(``GET /repos/o/r/pulls``, paged), and the GraphQL closing-reference query
(``POST /graphql``, ``closedByPullRequestsReferences``, paged by cursor).
Served (S-188): comment deletion (``DELETE /repos/o/r/issues/comments/{id}``,
204, or 404 for an id it doesn't hold), recorded in ``deleted``.

Pagination here hands the client a pre-parsed ``links`` dict, like
``requests.Response.links``; it never builds a ``Link`` header. The real header
parsing is covered at L1 by ``tests/unit/test_github_client.py`` (DF-186-02).

Fault injection (S-185): ``faults[route]`` is a list of responses (an ``int``
status, a :class:`FakeResponse`, or an exception) served, in order, before the
route's normal answer. Routes: ``issue``, ``pulls``, ``graphql``,
``comments_get``, ``comments_post``, ``reaction``, ``comment_delete``.

Redirects (S-185, QA 3): :func:`redirect` builds a 3xx answer with a
``Location`` off the API host, for ``faults``. Each :class:`Call` records the
``allow_redirects`` the client sent; the double never follows a redirect
itself, so a test asserts the client both disabled redirects and treated the
3xx as a fault.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

API = "https://api.github.com"
APP_ID = 424242
TOKEN = "ghs_" + "T" * 36

_COMMENTS = re.compile(r"^/(?:repos/[^/]+/[^/]+|repositories/\d+)/issues/(\d+)/comments$")
_REACTIONS = re.compile(r"^/repos/[^/]+/[^/]+/issues/comments/(\d+)/reactions$")
_COMMENT = re.compile(r"^/repos/[^/]+/[^/]+/issues/comments/(\d+)$")
_ISSUE = re.compile(r"^/repos/[^/]+/[^/]+/issues/(\d+)$")
_PULLS = re.compile(r"^/(?:repos/[^/]+/[^/]+|repositories/\d+)/pulls$")
_GRAPHQL = "/graphql"


@dataclass
class Call:
    method: str
    url: str
    path: str
    headers: dict[str, str]
    json: Any
    params: dict[str, Any] | None
    timeout: Any
    allow_redirects: Any = None


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any = None,
        headers: dict[str, str] | None = None,
        links: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.links = links or {}

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


def redirect(status: int = 301, location: str = "https://evil.example/steal") -> FakeResponse:
    """A 3xx answer pointing off the API host (QA 3)."""
    return FakeResponse(status, None, {"Location": location})


def issue_payload(number: int, *, state: str = "open", pull_request: bool = False, labels=()):
    """A ``GET /issues/{n}`` body in GitHub's shape (title and body included)."""
    body: dict[str, Any] = {
        "number": number,
        "state": state,
        "title": f"Issue {number} title",
        "body": "issue body",
        "user": {"login": "reporter", "type": "User"},
        "labels": [{"name": name} for name in labels],
    }
    if pull_request:
        body["pull_request"] = {"url": f"{API}/repos/o/r/pulls/{number}", "merged_at": None}
    return body


def pull_payload(number: int, head_ref: str, *, state: str = "open", fork: bool = False):
    """A ``GET /pulls`` item. ``fork=None`` models a deleted fork (``head.repo: null``)."""
    repo: dict[str, Any] | None
    if fork is None:
        repo = None
    else:
        repo = {"full_name": "someone/r" if fork else "o/r", "fork": bool(fork)}
    return {"number": number, "state": state, "head": {"ref": head_ref, "repo": repo}}


@dataclass
class FakeGitHub:
    """Records requests; serves one repository's issue, pulls and comment endpoints."""

    per_page_cap: int = 100
    comments: dict[int, list[dict]] = field(default_factory=dict)
    next_id: int = 2**31 + 1000
    reaction_status: int = 201
    post_status: int = 201
    list_status: int = 200
    delay: float = 0.0
    calls: list[Call] = field(default_factory=list)
    reactions: list[tuple[int, str]] = field(default_factory=list)
    raise_exc: BaseException | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    next_link_override: str | None = None
    # S-185
    issues: dict[int, dict] = field(default_factory=dict)
    pulls: list[dict] = field(default_factory=list)
    closing_refs: dict[int, list[dict]] = field(default_factory=dict)
    graphql_page_size: int = 100
    faults: dict[str, list[Any]] = field(default_factory=dict)
    # S-188
    deleted: list[int] = field(default_factory=list)

    # -- seeding -----------------------------------------------------------

    def add_comment(
        self,
        issue: int,
        body: str,
        *,
        app_id: int | None = APP_ID,
        user_type: str = "Bot",
        cid: int | None = None,
    ) -> dict:
        if cid is None:
            cid = self.next_id
            self.next_id += 1
        comment = {
            "id": cid,
            "body": body,
            "user": {
                "login": "agent-fleet[bot]" if user_type == "Bot" else "human",
                "type": user_type,
            },
            "performed_via_github_app": None if app_id is None else {"id": app_id},
        }
        self.comments.setdefault(issue, []).append(comment)
        return comment

    def add_issue(self, number: int, **kwargs: Any) -> dict:
        self.issues[number] = issue_payload(number, **kwargs)
        return self.issues[number]

    def add_closing_ref(
        self, issue: int, pr: int, state: str = "OPEN", repo: str | None = "o/r"
    ) -> None:
        """A closing reference; ``repo`` is the PR's ``nameWithOwner`` (CT-33).

        ``repo=None`` omits ``repository`` from the node, a malformed answer.
        """
        node: dict[str, Any] = {"number": pr, "state": state}
        if repo is not None:
            node["repository"] = {"nameWithOwner": repo}
        self.closing_refs.setdefault(issue, []).append(node)

    # -- inspection ----------------------------------------------------------

    def writes(self) -> list[Call]:
        return [c for c in self.calls if c.method != "GET" and c.path != _GRAPHQL]

    def paths(self, method: str | None = None) -> list[str]:
        return [c.path for c in self.calls if method is None or c.method == method]

    def graphql_calls(self) -> list[Call]:
        return [c for c in self.calls if c.path == _GRAPHQL]

    def projects_calls(self) -> list[Call]:
        """GraphQL requests that touch Projects v2 (the board), by query text."""
        return [
            c
            for c in self.graphql_calls()
            if "projectv2" in str((c.json or {}).get("query", "")).lower()
        ]

    # -- transport -----------------------------------------------------------

    def _fault(self, route: str) -> FakeResponse | None:
        queue = self.faults.get(route)
        if not queue:
            return None
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, int):
            return FakeResponse(item, {"message": "fault"}, dict(self.extra_headers))
        return item

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: Any = None,
        allow_redirects: Any = None,
    ) -> FakeResponse:
        parts = urlsplit(url)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        merged = {**query, **(params or {})}
        self.calls.append(
            Call(
                method,
                url,
                parts.path,
                dict(headers or {}),
                json,
                merged,
                timeout,
                allow_redirects,
            )
        )
        if self.delay:
            time.sleep(self.delay)
        if self.raise_exc is not None:
            raise self.raise_exc

        m = _COMMENTS.match(parts.path)
        if m and method == "GET":
            return self._fault("comments_get") or self._list(int(m.group(1)), merged)
        if m and method == "POST":
            fault = self._fault("comments_post")
            if fault is not None:
                return fault
            if self.post_status >= 300:
                return FakeResponse(self.post_status, {"message": "nope"}, self.extra_headers)
            created = self.add_comment(int(m.group(1)), json["body"])
            return FakeResponse(201, created)
        m = _REACTIONS.match(parts.path)
        if m and method == "POST":
            fault = self._fault("reaction")
            if fault is not None:
                return fault
            if self.reaction_status < 300:
                self.reactions.append((int(m.group(1)), json["content"]))
                return FakeResponse(self.reaction_status, {"content": json["content"]})
            return FakeResponse(self.reaction_status, {"message": "nope"}, self.extra_headers)
        m = _COMMENT.match(parts.path)
        if m and method == "DELETE":
            return self._fault("comment_delete") or self._delete(int(m.group(1)))
        m = _ISSUE.match(parts.path)
        if m and method == "GET":
            fault = self._fault("issue")
            if fault is not None:
                return fault
            payload = self.issues.get(int(m.group(1)))
            if payload is None:
                return FakeResponse(404, {"message": "Not Found"})
            return FakeResponse(200, payload)
        if _PULLS.match(parts.path) and method == "GET":
            return self._fault("pulls") or self._pulls(merged)
        if parts.path == _GRAPHQL and method == "POST":
            return self._fault("graphql") or self._graphql(json or {})
        return FakeResponse(404, {"message": "Not Found"})

    def _delete(self, cid: int) -> FakeResponse:
        for items in self.comments.values():
            for comment in items:
                if comment["id"] == cid:
                    items.remove(comment)
                    self.deleted.append(cid)
                    return FakeResponse(204, None)
        return FakeResponse(404, {"message": "Not Found"})

    def _list(self, issue: int, params: dict[str, Any]) -> FakeResponse:
        if self.list_status != 200:
            return FakeResponse(self.list_status, {"message": "err"}, self.extra_headers)
        per_page = min(int(params.get("per_page", 30)), self.per_page_cap)
        page = int(params.get("page", 1))
        items = self.comments.get(issue, [])
        chunk = items[(page - 1) * per_page : page * per_page]
        links: dict[str, dict[str, str]] = {}
        if page * per_page < len(items):
            nxt = self.next_link_override or (
                f"{API}/repositories/1/issues/{issue}/comments?per_page={per_page}&page={page + 1}"
            )
            links["next"] = {"url": nxt}
        return FakeResponse(200, chunk, links=links)

    def _pulls(self, params: dict[str, Any]) -> FakeResponse:
        per_page = min(int(params.get("per_page", 30)), self.per_page_cap)
        page = int(params.get("page", 1))
        state = params.get("state", "open")
        items = [p for p in self.pulls if state == "all" or p.get("state") == state]
        chunk = items[(page - 1) * per_page : page * per_page]
        links: dict[str, dict[str, str]] = {}
        if page * per_page < len(items):
            links["next"] = {
                "url": f"{API}/repositories/1/pulls?state={state}&per_page={per_page}&page={page + 1}"
            }
        return FakeResponse(200, chunk, links=links)

    def _graphql(self, body: dict) -> FakeResponse:
        query = str(body.get("query", ""))
        variables = body.get("variables") or {}
        if "closedByPullRequestsReferences" not in query:
            return FakeResponse(200, {"errors": [{"type": "UNSUPPORTED", "message": "x"}]})
        number = variables.get("number")
        if number not in self.issues:
            return FakeResponse(
                200,
                {
                    "data": {"repository": {"issue": None}},
                    "errors": [{"type": "NOT_FOUND", "message": "Could not resolve"}],
                },
            )
        include_closed = "includeClosedPrs: true" in query
        refs = [
            r
            for r in self.closing_refs.get(number, [])
            if include_closed or r.get("state") != "CLOSED"
        ]
        start = int(variables.get("after") or 0)
        size = self.graphql_page_size
        chunk = refs[start : start + size]
        more = start + size < len(refs)
        conn = {
            "nodes": chunk,
            "pageInfo": {"hasNextPage": more, "endCursor": str(start + size) if more else None},
        }
        return FakeResponse(
            200, {"data": {"repository": {"issue": {"closedByPullRequestsReferences": conn}}}}
        )
