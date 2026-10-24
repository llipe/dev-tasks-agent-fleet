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

A rate-limit wait honours ``Retry-After`` or ``x-ratelimit-reset`` up to
:data:`MAX_WAIT_SECONDS` (60 s), so GitHub's common secondary-limit
``Retry-After: 60`` is retried; a longer one gives up at once. A secondary limit
with no usable header waits :data:`SECONDARY_LIMIT_WAIT_SECONDS` (60 s), as
GitHub advises.

Wait budget (QA 5, DF-185-06). Each logical operation (one call, a paged list,
a GraphQL query with its own ``RATE_LIMITED`` retries) runs against one
monotonic deadline, :data:`DEFAULT_BUDGET_SECONDS` (120 s) unless the caller
sets one with :meth:`GitHubClient.deadline` or ``budget``. Every retry wait,
HTTP or GraphQL, on any page, must end by the deadline, no attempt starts after
it, and a request's own timeout is cut to what remains. A wait that would pass
it is not taken: the call raises :class:`GitHubUnavailable` at once.

Redirects are never followed (``allow_redirects=False``, QA 3): a redirect
could carry the token off the API host, and GitHub doesn't apply a redirected
write.

Errors:

- transport errors, 5xx and rate limits that outlast the attempts →
  :class:`GitHubUnavailable` (``GITHUB_UNAVAILABLE``);
- any 3xx, any other 4xx, a URL off the API host, or a malformed body →
  :class:`GitHubRequestRejected` (``GITHUB_REQUEST_REJECTED``). A 3xx is not
  retried: GitHub sends one for a renamed or transferred resource, which a
  retry can't change. A redirected write is never reported as applied;
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
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Protocol

import requests

log = logging.getLogger("bug_fix.github")

API_URL = "https://api.github.com"
API_VERSION = "2022-11-28"
DEFAULT_TIMEOUT = 15.0
MAX_ATTEMPTS = 3
BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0)
# The longest single rate-limit wait honoured (``Retry-After`` or a reset).
MAX_WAIT_SECONDS = 60.0
# A secondary limit with no usable header: GitHub asks for at least a minute.
SECONDARY_LIMIT_WAIT_SECONDS = 60.0
# The wait budget of one logical operation (a call, a paged list, a query).
DEFAULT_BUDGET_SECONDS = 120.0
_READ_METHODS = frozenset({"GET", "HEAD"})
_LINK_TARGET = re.compile(r"[ \t]*<([^<>]*)>")
# An RFC 9110 token: a Link parameter name or an unquoted value.
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_MUTATION = re.compile(r"^\s*mutation\b", re.IGNORECASE)


def _sleep(seconds: float) -> None:
    """The default wait between attempts (tests replace it)."""
    time.sleep(seconds)


def _monotonic() -> float:
    """The default deadline clock (tests replace it)."""
    return time.monotonic()


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


def rate_limit_wait(resp: Any) -> float | None:
    """Seconds to wait before retrying a rate-limited response; ``None`` to give up.

    - A readable ``Retry-After`` is honoured up to :data:`MAX_WAIT_SECONDS`
      (60 s), so GitHub's common secondary-limit ``Retry-After: 60`` is retried.
    - A primary limit (``x-ratelimit-remaining: 0``) waits until
      ``x-ratelimit-reset``, also up to :data:`MAX_WAIT_SECONDS`.
    - Otherwise (a secondary limit with no usable header) it waits
      :data:`SECONDARY_LIMIT_WAIT_SECONDS`, GitHub's "at least one minute".

    The caller still refuses any wait that would pass its deadline.
    """
    retry_after = _seconds(_header(resp, "retry-after"))
    if retry_after is not None:
        return retry_after if retry_after <= MAX_WAIT_SECONDS else None
    if _header(resp, "x-ratelimit-remaining") == "0":
        reset = _seconds(_header(resp, "x-ratelimit-reset"))
        if reset is not None:
            wait = max(0.0, reset - time.time())
            return wait if wait <= MAX_WAIT_SECONDS else None
    return SECONDARY_LIMIT_WAIT_SECONDS


