"""
Unit tests for the heartbeat keep-alive helper (issue #98, AC2/AC5/AC6).

The heartbeat module keeps the AgentCore response stream alive while a
synchronous blocking step runs, by emitting lightweight, clearly-typed
heartbeat chunks on an interval. It must:

  - emit heartbeat chunks distinguishable from the terminal result payload (AC5)
  - always let the caller emit the terminal payload LAST (AC5 / CT-3)
  - bound the emitted-chunk count to ~= duration / interval, not per-second (EC-6)
  - stop cleanly when the wrapped function finishes or raises (EC-5)

These are the RT-1 / CT-1 / CT-2 / CT-3 / EC-6 unit-level coverage.
"""

from __future__ import annotations

import asyncio
import json
import random
import time

from heartbeat import (
    HeartbeatResult,
    heartbeat_chunk,
    is_heartbeat_chunk,
    is_terminal_chunk,
    read_terminal_payload,
    run_with_heartbeat,
    terminal_chunk,
)

_PROP_SEED = "98_hb_0831"


# ---------------------------------------------------------------------------
# Chunk contract (CT-1, CT-2)
# ---------------------------------------------------------------------------


class TestChunkContract:
    def test_heartbeat_chunk_is_classified_as_heartbeat_only(self):
        chunk = heartbeat_chunk(seq=1)
        assert is_heartbeat_chunk(chunk) is True
        assert is_terminal_chunk(chunk) is False

    def test_terminal_chunk_is_classified_as_terminal_only(self):
        chunk = terminal_chunk(json.dumps({"status": "succeeded"}))
        assert is_terminal_chunk(chunk) is True
        assert is_heartbeat_chunk(chunk) is False

    def test_terminal_chunk_preserves_agentcore_delta_shape(self):
        # The terminal payload MUST remain readable at the existing path
        # event.contentBlockDelta.delta.text so the consumer contract is
        # unchanged (CT-2 schema-compat).
        payload = json.dumps({"status": "failed", "error_code": "X"})
        chunk = terminal_chunk(payload)
        text = chunk["event"]["contentBlockDelta"]["delta"]["text"]
        assert json.loads(text)["status"] == "failed"

    def test_heartbeat_chunk_carries_no_result_fields(self):
        # A heartbeat must not be mistakable for a result (no status/outcome).
        chunk = heartbeat_chunk(seq=3)
        blob = json.dumps(chunk)
        assert "status" not in blob
        assert "outcome" not in blob

    def test_heartbeat_seq_is_carried(self):
        chunk = heartbeat_chunk(seq=7)
        assert chunk["heartbeat"]["seq"] == 7


# ---------------------------------------------------------------------------
# run_with_heartbeat behaviour (RT-1, EC-5, EC-6)
# ---------------------------------------------------------------------------


def _sleep_return(value, seconds):
    def _fn():
        time.sleep(seconds)
        return value

    return _fn


