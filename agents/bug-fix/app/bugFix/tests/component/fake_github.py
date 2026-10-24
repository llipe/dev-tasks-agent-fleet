"""An in-memory GitHub REST double for L2 component tests.

It stands in for ``requests.Session`` at the transport boundary: the code
under test builds real URLs, headers and JSON bodies, and this fake records
every request and answers the issue-comment and reaction endpoints. It keeps
the package free of an extra HTTP-mocking dependency (TESTING.md: ``requests``
is mocked as in the siblings).
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


@dataclass
class Call:
    method: str
    url: str
    path: str
    headers: dict[str, str]
    json: Any
    params: dict[str, Any] | None
    timeout: Any


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


@dataclass
class FakeGitHub:
    """Records requests; serves comments and reactions for one repository."""

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
            "user": {"login": "agent-fleet[bot]" if user_type == "Bot" else "human", "type": user_type},
            "performed_via_github_app": None if app_id is None else {"id": app_id},
        }
        self.comments.setdefault(issue, []).append(comment)
        return comment

    # -- inspection ----------------------------------------------------------

    def writes(self) -> list[Call]:
        return [c for c in self.calls if c.method != "GET"]

    def paths(self, method: str | None = None) -> list[str]:
        return [c.path for c in self.calls if method is None or c.method == method]

    # -- transport -----------------------------------------------------------

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: Any = None,
    ) -> FakeResponse:
        parts = urlsplit(url)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        merged = {**query, **(params or {})}
        self.calls.append(Call(method, url, parts.path, dict(headers or {}), json, merged, timeout))
        if self.delay:
            time.sleep(self.delay)
        if self.raise_exc is not None:
            raise self.raise_exc

        m = _COMMENTS.match(parts.path)
        if m and method == "GET":
            return self._list(int(m.group(1)), merged)
        if m and method == "POST":
            if self.post_status >= 300:
                return FakeResponse(self.post_status, {"message": "nope"}, self.extra_headers)
            created = self.add_comment(int(m.group(1)), json["body"])
            return FakeResponse(201, created)
        m = _REACTIONS.match(parts.path)
        if m and method == "POST":
            if self.reaction_status < 300:
                self.reactions.append((int(m.group(1)), json["content"]))
                return FakeResponse(self.reaction_status, {"content": json["content"]})
            return FakeResponse(self.reaction_status, {"message": "nope"}, self.extra_headers)
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
