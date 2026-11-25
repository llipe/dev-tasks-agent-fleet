"""
A fake Anthropic client for the review call (S-216; D-80; test plan §14.1).

``FakeAnthropic`` stands in for ``anthropic.Anthropic`` on the two surfaces the
adapter uses: ``client.messages.count_tokens(**kw)`` and
``client.beta.messages.stream(**kw)`` (a context manager whose
``get_final_message()`` returns the final message). It makes no network call
and bypasses the SDK's HTTP layer, so it cannot show the SDK's retries,
``retry-after`` handling, headers or SSE assembly: CT-15
(``test_model_adapter_sdk.py``) covers those with the real SDK over
``httpx2.MockTransport``.

It records every call, in order, as a deep copy of the keyword arguments
(``events``, ``count_requests``, ``stream_requests``), and whether each stream
context manager was exited (``exits``: the exception type, or ``None``).

**Stream script** (``script``), one item per ``stream`` call, in order:

- a final message (``message``/``review_message`` build real
  ``anthropic.types.beta.BetaMessage`` objects with ``model_validate``, CT-14;
  ``loose_message`` builds one with ``model_construct`` for malformed shapes
  the SDK would not validate), returned by ``get_final_message()``;
- an ``Exception`` (the SDK's own classes, built by the helpers below), raised
  on ``__enter__``, where the SDK raises an HTTP error;
- ``MidStream(exc)``: raised by ``get_final_message()`` instead (an error event
  or a dropped connection after the stream opened);
- a callable ``(kwargs) -> item``, for an outcome that depends on the request.

A ``stream`` call past the end of the script raises ``AssertionError``.

**Count script** (``counts``), one item per ``count_tokens`` call: an ``int``
(the ``input_tokens``), an ``Exception`` (raised), a callable, or any other
object (returned as is, for malformed results). When the count script is
empty, ``count_tokens`` answers ``default_count``.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import anthropic
import httpx2
from anthropic.types import MessageTokensCount
from anthropic.types.beta import BetaMessage

__all__ = [
    "API_URL",
    "MODEL",
    "FakeAnthropic",
    "MidStream",
    "api_status_error",
    "auth_error",
    "bad_request",
    "connection_error",
    "finding",
    "loose_message",
    "message",
    "overloaded",
    "permission_denied",
    "prompt_too_long",
    "rate_limited",
    "review_message",
    "server_error",
    "timeout_error",
    "valid_review",
]

MODEL = "claude-sonnet-5-5"
API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_COUNT = 1_000


@dataclass(frozen=True)
class MidStream:
    """Raise ``error`` from ``get_final_message()``, after the stream opened."""

    error: BaseException


class _Stream:
    def __init__(self, item: Any) -> None:
        self._item = item

    def get_final_message(self) -> Any:
        if isinstance(self._item, MidStream):
            raise self._item.error
        return self._item


class _StreamManager:
    def __init__(self, fake: FakeAnthropic, item: Any, index: int) -> None:
        self._fake = fake
        self._item = item
        self._index = index

    def __enter__(self) -> _Stream:
        if isinstance(self._item, BaseException):
            self._fake.exits[self._index] = type(self._item)  # never opened: nothing to close
            raise self._item
        return _Stream(self._item)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._fake.exits[self._index] = exc_type


class _BetaMessages:
    def __init__(self, fake: FakeAnthropic) -> None:
        self._fake = fake

    def stream(self, **kwargs: Any) -> _StreamManager:
        fake = self._fake
        fake.stream_requests.append(copy.deepcopy(kwargs))
        fake.events.append(("stream", copy.deepcopy(kwargs)))
        index = len(fake.stream_requests) - 1
        fake.exits.append("open")
        if not fake.script:
            raise AssertionError(f"unexpected stream call #{index + 1}")
        item = fake.script.pop(0)
        if callable(item) and not isinstance(item, BaseException | MidStream | BetaMessage):
            item = item(copy.deepcopy(kwargs))
        return _StreamManager(fake, item, index)


class _Beta:
    def __init__(self, fake: FakeAnthropic) -> None:
        self.messages = _BetaMessages(fake)


class _Messages:
    def __init__(self, fake: FakeAnthropic) -> None:
        self._fake = fake

    def count_tokens(self, **kwargs: Any) -> Any:
        fake = self._fake
        fake.count_requests.append(copy.deepcopy(kwargs))
        fake.events.append(("count", copy.deepcopy(kwargs)))
        item: Any = fake.counts.pop(0) if fake.counts else fake.default_count
        if callable(item) and not isinstance(item, BaseException):
            item = item(copy.deepcopy(kwargs))
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, int) and not isinstance(item, bool):
            return MessageTokensCount(input_tokens=item)
        return item


class FakeAnthropic:
    """A scripted, recording stand-in for ``anthropic.Anthropic`` (review surface only)."""

    def __init__(
        self,
        script: Iterable[Any] = (),
        *,
        counts: Iterable[Any] = (),
        default_count: Any = DEFAULT_COUNT,
    ) -> None:
        self.script: list[Any] = list(script)
        self.counts: list[Any] = list(counts)
        self.default_count = default_count
        self.stream_requests: list[dict[str, Any]] = []
        self.count_requests: list[dict[str, Any]] = []
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.exits: list[Any] = []
        self.messages = _Messages(self)
        self.beta = _Beta(self)

    def push(self, *items: Any) -> FakeAnthropic:
        self.script.extend(items)
        return self

    def push_counts(self, *items: Any) -> FakeAnthropic:
        self.counts.extend(items)
        return self

    @property
    def calls(self) -> int:
        """``stream`` calls (the review calls); ``count_tokens`` calls are ``counts_made``."""
        return len(self.stream_requests)

    @property
    def counts_made(self) -> int:
        return len(self.count_requests)

    @property
    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.events]


# ---------------------------------------------------------------------------
# Final messages (CT-14: real SDK objects)
# ---------------------------------------------------------------------------


def _usage(usage: tuple[int, int] | None) -> dict[str, Any]:
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0}
    return {"input_tokens": usage[0], "output_tokens": usage[1]}


def message(
    text: str | None = None,
    *,
    blocks: Sequence[dict[str, Any]] | None = None,
    model: str = MODEL,
    stop_reason: str | None = "end_turn",
    usage: tuple[int, int] = (1000, 200),
) -> BetaMessage:
    """A validated final message: ``blocks`` as given, else one ``text`` block."""
    content = list(blocks) if blocks is not None else [{"type": "text", "text": text or ""}]
    return BetaMessage.model_validate(
        {
            "id": "msg_fixture_0001",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": _usage(usage),
        }
    )


def review_message(review: Any, **kw: Any) -> BetaMessage:
    """A final message whose one text block is ``json.dumps(review)``."""
    return message(json.dumps(review, ensure_ascii=False), **kw)


class _Loose:
    """A message-shaped object with arbitrary attributes (what ``model_construct`` allows)."""

    def __init__(self, **attrs: Any) -> None:
        self.__dict__.update(attrs)


def loose_message(
    text: str | None = "{}",
    *,
    model: Any = MODEL,
    stop_reason: Any = "end_turn",
    usage: Any = (1000, 200),
    content: Any = None,
    omit: Sequence[str] = (),
) -> Any:
    """A final message with shapes the SDK would not validate (missing or odd fields).

    ``usage`` may be a tuple ``(input, output)`` of any values, an object, or
    ``None``; ``omit`` drops attributes entirely.
    """
    if content is None:
        content = [_Loose(type="text", text=text)]
    if isinstance(usage, tuple):
        usage = _Loose(input_tokens=usage[0], output_tokens=usage[1])
    attrs = {"model": model, "stop_reason": stop_reason, "usage": usage, "content": content}
    for name in omit:
        attrs.pop(name, None)
    return _Loose(**attrs)


# ---------------------------------------------------------------------------
# Errors: the SDK's own classes, built as its HTTP layer builds them
# ---------------------------------------------------------------------------

_STATUS_CLASSES: dict[int, type[anthropic.APIStatusError]] = {
    400: anthropic.BadRequestError,
    401: anthropic.AuthenticationError,
    403: anthropic.PermissionDeniedError,
    404: anthropic.NotFoundError,
    409: anthropic.ConflictError,
    413: anthropic.RequestTooLargeError,
    422: anthropic.UnprocessableEntityError,
    429: anthropic.RateLimitError,
    500: anthropic.InternalServerError,
    529: anthropic.OverloadedError,
}


def _request() -> httpx2.Request:
    return httpx2.Request("POST", API_URL)


def api_status_error(
    status: int,
    message_text: str = "",
    *,
    error_type: str = "api_error",
    request_id: str | None = "req_fixture_0001",
    headers: dict[str, str] | None = None,
    cls: type[anthropic.APIStatusError] | None = None,
) -> anthropic.APIStatusError:
    """An ``APIStatusError`` subclass for ``status``, as ``Anthropic._make_status_error`` builds it.

    Its ``str()`` carries the API message, as the real one does, so a test can
    check that the adapter never repeats it.
    """
    body = {"type": "error", "error": {"type": error_type, "message": message_text}}
    hdrs = {"content-type": "application/json", **(headers or {})}
    if request_id is not None:
        hdrs["request-id"] = request_id
    response = httpx2.Response(status, headers=hdrs, json=body, request=_request())
    klass = cls or _STATUS_CLASSES.get(status, anthropic.APIStatusError)
    return klass(f"Error code: {status} - {body!r}", response=response, body=body)


def prompt_too_long(tokens: int = 1_000_001, limit: int = 1_000_000) -> anthropic.BadRequestError:
    err = api_status_error(
        400,
        f"prompt is too long: {tokens} tokens > {limit} maximum",
        error_type="invalid_request_error",
    )
    assert isinstance(err, anthropic.BadRequestError)
    return err


def bad_request(message_text: str = "output_config.format: schema rejected") -> Any:
    return api_status_error(400, message_text, error_type="invalid_request_error")


def rate_limited(message_text: str = "Number of request tokens has exceeded your limit.") -> Any:
    return api_status_error(
        429, message_text, error_type="rate_limit_error", headers={"retry-after": "0"}
    )


def auth_error(message_text: str = "invalid x-api-key") -> Any:
    return api_status_error(401, message_text, error_type="authentication_error")


def permission_denied(message_text: str = "Your API key does not have permission") -> Any:
    return api_status_error(403, message_text, error_type="permission_error")


def server_error(message_text: str = "Internal server error") -> Any:
    return api_status_error(500, message_text)


def overloaded(message_text: str = "Overloaded") -> Any:
    return api_status_error(529, message_text, error_type="overloaded_error")


def connection_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=_request())


def timeout_error() -> anthropic.APITimeoutError:
    return anthropic.APITimeoutError(request=_request())


# ---------------------------------------------------------------------------
# Review objects (spec §6.3)
# ---------------------------------------------------------------------------


def finding(rank: int = 1, **overrides: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "severity": "blocking",
        "category": "correctness",
        "file": "src/app.py",
        "line_start": 1,
        "line_end": 1,
        "title": "Off-by-one in the size check",
        "failure_scenario": "A size of exactly 10 is rejected.",
        "consequence": "Valid widgets cannot be saved.",
        "rank": rank,
    }
    out.update(overrides)
    return out


def valid_review(n: int = 1, checks: Sequence[dict[str, Any]] = ()) -> dict[str, Any]:
    return {"findings": [finding(k + 1) for k in range(n)], "verifier_checks": list(checks)}

