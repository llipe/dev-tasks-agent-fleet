"""
Shared GitHub REST and GraphQL client: retry policy and typed errors
(spec §6, §8.1, §8.9; S-185; D-67).

Every call uses the **App installation token**, never the Projects PAT.

Retry policy (D-67). A request is tried at most :data:`MAX_ATTEMPTS` (3)
times:

- **Reads** (``GET``, and GraphQL *queries*) retry on transport errors, 5xx,
  429 and rate-limited 403s, with backoff (1 s, then 2 s);
- **Writes** (``POST``, ``PATCH``, ``PUT``, ``DELETE``) retry **only** on a rate
  limit, which GitHub refuses before applying the request. A write is never
  retried on a 5xx or a transport error, because GitHub may already have
  applied it, and a retry would post the same comment twice.

A rate-limit wait honours ``Retry-After`` or ``x-ratelimit-reset``. A wait
beyond :data:`MAX_WAIT_SECONDS` isn't taken: the call gives up at once, so a
long primary-limit reset can't consume the run budget.

Errors:

- transport errors, 5xx and rate limits that outlast the attempts →
  :class:`GitHubUnavailable` (``GITHUB_UNAVAILABLE``);
- any other 4xx, a URL off the API host, or a malformed body →
  :class:`GitHubRequestRejected` (``GITHUB_REQUEST_REJECTED``);
- a 404 is **data** when the caller passes ``not_found_ok=True``, and the call
  returns ``None``.

Callers decide which writes are best effort (a reaction, the refusal reply, a
race-loss ``DELETE`` 404; DF-38) by catching these errors.

Messages carry the method, the label and the status only: never the token, a
request body or a response body. Transport exceptions are raised ``from None``
so their text, which may echo headers, is dropped.

Pagination: :func:`next_link` reads the ``next`` relation of a response from
the raw ``Link`` header through :func:`parse_link_header`, which matches
``rel`` as a whole parameter name and never inside a quoted value. Callers
restrict where a ``next`` link may point.
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

import requests

log = logging.getLogger("bug_fix.github")

API_URL = "https://api.github.com"
API_VERSION = "2022-11-28"
DEFAULT_TIMEOUT = 15.0
MAX_ATTEMPTS = 3
BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0)
MAX_WAIT_SECONDS = 30.0
_READ_METHODS = frozenset({"GET", "HEAD"})
_LINK_TARGET = re.compile(r"[ \t]*<([^<>]*)>")
# An RFC 9110 token: a Link parameter name or an unquoted value.
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_MUTATION = re.compile(r"^\s*mutation\b", re.IGNORECASE)


def _sleep(seconds: float) -> None:
    """The default wait between attempts (tests replace it)."""
    time.sleep(seconds)


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


class Response(Protocol):
    status_code: int
    headers: Any

    def json(self) -> Any: ...


# ---------------------------------------------------------------------------
# Link header
# ---------------------------------------------------------------------------


def _skip_ws(value: str, i: int) -> int:
    while i < len(value) and value[i] in " \t":
        i += 1
    return i


def _skip_entry(value: str, i: int) -> int:
    """The index just past the next ``,`` outside a quoted string (or the end)."""
    quoted = False
    while i < len(value):
        ch = value[i]
        if quoted and ch == "\\":
            i += 2
            continue
        if ch == '"':
            quoted = not quoted
        elif ch == "," and not quoted:
            return i + 1
        i += 1
    return len(value)


def _quoted_string(value: str, i: int) -> tuple[str | None, int]:
    """The RFC 9110 quoted-string at ``value[i] == '"'``; ``None`` if unterminated."""
    out: list[str] = []
    i += 1
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            out.append(value[i + 1])
            i += 2
            continue
        if ch == '"':
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    return None, len(value)


def _link_params(value: str, i: int) -> tuple[list[tuple[str, str]] | None, int]:
    """The ``; name[=value]`` parameters of one link-value, up to its ``,``.

    Returns ``(None, next_entry)`` when the parameters are malformed, so the
    whole link-value is dropped.
    """
    params: list[tuple[str, str]] = []
    while True:
        i = _skip_ws(value, i)
        if i >= len(value):
            return params, i
        if value[i] == ",":
            return params, i + 1
        if value[i] != ";":
            return None, _skip_entry(value, i)
        i = _skip_ws(value, i + 1)
        name = _TOKEN.match(value, i)
        if name is None:
            return None, _skip_entry(value, i)
        i = _skip_ws(value, name.end())
        param = ""
        if i < len(value) and value[i] == "=":
            i = _skip_ws(value, i + 1)
            if i < len(value) and value[i] == '"':
                quoted, i = _quoted_string(value, i)
                if quoted is None:
                    return None, i
                param = quoted
            else:
                token = _TOKEN.match(value, i)
                if token is None:
                    return None, _skip_entry(value, i)
                param, i = token.group(0), token.end()
        params.append((name.group(0).lower(), param))


def parse_link_header(value: object) -> dict[str, str]:
    """``{rel: url}`` from an RFC 8288 ``Link`` header value, as GitHub sends it.

    Each link-value is ``<url>`` followed by ``; name[=value]`` parameters,
    where a value is a token or a quoted string. Only a parameter **named**
    ``rel`` names relations (QA 4): ``xrel=next``, or ``rel=next`` inside
    another parameter's quoted value (``title="a; rel=next"``), never does.
    Only the first ``rel`` counts (RFC 8288 §3.3). A multi-valued ``rel``
    (``rel="last next"``) names each relation; other parameters are ignored.
    A malformed link-value is dropped whole; nothing raises.
    """
    if not isinstance(value, str):
        return {}
    out: dict[str, str] = {}
    i = 0
    while i < len(value):
        m = _LINK_TARGET.match(value, i)
        if m is None:
            i = _skip_entry(value, i)
            continue
        url = m.group(1).strip()
        params, i = _link_params(value, m.end())
        if params is None or not url:
            continue
        rel = next((v for k, v in params if k == "rel"), "")
        for name in rel.split():
            out.setdefault(name.lower(), url)
    return out


def next_link(resp: Any) -> str | None:
    """The ``next`` page URL of a response, or ``None`` on the last page.

    A raw ``Link`` header is always parsed here, by :func:`parse_link_header`,
    because ``requests.Response.links`` splits parameters on every ``;``, even
    inside a quoted value. A pre-parsed ``links`` dict is read only when there
    is no header (the L2 double, ``fake_github.py``).
    """
    headers = getattr(resp, "headers", None) or {}
    try:
        raw = headers.get("Link") or headers.get("link")
    except AttributeError:
        raw = None
    if raw is not None:
        return parse_link_header(raw).get("next")
    links = getattr(resp, "links", None)
    if isinstance(links, Mapping):
        nxt = links.get("next")
        if isinstance(nxt, Mapping) and isinstance(nxt.get("url"), str):
            return str(nxt["url"])
    return None


# ---------------------------------------------------------------------------
# Rate limits
# ---------------------------------------------------------------------------


def _header(resp: Any, name: str) -> str | None:
    headers = getattr(resp, "headers", None) or {}
    for key in (name, name.lower(), name.title()):
        try:
            value = headers.get(key)
        except AttributeError:
            return None
        if value is not None:
            return str(value)
    return None


def _message(resp: Any) -> str:
    try:
        body = resp.json()
    except (ValueError, AttributeError):
        return ""
    if isinstance(body, Mapping) and isinstance(body.get("message"), str):
        return str(body["message"])
    return ""


def is_rate_limited(resp: Any) -> bool:
    """A 429, or a 403 that GitHub marks as a primary or secondary rate limit."""
    status = resp.status_code
    if status == 429:
        return True
    if status != 403:
        return False
    if _header(resp, "retry-after") is not None or _header(resp, "x-ratelimit-remaining") == "0":
        return True
    return "rate limit" in _message(resp).lower()


def _seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def rate_limit_wait(resp: Any, attempt: int) -> float:
    """Seconds to wait before retrying a rate-limited response."""
    retry_after = _seconds(_header(resp, "retry-after"))
    if retry_after is not None:
        return retry_after
    if _header(resp, "x-ratelimit-remaining") == "0":
        reset = _seconds(_header(resp, "x-ratelimit-reset"))
        if reset is not None:
            return max(0.0, reset - time.time())
    return _backoff(attempt)


def _backoff(attempt: int) -> float:
    return BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GitHubClient:
    """REST and GraphQL calls with the retry policy above."""

    def __init__(
        self,
        token: str | Callable[[], str],
        *,
        session: Any = None,
        api_url: str = API_URL,
        timeout: float = DEFAULT_TIMEOUT,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._token = token
        # A ``requests.Session``, or any object with the same ``request()``.
        self.session: Any = session if session is not None else requests.Session()
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self._sleep_fn = sleep

    def _wait(self, seconds: float) -> None:
        (self._sleep_fn or _sleep)(seconds)

    def _headers(self) -> dict[str, str]:
        token = self._token() if callable(self._token) else self._token
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "agent-fleet-bug-fix",
        }

    def request(
        self,
        method: str,
        url: str,
        *,
        label: str,
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        idempotent: bool | None = None,
        not_found_ok: bool = False,
    ) -> Response | None:
        """Send one request under the retry policy. ``None`` only for an allowed 404.

        ``idempotent`` defaults to ``True`` for reads; a GraphQL query passes it
        explicitly, because it is a ``POST`` that changes nothing.
        """
        method = method.upper()
        if not url.startswith(self.api_url + "/"):
            raise GitHubRequestRejected(f"{method} {label}: URL is not on the GitHub API host")
        retry_faults = method in _READ_METHODS if idempotent is None else idempotent
        for attempt in range(MAX_ATTEMPTS):
            last = attempt == MAX_ATTEMPTS - 1
            try:
                resp: Response = self.session.request(
                    method,
                    url,
                    headers=self._headers(),
                    json=json,
                    params=params,
                    timeout=self.timeout if timeout is None else timeout,
                )
            except requests.RequestException as exc:
                error = GitHubUnavailable(
                    f"{method} {label} could not reach GitHub ({type(exc).__name__})"
                )
                if last or not retry_faults:
                    raise error from None
                log.warning("%s; retrying", error)
                self._wait(_backoff(attempt))
                continue
            status = resp.status_code
            if is_rate_limited(resp):
                wait = rate_limit_wait(resp, attempt)
                if last or wait > MAX_WAIT_SECONDS:
                    raise GitHubUnavailable(
                        f"{method} {label} was rate limited ({status})", status=status
                    )
                log.warning("%s %s rate limited (%s); waiting %.1fs", method, label, status, wait)
                self._wait(wait)
                continue
            if status >= 500:
                if last or not retry_faults:
                    raise GitHubUnavailable(f"{method} {label} returned {status}", status=status)
                log.warning("%s %s returned %s; retrying", method, label, status)
                self._wait(_backoff(attempt))
                continue
            if status == 404 and not_found_ok:
                return None
            if status >= 400:
                raise GitHubRequestRejected(f"{method} {label} returned {status}", status=status)
            return resp
        raise AssertionError("unreachable")  # pragma: no cover

    def graphql(
        self,
        query: str,
        variables: Mapping[str, Any],
        *,
        label: str,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Run a GraphQL **query** and return its ``data``.

        A ``RATE_LIMITED`` error is retried like a rate-limited response. Any
        other GraphQL error is :class:`GitHubRequestRejected`, naming only the
        error types, never their messages. A mutation is refused: writes go
        through REST with their own policy.
        """
        if _MUTATION.match(query):
            raise ValueError("graphql() runs queries only")
        url = self.api_url + "/graphql"
        name = f"POST /graphql ({label})"
        body = {"query": query, "variables": dict(variables)}
        for attempt in range(MAX_ATTEMPTS):
            resp = self.request(
                "POST", url, label=name, json=body, timeout=timeout, idempotent=True
            )
            assert resp is not None  # not_found_ok is False
            try:
                payload = resp.json()
            except ValueError:
                raise GitHubRequestRejected(f"{name} returned no JSON") from None
            if not isinstance(payload, Mapping):
                raise GitHubRequestRejected(f"{name} returned no object")
            errors = payload.get("errors")
            if errors:
                types = sorted(
                    {
                        str(e.get("type"))
                        for e in errors
                        if isinstance(e, Mapping) and isinstance(e.get("type"), str)
                    }
                    if isinstance(errors, list)
                    else set()
                )
                if "RATE_LIMITED" in types:
                    if attempt == MAX_ATTEMPTS - 1:
                        raise GitHubUnavailable(f"{name} was rate limited")
                    self._wait(_backoff(attempt))
                    continue
                raise GitHubRequestRejected(f"{name} returned errors {types or ['unknown']}")
            data = payload.get("data")
            if not isinstance(data, Mapping):
                raise GitHubRequestRejected(f"{name} returned no data")
            return dict(data)
        raise AssertionError("unreachable")  # pragma: no cover

    def get_paged(
        self,
        url: str,
        *,
        label: str,
        params: dict[str, Any] | None,
        allow_next: Callable[[object], None],
        max_pages: int,
        timeout: float | None = None,
    ) -> list[Any]:
        """Every item of a paged list. ``allow_next`` raises to refuse a ``next`` link.

        A non-list page is :class:`GitHubRequestRejected`. Reaching
        ``max_pages`` with a ``next`` page still left is
        :class:`GitHubUnavailable`: a truncated list would read as "no match"
        (a missed claim marker or linked PR), which D-67 forbids.
        """
        out: list[Any] = []
        nxt = url
        for _ in range(max_pages):
            resp = self.request("GET", nxt, label=label, params=params, timeout=timeout)
            assert resp is not None  # not_found_ok is False
            try:
                page = resp.json()
            except ValueError:
                raise GitHubRequestRejected(f"GET {label} returned no JSON") from None
            if not isinstance(page, list):
                raise GitHubRequestRejected(f"GET {label} returned no list")
            out.extend(page)
            following = next_link(resp)
            if following is None:
                return out
            allow_next(following)
            nxt = following
            params = None  # the next link carries its own query
        raise GitHubUnavailable(f"GET {label} has more than {max_pages} pages")