def _backoff(attempt: int) -> float:
    return BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GitHubClient:
    """REST and GraphQL calls with the retry policy above.

    ``budget`` is the wait budget of one logical operation, in seconds
    (default :data:`DEFAULT_BUDGET_SECONDS`). ``sleep`` and ``clock`` (a
    monotonic clock) are injectable for tests. A client is not thread-safe:
    the deadline is per client.
    """

    def __init__(
        self,
        token: str | Callable[[], str],
        *,
        session: Any = None,
        api_url: str = API_URL,
        timeout: float = DEFAULT_TIMEOUT,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
        budget: float = DEFAULT_BUDGET_SECONDS,
    ) -> None:
        self._token = token
        # A ``requests.Session``, or any object with the same ``request()``.
        self.session: Any = session if session is not None else requests.Session()
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.budget = budget
        self._sleep_fn = sleep
        self._clock_fn = clock
        self._deadline: float | None = None

    # -- the deadline (QA 5) ------------------------------------------------------

    def _now(self) -> float:
        return (self._clock_fn or _monotonic)()

    @contextmanager
    def deadline(self, seconds: float | None = None) -> Iterator[None]:
        """Run one logical operation against a monotonic deadline.

        The deadline is now plus ``seconds`` (default: :attr:`budget`). Every
        retry wait inside, HTTP and GraphQL, on any page, must end by then, and
        no attempt starts after it; otherwise the call raises
        :class:`GitHubUnavailable`. A nested ``deadline()`` keeps the outer one,
        so a caller can bound a whole sequence of calls. Each public call opens
        its own when none is open.
        """
        if self._deadline is not None:
            yield
            return
        self._deadline = self._now() + (self.budget if seconds is None else seconds)
        try:
            yield
        finally:
            self._deadline = None

    def _remaining(self) -> float:
        assert self._deadline is not None  # set by deadline()
        return self._deadline - self._now()

    def _wait(self, seconds: float, what: str, status: int | None = None) -> None:
        """Sleep ``seconds`` before a retry, or give up if that passes the deadline."""
        if seconds > self._remaining():
            raise GitHubUnavailable(
                f"{what}; a {seconds:.0f}s retry wait would pass the operation's time budget",
                status=status,
            )
        log.warning("%s; retrying in %.1fs", what, seconds)
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
        with self.deadline():
            return self._request(
                method,
                url,
                label=label,
                json=json,
                params=params,
                timeout=timeout,
                idempotent=idempotent,
                not_found_ok=not_found_ok,
            )

    def _request(
        self,
        method: str,
        url: str,
        *,
        label: str,
        json: Any,
        params: dict[str, Any] | None,
        timeout: float | None,
        idempotent: bool | None,
        not_found_ok: bool,
    ) -> Response | None:
        method = method.upper()
        if not url.startswith(self.api_url + "/"):
            raise GitHubRequestRejected(f"{method} {label}: URL is not on the GitHub API host")
        retry_faults = method in _READ_METHODS if idempotent is None else idempotent
        for attempt in range(MAX_ATTEMPTS):
            last = attempt == MAX_ATTEMPTS - 1
            remaining = self._remaining()
            if remaining <= 0:
                raise GitHubUnavailable(f"{method} {label}: the operation's time budget ran out")
            per_call = self.timeout if timeout is None else timeout
            try:
                resp: Response = self.session.request(
                    method,
                    url,
                    headers=self._headers(),
                    json=json,
                    params=params,
                    timeout=min(per_call, remaining),
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                error = GitHubUnavailable(
                    f"{method} {label} could not reach GitHub ({type(exc).__name__})"
                )
                if last or not retry_faults:
                    raise error from None
                self._wait(_backoff(attempt), str(error))
                continue
            status = resp.status_code
            if is_rate_limited(resp):
                wait = rate_limit_wait(resp)
                what = f"{method} {label} was rate limited ({status})"
                if last or wait is None:
                    raise GitHubUnavailable(what, status=status)
                self._wait(wait, what, status)
                continue
            if status >= 500:
                what = f"{method} {label} returned {status}"
                if last or not retry_faults:
                    raise GitHubUnavailable(what, status=status)
                self._wait(_backoff(attempt), what, status)
                continue
            if 300 <= status < 400:
                # Never followed (QA 3): a redirect could carry the token off
                # the API host, and a redirected write was not applied.
                raise GitHubRequestRejected(
                    f"{method} {label} returned a redirect ({status})", status=status
                )
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

        A ``RATE_LIMITED`` error is retried like a rate-limited response, inside
        the same deadline as the HTTP retries. Any other GraphQL error is
        :class:`GitHubRequestRejected`, naming only the error types, never their
        messages. A mutation is refused: writes go through REST with their own
        policy.
        """
        if _MUTATION.match(query):
            raise ValueError("graphql() runs queries only")
        with self.deadline():
            return self._graphql(query, variables, label=label, timeout=timeout)

    def _graphql(
        self,
        query: str,
        variables: Mapping[str, Any],
        *,
        label: str,
        timeout: float | None,
    ) -> dict[str, Any]:
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
                    wait = rate_limit_wait(resp)
                    what = f"{name} was rate limited"
                    if attempt == MAX_ATTEMPTS - 1 or wait is None:
                        raise GitHubUnavailable(what)
                    self._wait(wait, what)
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
        with self.deadline():
            return self._get_paged(url, label, params, allow_next, max_pages, timeout)

    def _get_paged(
        self,
        url: str,
        label: str,
        params: dict[str, Any] | None,
        allow_next: Callable[[object], None],
        max_pages: int,
        timeout: float | None,
    ) -> list[Any]:
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
