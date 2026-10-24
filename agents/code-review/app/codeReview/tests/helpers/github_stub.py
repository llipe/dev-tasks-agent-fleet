"""
Stub GitHub transport and recorded-fixture loader (S-205; reused by S-206–S-213).

``GitHubClient`` sends through an injected transport with the
``requests.Session.request`` signature. ``StubTransport`` records every call
and answers from a route table, so no test touches the network.

Routes are keyed by ``(METHOD, path)`` or ``(METHOD, path, query)`` where
``query`` is a tuple of sorted ``(key, value)`` string pairs. The exact key
with query wins over the query-less key. Each route holds a list of outcomes
consumed in order; the last one repeats. An outcome is a ``StubResponse`` or an
exception instance to raise. A call with no route returns ``default`` when one
is set and otherwise fails the test loudly.

Recorded fixtures live in ``tests/fixtures/github/<name>/routes.json``::

    [{"method": "GET", "path": "/repos/acme/widgets/pulls/42",
      "query": {"ref": "..."},            # optional
      "status": 200, "headers": {...},    # optional
      "body_file": "pull.json"}]          # or "body": <json> / "text": "..."
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "github"

Query = tuple[tuple[str, str], ...]


@dataclass
class StubResponse:
    status_code: int = 200
    content: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.content)


def json_response(
    body: Any, status: int = 200, headers: Mapping[str, str] | None = None
) -> StubResponse:
    return StubResponse(status, json.dumps(body).encode(), dict(headers or {}))


def text_response(
    text: str, status: int = 200, headers: Mapping[str, str] | None = None
) -> StubResponse:
    return StubResponse(status, text.encode(), dict(headers or {}))


@dataclass
class Call:
    method: str
    url: str
    path: str
    headers: dict[str, str]
    params: dict[str, Any]
    json: Any
    timeout: Any
    allow_redirects: Any

    @property
    def query(self) -> Query:
        return _query(self.params)


def _query(params: Mapping[str, Any] | None) -> Query:
    return tuple(sorted((str(k), str(v)) for k, v in (params or {}).items()))


class StubTransport:
    """Records calls and answers from a route table."""

    def __init__(
        self,
        routes: Mapping[tuple, list[Any] | Any] | None = None,
        *,
        default: StubResponse | None = None,
    ) -> None:
        self.routes: dict[tuple, list[Any]] = {}
        self.default = default
        self.calls: list[Call] = []
        for key, outcomes in (routes or {}).items():
            self.add(key, outcomes)

    def add(self, key: tuple, outcomes: list[Any] | Any) -> None:
        self.routes[key] = list(outcomes) if isinstance(outcomes, list) else [outcomes]

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        timeout: Any = None,
        allow_redirects: Any = True,
    ) -> StubResponse:
        path = urlsplit(url).path
        call = Call(
            method,
            url,
            path,
            dict(headers or {}),
            dict(params or {}),
            json,
            timeout,
            allow_redirects,
        )
        self.calls.append(call)
        key_q = (method, path, call.query)
        key = key_q if key_q in self.routes else (method, path)
        if key not in self.routes:
            if self.default is not None:
                return self.default
            raise AssertionError(f"StubTransport: no route for {method} {path} {call.query}")
        outcomes = self.routes[key]
        outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def load_fixture(name: str) -> StubTransport:
    """Build a ``StubTransport`` from ``tests/fixtures/github/<name>/routes.json``."""
    base = FIXTURES / name
    stub = StubTransport()
    for route in json.loads((base / "routes.json").read_text()):
        if "body_file" in route:
            content = (base / route["body_file"]).read_bytes()
        elif "text" in route:
            content = route["text"].encode()
        else:
            content = json.dumps(route.get("body")).encode()
        resp = StubResponse(route.get("status", 200), content, dict(route.get("headers", {})))
        query = route.get("query")
        key: tuple = (route["method"], route["path"])
        if query is not None:
            key = (*key, _query(query))
        stub.add(key, resp)
    return stub


def fixture_json(name: str, file: str) -> Any:
    return json.loads((FIXTURES / name / file).read_text())
