"""L2 tests for the S-190 fix-round run-ownership design (QA-190-01; issue #372).

``RunWorker`` owns the run and its one terminal write; the entrypoint only
relays; the SIGTERM backstop ends the run ``SIGNAL_TERMINATION``. The tests
in ``test_main.py`` call the backstop's body from *inside* the running step,
on the worker thread, so they never let the handler and the worker run at the
same time. In production the handler runs on the main thread while the worker
keeps going. These tests run them concurrently:

- a SIGTERM on the main thread while the worker is mid-step;
- a SIGTERM inside the worker's own terminal write (strict xfail, a defect);
- a relay failure while the worker still runs (strict xfail, a defect);
- the backstop through the AgentCore SDK's real async-generator bridge
  (strict xfail, a defect);
- a stream close after the worker already finished (an untested branch);
- two invocations in one process, one after the other.

Every test joins the worker thread before it returns, so no run outlives it.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import signal
import threading
from typing import Any

import pytest

import main
import signal_backstop
from heartbeat import heartbeat_chunk, is_heartbeat_chunk, read_terminal_payload
from tests.component import test_main as _test_main
from tests.component.test_main import (
    SB_KEY,
    TOKEN,
    WAVE_A_STEPS,
    ReporterDB,
    _sigterm,
    _slow_install,
    _with_payload,
    _write_shapes,
)

world = _test_main.world  # the fixture, shared with test_main.py

TERMINAL = ("succeeded", "failed")
WORKER = "bug-fix-run"


def _join_workers(timeout: float = 10.0) -> None:
    """Wait for every ``RunWorker`` thread, so no run leaks into the next test."""
    for t in threading.enumerate():
        if t.name == WORKER:
            t.join(timeout)
            assert not t.is_alive(), "the run worker did not finish"


def _terminal(db: ReporterDB) -> list[dict]:
    return [p for p in db.run_patches() if p.get("status") in TERMINAL]


# ---------------------------------------------------------------------------
# SIGTERM on the main thread while the worker runs
# ---------------------------------------------------------------------------


class TestSigtermConcurrentWithTheWorker:
    def test_a_sigterm_mid_step_before_ownership_is_one_terminal_write(self, world):
        """The handler (main thread) fails the run while the worker is in
        ``install``. It disposes nothing, and the worker's own report later is
        a no-op: one terminal row, ``SIGNAL_TERMINATION``."""
        w = world(heartbeat_interval=0.02)
        _slow_install(w)
        seen: dict[str, Any] = {}

        async def go() -> None:
            agen = main.invoke(w.payload(), None)
            assert is_heartbeat_chunk(await agen.__anext__())
            assert threading.current_thread() is threading.main_thread()
            _sigterm(w)  # the handler's body, on the main thread, worker live
            db = ReporterDB.instances[-1]
            seen["terminal"] = list(_terminal(db))
            seen["writes"] = list(w.gh.writes())
            await agen.aclose()

        try:
            asyncio.run(go())
        finally:
            _join_workers()
        assert [(p["status"], p["error_code"]) for p in seen["terminal"]] == [
            ("failed", "SIGNAL_TERMINATION")
        ]
        assert "ownership was not confirmed" in seen["terminal"][0]["error_message"]
        assert seen["writes"] == []
        db = ReporterDB.instances[-1]
        assert len(_terminal(db)) == 1, _terminal(db)
        blob = json.dumps(db.calls)
        assert SB_KEY not in blob and TOKEN not in blob

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "DEFECT: RunReporter._terminate sets _terminal=True before its flush "
            "and its runs PATCH. A SIGTERM handled on the main thread inside that "
            "window sees _terminal, skips fail(), then re-raises SIGTERM with "
            "SIG_DFL and the process dies before the worker's PATCH lands: zero "
            "terminal writes, the run stays 'running' until the reaper. Expected: "
            "the handler waits (bounded) for an in-flight terminal write, or the "
            "terminal write is serialized under one lock shared with the handler."
        ),
    )
    def test_a_sigterm_inside_the_workers_terminal_write_leaves_one_terminal_row(
        self, world, monkeypatch
    ):
        w = world(heartbeat_interval=0.02)
        entered, release = threading.Event(), threading.Event()
        real_update = ReporterDB.update

        def update(self, table, filt, patch):
            if (
                table == "runs"
                and patch.get("status") in TERMINAL
                and threading.current_thread().name == WORKER
            ):
                entered.set()  # _terminal is already True; the PATCH is in flight
                release.wait(10)
            return real_update(self, table, filt, patch)

        monkeypatch.setattr(ReporterDB, "update", update)
        seen: dict[str, Any] = {}

        async def go() -> None:
            agen = main.invoke(w.payload(), None)
            try:
                assert is_heartbeat_chunk(await agen.__anext__())
                assert entered.wait(10), "the worker never reached its terminal write"
                _sigterm(w)
                # Here the real handler re-raises SIGTERM with SIG_DFL: the
                # process is gone, so whatever has landed now is all there is.
                seen["terminal"] = list(_terminal(ReporterDB.instances[-1]))
            finally:
                release.set()
                await agen.aclose()

        try:
            asyncio.run(go())
        finally:
            release.set()
            _join_workers()
        assert len(seen["terminal"]) == 1, seen["terminal"]


# ---------------------------------------------------------------------------
# The relay fails while the worker still runs
# ---------------------------------------------------------------------------


class TestRelayFailure:
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "DEFECT: when the relay (run_with_heartbeat) raises an Exception while "
            "the worker still runs, invoke()'s `except Exception` calls "
            "run.fail('UNHANDLED_ERROR') from the entrypoint thread. That is a "
            "second writer on the non-thread-safe reporter during the run, and it "
            "takes the terminal write from the worker: the row says failed/"
            "UNHANDLED_ERROR (counted by the breaker, D-20) while the worker goes "
            "on to claim and dispose the issue, and its real needs_review report "
            "is dropped as a no-op. Expected: with worker.running, the entrypoint "
            "only logs (as on GeneratorExit/CancelledError) and the worker writes "
            "the one terminal row."
        ),
    )
    def test_a_relay_failure_mid_run_leaves_the_terminal_write_to_the_worker(
        self, world, monkeypatch
    ):
        w = world(heartbeat_interval=0.02)
        _slow_install(w)

        async def broken_relay(fn, *, interval, seq_start=0):
            yield heartbeat_chunk(1)
            raise RuntimeError("the relay broke")

        monkeypatch.setattr(main, "run_with_heartbeat", broken_relay)

        async def go() -> list:
            return [c async for c in main.invoke(w.payload(), None)]

        try:
            asyncio.run(go())
        finally:
            _join_workers()
        db = ReporterDB.instances[-1]
        terminal = _terminal(db)
        assert len(terminal) == 1, terminal
        assert (terminal[0]["status"], terminal[0].get("outcome")) == (
            "succeeded",
            "needs_review",
        )


# ---------------------------------------------------------------------------
# The backstop through the SDK's real bridge
# ---------------------------------------------------------------------------


class TestBackstopUnderTheSdk:
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "DEFECT: bedrock-agentcore 1.22.0 iterates an async-generator "
            "entrypoint on its daemon 'agentcore-worker-loop' thread "
            "(BedrockAgentCoreApp._async_gen_to_sync_gen), not the main thread. "
            "install_termination_backstop() is called inside invoke(), so "
            "signal.signal raises ValueError and the backstop silently returns: "
            "in production no SIGTERM handler is installed, no SIGNAL_TERMINATION "
            "is written and no D-81 disposition runs on SIGTERM. The tests in "
            "test_main.py replace install_termination_backstop, so they never see "
            "it. Expected: the handler is installed on the main thread (at import "
            "or app start) and resolves the live run through a registry."
        ),
    )
    def test_a_sigterm_mid_run_under_the_sdk_bridge_ends_signal_termination(
        self, world, monkeypatch
    ):
        w = world(heartbeat_interval=0.02)
        _slow_install(w)
        # The real installer, not the fixture's recorder.
        monkeypatch.setattr(
            main, "install_termination_backstop", signal_backstop.install_termination_backstop
        )
        # The handler re-raises SIGTERM with SIG_DFL; never kill the test process.
        monkeypatch.setattr(signal, "raise_signal", lambda signum: None)
        before = signal.getsignal(signal.SIGTERM)
        try:
            chunks = main.app._async_gen_to_sync_gen(
                main.invoke(w.payload(), None), contextvars.copy_context()
            )
            first = next(chunks)
            assert is_heartbeat_chunk(first)
            handler = signal.getsignal(signal.SIGTERM)
            if callable(handler):
                handler(signal.SIGTERM, None)  # as the kernel would deliver it
            rest = list(chunks)
            assert read_terminal_payload([first, *rest]) is not None
        finally:
            signal.signal(signal.SIGTERM, before)
            _join_workers()
        final = ReporterDB.instances[-1].final()
        assert (final["status"], final.get("error_code")) == ("failed", "SIGNAL_TERMINATION")


# ---------------------------------------------------------------------------
# A stream close after the worker finished (the untested branch)
# ---------------------------------------------------------------------------


class TestCloseAfterTheWorkerFinished:
    def test_a_close_after_the_worker_reported_adds_nothing(self, world, caplog):
        w = world(heartbeat_interval=0.02)
        _slow_install(w)

        async def go() -> None:
            agen = main.invoke(w.payload(), None)
            assert is_heartbeat_chunk(await agen.__anext__())
            _join_workers()  # the worker has reported; the relay is parked on a yield
            await agen.aclose()

        with caplog.at_level(logging.WARNING, logger="bug_fix"):
            asyncio.run(go())
        db = ReporterDB.instances[-1]
        terminal = _terminal(db)
        assert len(terminal) == 1, terminal
        assert (terminal[0]["status"], terminal[0]["outcome"]) == ("succeeded", "needs_review")
        assert not any("invoke stream closed" in m for m in db.messages())
        assert any("had already reported" in r.getMessage() for r in caplog.records)
        assert not any(
            p.get("error_code") in ("GeneratorExit", "CancelledError") for p in db.run_patches()
        )


# ---------------------------------------------------------------------------
# Two invocations in one process
# ---------------------------------------------------------------------------


class TestTwoInvocationsInOneProcess:
    def test_the_second_run_inherits_no_state_from_the_first(self, world):
        """Run 1's stream closes mid-run; run 2 starts after its worker ends.
        Each run has its own reporter and worker: no close note, no write and
        no backstop target carries over."""
        w = world(heartbeat_interval=0.02)
        _slow_install(w)

        async def close_mid_run() -> None:
            agen = main.invoke(w.payload(), None)
            assert is_heartbeat_chunk(await agen.__anext__())
            await agen.aclose()

        asyncio.run(close_mid_run())
        _join_workers()
        first = ReporterDB.instances[-1]
        first_calls = len(first.calls)
        assert any("invoke stream closed" in m for m in first.messages())

        _with_payload(w, run_id="not-a-uuid")

        async def second() -> list:
            return [c async for c in main.invoke(w.payload(), None)]

        chunks = asyncio.run(second())
        _join_workers()
        db = ReporterDB.instances[-1]
        assert db is not first
        assert len(first.calls) == first_calls  # nothing written to run 1 afterwards
        assert db.step_keys() == ["preflight"]
        assert not any("invoke stream closed" in m for m in db.messages())
        final = db.final()
        assert (final["status"], final["error_code"]) == ("failed", "INVALID_PAYLOAD")
        assert json.loads(read_terminal_payload(chunks))["error_code"] == "INVALID_PAYLOAD"
        # The backstop now resolves run 2, not run 1.
        assert w.backstop["run"]().run_id == "not-a-uuid"
        # Run 1 stayed a full Wave A run.
        assert first.step_keys() == WAVE_A_STEPS
        assert first.final()["outcome"] == "needs_review"
        assert [s for _, s in _write_shapes(w)].count("comment:disposition") == 1