class TestRunWithHeartbeat:
    def test_short_fn_emits_no_heartbeat_and_returns_result(self):
        async def _run():
            chunks = []
            result_holder = None
            async for item in run_with_heartbeat(_sleep_return("done", 0.0), interval=0.1):
                if isinstance(item, HeartbeatResult):
                    result_holder = item
                else:
                    chunks.append(item)
            return chunks, result_holder

        chunks, result = asyncio.run(_run())
        assert chunks == []  # nothing ran long enough to beat
        assert result.value == "done"
        assert result.error is None

    def test_long_fn_emits_at_least_one_heartbeat_before_result(self):
        async def _run():
            chunks = []
            result = None
            async for item in run_with_heartbeat(_sleep_return("ok", 0.35), interval=0.1):
                if isinstance(item, HeartbeatResult):
                    result = item
                else:
                    assert is_heartbeat_chunk(item)
                    chunks.append(item)
            return chunks, result

        chunks, result = asyncio.run(_run())
        assert len(chunks) >= 1
        assert result.value == "ok"

    def test_heartbeat_count_is_bounded_by_duration_over_interval(self):
        # EC-6: ~ duration/interval beats, not per-second flooding.
        async def _run():
            n = 0
            async for item in run_with_heartbeat(_sleep_return("x", 0.5), interval=0.1):
                if not isinstance(item, HeartbeatResult):
                    n += 1
            return n

        n = asyncio.run(_run())
        # duration/interval ~= 5; allow scheduler slack but reject a flood.
        assert 1 <= n <= 12

    def test_heartbeat_seqs_are_monotonic(self):
        async def _run():
            seqs = []
            async for item in run_with_heartbeat(_sleep_return("x", 0.35), interval=0.1):
                if not isinstance(item, HeartbeatResult):
                    seqs.append(item["heartbeat"]["seq"])
            return seqs

        seqs = asyncio.run(_run())
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)

    def test_exception_is_captured_and_stops_heartbeats(self):
        # EC-5: a raising fn stops the heartbeat and surfaces the error in the
        # HeartbeatResult (caller re-raises / reports terminal).
        def _boom():
            time.sleep(0.15)
            raise RuntimeError("kaboom")

        async def _run():
            saw_result = None
            async for item in run_with_heartbeat(_boom, interval=0.05):
                if isinstance(item, HeartbeatResult):
                    saw_result = item
            return saw_result

        result = asyncio.run(_run())
        assert result.value is None
        assert isinstance(result.error, RuntimeError)
        assert "kaboom" in str(result.error)

    def test_result_is_the_last_item_yielded(self):
        # CT-3: the HeartbeatResult (terminal signal) is always last.
        async def _run():
            items = []
            async for item in run_with_heartbeat(_sleep_return("z", 0.25), interval=0.05):
                items.append(item)
            return items

        items = asyncio.run(_run())
        assert isinstance(items[-1], HeartbeatResult)
        assert all(not isinstance(i, HeartbeatResult) for i in items[:-1])


class TestTerminalLastProperty:
    """RT-1: for any step duration, exactly one terminal signal, emitted last."""

    def test_terminal_signal_always_terminates_for_random_durations(self):
        rng = random.Random(_PROP_SEED)

        async def _one(duration, interval):
            items = []
            async for item in run_with_heartbeat(_sleep_return("v", duration), interval=interval):
                items.append(item)
            return items

        for _ in range(40):
            duration = rng.uniform(0.0, 0.4)
            interval = rng.uniform(0.05, 0.2)
            items = asyncio.run(_one(duration, interval))
            terminals = [i for i in items if isinstance(i, HeartbeatResult)]
            assert len(terminals) == 1, f"seed={_PROP_SEED} dur={duration} int={interval}"
            assert isinstance(items[-1], HeartbeatResult)
            # heartbeats emitted iff the fn ran longer than one interval
            hb = [i for i in items if not isinstance(i, HeartbeatResult)]
            if duration > interval * 1.5:
                assert len(hb) >= 1


# ---------------------------------------------------------------------------
# Consumer parser (SC-5, RT-3, EC-3/EC-4)
# ---------------------------------------------------------------------------


class TestConsumerParser:
    def test_reads_terminal_payload_ignoring_heartbeats(self):
        payload = json.dumps({"status": "succeeded", "outcome": "fixed"})
        stream = [
            heartbeat_chunk(1),
            heartbeat_chunk(2),
            terminal_chunk(payload),
        ]
        text = read_terminal_payload(stream)
        assert json.loads(text)["status"] == "succeeded"

    def test_returns_none_when_no_terminal_chunk(self):
        stream = [heartbeat_chunk(1), heartbeat_chunk(2)]
        assert read_terminal_payload(stream) is None

    def test_fuzz_random_heartbeat_arrangements_never_mislead_parser(self):
        # RT-3: any count/order of heartbeats around one terminal chunk resolves
        # to that terminal payload, never a heartbeat, never raising.
        rng = random.Random("98_fuzz_0831")
        payload = json.dumps({"status": "failed", "error_code": "AUDIT_FINDINGS"})
        for _ in range(500):
            n_before = rng.randint(0, 8)
            n_after = 0  # terminal is always last by contract; extra beats precede it
            stream = [heartbeat_chunk(i) for i in range(n_before)]
            stream.append(terminal_chunk(payload))
            stream += [heartbeat_chunk(100 + i) for i in range(n_after)]
            text = read_terminal_payload(stream)
            assert text is not None
            assert json.loads(text)["error_code"] == "AUDIT_FINDINGS"
