"""
Heartbeat keep-alive for long-running pipeline steps (issue #98).

Root cause of #98: the ``@app.entrypoint`` handler is an async generator that
yields only at terminal points. During a long blocking step (notably
``pnpm test`` inside ``validate``), the AgentCore HTTP response stream is idle;
once it stays idle past ``idleRuntimeSessionTimeout`` the container is reclaimed
before the agent can write a terminal status.

This module lets the entrypoint run a synchronous blocking function in a worker
thread while the async generator emits lightweight, clearly-typed *heartbeat*
chunks on an interval. The stream therefore never goes idle, and the container
survives for the full (bounded) duration of the step.

Design constraints (from the #98 refinement):

  - Heartbeat logic lives HERE and in the entrypoint, NOT in the byte-identical
    vendored ``agent_reporter.py`` (D13 — the SDK copy must not diverge).
  - Heartbeat chunks are structurally distinguishable from the terminal result
    payload so the consumer never mistakes one for a result (AC5 / CT-1).
  - The terminal result payload keeps its existing AgentCore delta shape
    (``event.contentBlockDelta.delta.text``) so the consumer contract is
    unchanged (CT-2), and is always emitted last (CT-3).
  - No new external dependency — stdlib ``asyncio`` only.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Chunk contract
# ---------------------------------------------------------------------------


def heartbeat_chunk(seq: int) -> dict:
    """Build a heartbeat stream chunk.

    Distinguishable from the terminal payload by a top-level ``heartbeat`` key
    and the deliberate absence of any ``event``/result fields. Carries a
    monotonic ``seq`` for observability only.
    """
    return {"heartbeat": {"seq": seq}}


def terminal_chunk(text: str) -> dict:
    """Build the terminal result chunk in the AgentCore delta shape.

    Mirrors the exact shape the entrypoint has always emitted so the consumer
    contract is unchanged (CT-2): the JSON result string lives at
    ``event.contentBlockDelta.delta.text``.
    """
    return {"event": {"contentBlockDelta": {"delta": {"text": text}}}}


def is_heartbeat_chunk(chunk: Any) -> bool:
    """True iff ``chunk`` is a heartbeat (never a terminal result)."""
    return isinstance(chunk, dict) and "heartbeat" in chunk and "event" not in chunk


def is_terminal_chunk(chunk: Any) -> bool:
    """True iff ``chunk`` carries a terminal result payload."""
    return (
        isinstance(chunk, dict)
        and "heartbeat" not in chunk
        and isinstance(chunk.get("event"), dict)
        and "contentBlockDelta" in chunk["event"]
    )


def read_terminal_payload(chunks: list) -> str | None:
    """Consumer-side helper: extract the terminal result text from a stream.

    Given the full list of chunks a run emitted, ignore every heartbeat and
    return the ``text`` of the single terminal chunk (AC5). Returns ``None`` if
    no terminal chunk is present. Ignores well-formed heartbeats without raising
    (fuzz-safe, RT-3).
    """
    terminal_text: str | None = None
    for chunk in chunks:
        if is_terminal_chunk(chunk):
            terminal_text = chunk["event"]["contentBlockDelta"]["delta"]["text"]
    return terminal_text


# ---------------------------------------------------------------------------
# run_with_heartbeat
# ---------------------------------------------------------------------------


@dataclass
class HeartbeatResult:
    """Terminal signal yielded last by :func:`run_with_heartbeat`.

    ``value`` holds the wrapped function's return value on success; ``error``
    holds the exception it raised (so the caller can re-raise or report a
    terminal status). Exactly one of the two is set.
    """

    value: Any = None
    error: BaseException | None = None


async def run_with_heartbeat(
    fn: Callable[[], Any],
    *,
    interval: float,
    seq_start: int = 0,
) -> AsyncIterator[dict | HeartbeatResult]:
    """Run blocking ``fn`` in a worker thread, emitting heartbeats until it ends.

    Yields :func:`heartbeat_chunk` dicts every ``interval`` seconds while ``fn``
    runs, then yields exactly one :class:`HeartbeatResult` as the final item
    (the terminal signal). The result carries ``fn``'s return value, or its
    exception in ``error`` — this function never lets ``fn``'s exception escape
    mid-iteration, so the caller controls terminal reporting.

    Guarantees:
      - The :class:`HeartbeatResult` is always the last item yielded (CT-3).
      - Zero heartbeats are emitted if ``fn`` finishes within one ``interval``.
      - Heartbeat ``seq`` values are strictly increasing.
    """
    task = asyncio.ensure_future(asyncio.to_thread(fn))
    seq = seq_start
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=interval)
            if task in done:
                break
            seq += 1
            yield heartbeat_chunk(seq)
    except asyncio.CancelledError:
        task.cancel()
        raise

    try:
        value = task.result()
        yield HeartbeatResult(value=value)
    except Exception as exc:  # noqa: BLE001 — surfaced to caller via result
        yield HeartbeatResult(error=exc)
