"""
CT-15 (S-216) — the real ``anthropic`` SDK over ``httpx2.MockTransport``.

The fake client (``tests/fixtures/anthropic_fake.py``) bypasses the SDK's
HTTP layer, so it cannot show what the SDK itself does. These tests run
``model_adapter.review`` through ``model_adapter.make_client`` and the real
``anthropic.Anthropic``, with only the transport replaced (no network):

(a) a 429 then a 200 stream: the SDK retries and the review succeeds;
(b) a persistent 429: exactly 3 HTTP requests (``max_retries=2``), then
    ``MODEL_RATE_LIMITED``;
(c) a 400 ``prompt is too long`` body: ``BadRequestError``, the context-length path;
(d) the request body carries ``output_config`` and ``fallbacks``, the stream call
    carries ``anthropic-beta: server-side-fallback-2026-07-01``, and the key is
    sent in one header only;
(e) an SSE stream with ``thinking`` and ``text`` blocks assembles into a final
    message with both; the adapter keeps the text.

S-217 adds the selection call's half: ``context.selection.select_context``
through ``make_client(max_retries=0)`` makes exactly one HTTP attempt on a
429 and fails open, and its request carries the selection body and the beta
header, with no ``count_tokens`` request.

Plan note: the pinned SDK (``anthropic==2.14.0``) is built on ``httpx2``, not
``httpx``, so the transport is ``httpx2.MockTransport``. ``output_config``,
``betas`` and ``fallbacks`` are named parameters of ``beta.messages.stream`` in
that version, so no ``extra_body`` is needed (CT-14). The pinned SDK sends an
``api_key`` as ``Authorization: Bearer <key>``, not the ``x-api-key`` header the
plan names (CT-15 (d)); the test pins what the SDK does.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest

import model_adapter
from model_adapter import FALLBACK_BETA, ModelApiError, ModelRateLimited
from tests.fixtures.anthropic_fake import valid_review
from tests.helpers.model_run import Recorder, first_prompt, review_inputs, settings

KEY = "sk-ant-api03-SDKTESTKEY-0123456789abcdef"
STREAM_PATH = "/v1/messages"
COUNT_PATH = "/v1/messages/count_tokens"


def _sse(events: list[tuple[str, dict[str, Any]]]) -> bytes:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def _stream_body(
    text: str, *, thinking: str | None = None, model: str = "claude-sonnet-5-5"
) -> bytes:
    events: list[tuple[str, dict[str, Any]]] = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_sdk_1",
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 1234, "output_tokens": 1},
                },
            },
        )
    ]
    index = 0
    if thinking is not None:
        events += [
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "thinking", "thinking": "", "signature": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "thinking_delta", "thinking": thinking},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "signature_delta", "signature": "sig"},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ]
        index = 1
    half = len(text) // 2
    events += [
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {"type": "text_delta", "text": text[:half]},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {"type": "text_delta", "text": text[half:]},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": index}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 321},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return _sse(events)


def _ok_stream(**kw: Any) -> httpx2.Response:
    return httpx2.Response(
        200,
        headers={"content-type": "text/event-stream", "request-id": "req_sdk_ok"},
        content=_stream_body(json.dumps(valid_review()), **kw),
    )


def _error(status: int, error_type: str, message: str, **headers: str) -> httpx2.Response:
    body = {"type": "error", "error": {"type": error_type, "message": message}}
    return httpx2.Response(
        status,
        headers={"content-type": "application/json", "request-id": "req_sdk_err", **headers},
        json=body,
    )


def _count(n: int = 1_000) -> httpx2.Response:
    return httpx2.Response(200, json={"input_tokens": n})


class Transport:
    """Records every request; answers ``count_tokens`` with ``count`` and streams from a script."""

    def __init__(
        self, script: list[httpx2.Response], count: Callable[[], httpx2.Response] = _count
    ) -> None:
        self.script = script
        self.count = count
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path == COUNT_PATH:
            return self.count()
        assert request.url.path == STREAM_PATH, request.url.path
        assert self.script, "unexpected stream request"
        return self.script.pop(0)

    def streams(self) -> list[httpx2.Request]:
        return [r for r in self.requests if r.url.path == STREAM_PATH]

    def counts(self) -> list[httpx2.Request]:
        return [r for r in self.requests if r.url.path == COUNT_PATH]


@pytest.fixture
def sdk(monkeypatch):
    """Route every ``anthropic.Anthropic`` that ``make_client`` builds through a transport."""
    holder: dict[str, Transport] = {}
    real = anthropic.Anthropic

    class Routed(real):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs: Any) -> None:
            transport = httpx2.MockTransport(holder["t"])
            super().__init__(**kwargs, http_client=httpx2.Client(transport=transport))

    monkeypatch.setattr(model_adapter.anthropic, "Anthropic", Routed)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

    def install(t: Transport) -> Transport:
        holder["t"] = t
        return t

    return install


def _review(recorder: Recorder | None = None) -> Any:
    ins = review_inputs()
    rec = recorder or Recorder()

    def factory(**kw: Any) -> Any:
        return model_adapter.make_client(api_key=KEY, **kw)

    return model_adapter.review(
        first_prompt(ins),
        ins,
        client_factory=factory,
        settings=settings(),
        reasoning_effort="high",
        max_diff_lines=2000,
        warn=rec.warn,
        sink=rec.sink,
    )


def test_a_429_then_200_is_retried_by_the_sdk(sdk):
    """(a): ``retry-after-ms`` honoured; 2 stream requests, one review call."""
    t = sdk(
        Transport(
            [_error(429, "rate_limit_error", "slow down", **{"retry-after-ms": "1"}), _ok_stream()]
        )
    )
    result = _review()
    assert len(t.streams()) == 2
    assert result.calls == 1 and result.findings == valid_review()


def test_a_persistent_429_is_three_requests_then_model_rate_limited(sdk):
    """(b): ``max_retries=2`` is exactly 3 HTTP requests."""
    limited = [
        _error(429, "rate_limit_error", "slow down", **{"retry-after-ms": "1"}) for _ in range(3)
    ]
    t = sdk(Transport(limited))
    with pytest.raises(ModelRateLimited) as exc:
        _review()
    assert len(t.streams()) == 3
    assert exc.value.code == "MODEL_RATE_LIMITED"
    assert "RateLimitError" in str(exc.value) and "slow down" not in str(exc.value)


def test_a_400_prompt_is_too_long_takes_the_context_length_path(sdk):
    """(c): the real ``BadRequestError`` body is read for the R4 phrase."""
    too_long = _error(
        400, "invalid_request_error", "prompt is too long: 1000001 tokens > 1000000 maximum"
    )
    t = sdk(Transport([too_long, _ok_stream()]))
    rec = Recorder()
    result = _review(rec)
    assert len(t.streams()) == 2  # a 400 is not retried by the SDK
    assert "context length rejected; retrying without full files" in rec.messages
    assert result.context.full_files_included == ()


def test_an_unrelated_400_is_model_api_error_without_retry(sdk):
    t = sdk(Transport([_error(400, "invalid_request_error", "unknown beta")]))
    with pytest.raises(ModelApiError):
        _review()
    assert len(t.streams()) == 1


def test_request_body_and_headers(sdk):
    """(d): body, beta header, and the key in the ``authorization`` header only."""
    t = sdk(Transport([_ok_stream()]))
    _review()
    (stream,) = t.streams()
    (count,) = t.counts()
    body = json.loads(stream.content)
    assert body["model"] == "claude-sonnet-5-5"
    assert body["max_tokens"] == 64_000
    assert body["stream"] is True
    assert body["fallbacks"] == "default"
    assert body["output_config"]["effort"] == "high"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "betas" not in body and "thinking" not in body and "tools" not in body
    assert FALLBACK_BETA in stream.headers.get("anthropic-beta", "")
    count_body = json.loads(count.content)
    assert set(count_body) == {"model", "system", "messages", "output_config"}
    for request in (stream, count):
        assert request.headers["authorization"] == f"Bearer {KEY}"
        others = {k: v for k, v in request.headers.items() if k.lower() != "authorization"}
        assert KEY not in json.dumps(others)
        assert KEY not in request.content.decode()
        assert KEY not in str(request.url)


def test_sse_thinking_and_text_blocks_assemble_and_the_text_is_kept(sdk):
    """(e): the final message has both blocks; the review is the text."""
    t = sdk(Transport([_ok_stream(thinking="private reasoning")]))
    result = _review()
    assert len(t.streams()) == 1
    assert result.findings == valid_review()
    assert result.input_tokens == 1234 and result.output_tokens == 321
    assert result.answered_by_model == "claude-sonnet-5-5"


def test_a_count_tokens_failure_is_not_retried_into_a_failed_run(sdk):
    """A 500 on ``count_tokens`` (after its own SDK retries) falls back to the estimate."""
    t = sdk(
        Transport(
            [_ok_stream()],
            count=lambda: _error(500, "api_error", "boom", **{"retry-after-ms": "1"}),
        )
    )
    rec = Recorder()
    result = _review(rec)
    assert result.calls == 1
    assert len(t.counts()) == 3
    assert "token count failed; using the estimate" in rec.messages


def _fallback_stream(partial: str, answer: str) -> httpx2.Response:
    """A streamed server-side fallback: partial text, a ``fallback`` block, the answer."""
    events: list[tuple[str, dict[str, Any]]] = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_sdk_fb",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-5-5",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 10, "output_tokens": 1},
                },
            },
        )
    ]
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": ""},
        {
            "type": "fallback",
            "from": {"model": "claude-sonnet-5-5"},
            "to": {"model": "claude-opus-5-1"},
            "trigger": {"type": "refusal"},
        },
        {"type": "text", "text": ""},
    ]
    texts = {0: partial, 2: answer}
    for index, block in enumerate(blocks):
        events.append(
            (
                "content_block_start",
                {"type": "content_block_start", "index": index, "content_block": block},
            )
        )
        if index in texts:
            events.append(
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "text_delta", "text": texts[index]},
                    },
                )
            )
        events.append(("content_block_stop", {"type": "content_block_stop", "index": index}))
    events += [
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 50},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=_sse(events))


def test_a_streamed_fallback_answer_posts_without_a_repair(sdk):
    """D-86, AC-16: the SDK assembles the fallback block; the adapter reads the text after it."""
    t = sdk(Transport([_fallback_stream('{"findings": [', json.dumps(valid_review()))]))
    result = _review()
    assert len(t.streams()) == 1
    assert result.findings == valid_review() and result.repair_calls == 0
    assert result.answered_by_model == "claude-opus-5-1"  # the SDK relabels the snapshot


# ---------------------------------------------------------------------------
# CT-15, selection half (S-217): one attempt with the real SDK
# ---------------------------------------------------------------------------


def _select_with_the_sdk() -> tuple[Any, list[tuple[str, dict[str, Any]]]]:
    from context.selection import ChangedFile, DocCandidate, SelectionInputs, select_context

    warnings: list[tuple[str, dict[str, Any]]] = []

    def factory(**kw: Any) -> Any:
        return model_adapter.make_client(api_key=KEY, **kw)

    counter = iter(range(1, 100))
    result = select_context(
        SelectionInputs(
            pr_title="t",
            pr_body="b",
            head_ref="h",
            issues=(),
            changed=(ChangedFile("src/a.py", 1, 0),),
            candidates=(DocCandidate(1, "docs/spec.md", 10),),
        ),
        client_factory=factory,
        model_id="claude-sonnet-5-5",
        clock=lambda: 0.0,
        deadline=800.0,
        nonce_factory=lambda: f"{next(counter):016x}",
        warn=lambda m, **d: warnings.append((m, d)),
    )
    return result, warnings


def test_selection_429_is_one_request_and_fails_open(sdk):
    """(b), selection: ``max_retries=0`` is exactly one HTTP request, then fail open."""
    limited = [
        _error(429, "rate_limit_error", "slow down", **{"retry-after-ms": "1"}) for _ in range(3)
    ]
    t = sdk(Transport(limited))
    result, warnings = _select_with_the_sdk()
    assert len(t.streams()) == 1
    assert t.counts() == []
    assert (result.status, result.reason) == ("failed", "api_error")
    assert warnings == [
        (
            "context selection failed; using rule-based context",
            {"reason": "api_error", "error": "RateLimitError"},
        )
    ]


def test_selection_request_body_and_headers(sdk):
    """(d), selection: effort low, 8,000 tokens, structured output, the beta, no tools."""
    answer = json.dumps({"documents": [{"index": 1, "role": "spec", "reason": "r"}]})
    t = sdk(
        Transport(
            [
                httpx2.Response(
                    200,
                    headers={"content-type": "text/event-stream", "request-id": "req_sel"},
                    content=_stream_body(answer),
                )
            ]
        )
    )
    result, warnings = _select_with_the_sdk()
    assert result.status == "picked" and result.spec_paths == ("docs/spec.md",)
    assert warnings == []
    (stream,) = t.streams()
    assert t.counts() == []
    body = json.loads(stream.content)
    assert body["model"] == "claude-sonnet-5-5"
    assert body["max_tokens"] == 8_000
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default"
    assert "tools" not in body and "tool_choice" not in body and "thinking" not in body
    assert FALLBACK_BETA in stream.headers.get("anthropic-beta", "")
    assert stream.headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in stream.content.decode()
