"""L2 tests for the S-190 fix round 2 (issue #372).

- The SIGTERM backstop through the *real* install path: one handler on the
  main thread, the live run through the registry, a loud ``run_event`` when it
  is missing, the app-start install on top of a previous handler, and a real
  uvicorn server ending the process after one terminal write.
- The session reads busy while the run worker runs (QA gap 2).
- The run's deadline: between steps, after a confirmed claim, and in the
  relay for a worker stuck in a step (QA gap 7).
- A process stop out of the relay stops the worker: no GitHub write and no
  event on the ended run (QA gap 5).
- Every reporter write is serialized (QA gap 6).
- The branches QA listed as uncovered in ``main.py``.

Every test that starts a run joins its worker before it returns.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from bedrock_agentcore.runtime.models import PingStatus

import agent_reporter
import main
import outcomes
import signal_backstop
from heartbeat import heartbeat_chunk, is_heartbeat_chunk, read_terminal_payload
from scrubber import SecretSet
from tests.component import test_main as _test_main
from tests.component.repo_fixtures import result
from tests.component.test_main import (
    SB_KEY,
    TOKEN,
    WAVE_A_STEPS,
    Died,
    ReporterDB,
    _invoke,
    _slow_install,
    _write_shapes,
)

world = _test_main.world  # the fixture, shared with test_main.py

TERMINAL = ("succeeded", "failed")
WORKER = "bug-fix-run"
PKG = Path(main.__file__).resolve().parent


def _join_workers(timeout: float = 10.0) -> None:
    for t in threading.enumerate():
        if t.name == WORKER:
            t.join(timeout)
            assert not t.is_alive(), "the run worker did not finish"


def _terminal(db: ReporterDB) -> list[dict]:
    return [p for p in db.run_patches() if p.get("status") in TERMINAL]


@pytest.fixture
def sigterm_restored():
    """Whatever a test does to SIGTERM and the registry is undone after it."""
    set_handler = signal.signal
    original = signal.getsignal(signal.SIGTERM)
    try:
        yield
    finally:
        set_handler(signal.SIGTERM, original)
        signal_backstop.clear_active_run(signal_backstop._active)


def _blocked_install(w) -> threading.Event:
    """``install`` blocks until the returned event is set (a stuck step)."""
    release = threading.Event()

    def stuck(call):
        release.wait(10)
        return result(0, "ok")

    w.sandbox.answers[("make", "install")] = stuck
    return release


# ---------------------------------------------------------------------------
# The real install path
# ---------------------------------------------------------------------------


class TestTheRealInstallPath:
    def test_main_installs_the_backstop_at_import(self):
        assert signal_backstop.is_backstop_handler(signal.getsignal(signal.SIGTERM))

    def test_a_run_registers_with_the_real_installer_and_clears_at_the_end(
        self, world, sigterm_restored
    ):
        w = world(real_backstop=True)
        res, _, db = _invoke(w)
        assert (res["status"], res["outcome"]) == ("succeeded", "needs_review")
        assert not any("SIGTERM backstop" in m for m in db.messages())
        assert signal_backstop.active_run() is None  # the worker cleared it

    def test_the_live_run_is_the_registered_one_during_the_run(self, world, sigterm_restored):
        w = world(real_backstop=True, heartbeat_interval=0.02)
        _slow_install(w)
        seen: dict[str, Any] = {}

        async def go() -> None:
            agen = main.invoke(w.payload(), None)
            assert is_heartbeat_chunk(await agen.__anext__())
            target = signal_backstop.active_run()
            assert target is not None
            seen["run_id"] = target.get_run().run_id
            seen["secrets"] = target.get_secrets()
            async for _ in agen:
                pass

        try:
            asyncio.run(go())
        finally:
            _join_workers()
        assert seen["run_id"] == w.payload()["run_id"]
        assert SB_KEY in seen["secrets"] and TOKEN in seen["secrets"]

    def test_a_missing_handler_is_a_loud_run_event_and_the_run_still_ends(
        self, world, sigterm_restored
    ):
        # Off the main thread (the SDK's worker loop) nothing can install it.
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        w = world(real_backstop=True)
        chunks = list(
            main.app._async_gen_to_sync_gen(
                main.invoke(w.payload(), None), contextvars.copy_context()
            )
        )
        _join_workers()
        db = ReporterDB.instances[-1]
        errors = [e for e in db.events() if "SIGTERM backstop is not installed" in e["message"]]
        assert len(errors) == 1 and errors[0]["level"] == "error"
        assert "agentcore-worker-loop" in errors[0]["message"]
        assert json.loads(read_terminal_payload(chunks))["outcome"] == "needs_review"

    def test_app_start_puts_the_backstop_on_top_of_the_previous_handler(self, sigterm_restored):
        def uvicorn_like(signum, frame):  # stands in for uvicorn's handle_exit
            pass

        signal.signal(signal.SIGTERM, uvicorn_like)
        assert main.app.router.lifespan_context is main._lifespan

        async def start() -> None:
            async with main._lifespan(main.app):
                pass

        asyncio.run(start())
        handler = signal.getsignal(signal.SIGTERM)
        assert signal_backstop.is_backstop_handler(handler)
        assert handler.previous is uvicorn_like


_UVICORN_SCRIPT = textwrap.dedent(
    """
    import os, signal, sys, threading, time, urllib.request
    import main, signal_backstop

    port = int(sys.argv[1])

    class Run:
        _terminal = False

        def fail(self, **kw):
            print("FAIL", kw["error_code"], flush=True)
            self._terminal = True

    run = Run()

    def fire():
        for _ in range(400):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=1)
                break
            except Exception:
                time.sleep(0.05)
        handler = signal.getsignal(signal.SIGTERM)
        print("ON_TOP", signal_backstop.is_backstop_handler(handler),
              getattr(handler.previous, "__qualname__", handler.previous), flush=True)
        signal_backstop.install_termination_backstop(lambda: run, list)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=fire, daemon=True).start()
    # Like RunWorker: a non-daemon thread that would keep the process up.
    threading.Thread(target=time.sleep, args=(60,), name="bug-fix-run").start()
    main.serve(port)
    print("SERVE_RETURNED", flush=True)
    """
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestUnderUvicorn:
    def test_a_sigterm_fails_the_run_once_then_uvicorn_shuts_down_and_the_process_ends(self):
        """The real server: the app-start handler sits on uvicorn's, ends the run
        once, chains to uvicorn's shutdown; uvicorn restores the import-time
        handler and re-raises SIGTERM, which ends the process (exit 143/-15)
        although a non-daemon thread is still running."""
        env = {**os.environ, "PYTHONPATH": str(PKG)}
        started = time.monotonic()
        proc = subprocess.run(
            [sys.executable, "-c", _UVICORN_SCRIPT, str(_free_port())],
            cwd=PKG,
            env=env,
            capture_output=True,
            text=True,
            timeout=40,
        )
        lines = [
            ln for ln in proc.stdout.splitlines() if ln.startswith(("ON_TOP", "FAIL", "SERVE"))
        ]
        assert lines == ["ON_TOP True Server.handle_exit", "FAIL SIGNAL_TERMINATION"], (
            proc.stdout,
            proc.stderr[-2000:],
        )
        assert proc.returncode == -signal.SIGTERM
        assert time.monotonic() - started < 30  # not the 60 s thread


# ---------------------------------------------------------------------------
# Busy while the worker runs (QA gap 2)
# ---------------------------------------------------------------------------


def _ping_status() -> str:
    return json.loads(main.app._handle_ping(None).body)["status"]


class TestTheSessionIsBusyWhileTheWorkerRuns:
    def test_ping_is_busy_during_the_run_and_healthy_after(self, world):
        w = world(heartbeat_interval=0.02)
        _slow_install(w)
        seen: dict[str, Any] = {}

        async def go() -> None:
            agen = main.invoke(w.payload(), None)
            assert is_heartbeat_chunk(await agen.__anext__())
            seen["during"] = (main.app.get_current_ping_status(), _ping_status())
            seen["jobs"] = main.app.get_async_task_info()["running_jobs"]
            await agen.aclose()  # the panel goes away; the worker still runs
            seen["after_close"] = main.app.get_current_ping_status()

        try:
            asyncio.run(go())
        finally:
            _join_workers()
        assert seen["during"] == (PingStatus.HEALTHY_BUSY, "HealthyBusy")
        assert [j["name"] for j in seen["jobs"]] == ["bug-fix-run"]
        assert seen["after_close"] == PingStatus.HEALTHY_BUSY
        assert main.app.get_current_ping_status() == PingStatus.HEALTHY
        assert _ping_status() == "Healthy"
        assert main.app.get_async_task_info()["active_count"] == 0

    def test_a_failing_busy_mark_is_an_error_event_and_the_run_goes_on(self, world, monkeypatch):
        def boom(name, metadata=None):
            raise RuntimeError("no tracker")

        monkeypatch.setattr(main.app, "add_async_task", boom)
        w = world()
        res, _, db = _invoke(w)
        assert res["outcome"] == "needs_review"
        assert any(
            e["level"] == "error" and "could not be marked busy (RuntimeError)" in e["message"]
            for e in db.events()
        )


# ---------------------------------------------------------------------------
# The run's deadline (QA gap 7)
# ---------------------------------------------------------------------------


class TestRunBudget:
    @pytest.mark.parametrize(
        ("request_", "budget"),
        [
            ({}, 3600 - 120),
            ({"max_runtime_seconds": 600, "grace_seconds": 60}, 540),
            ({"max_runtime_seconds": 600}, 480),
            ({"max_runtime_seconds": 100, "grace_seconds": 200}, 0),
            ({"max_runtime_seconds": True, "grace_seconds": -5}, 3600 - 120),
            ({"max_runtime_seconds": "600", "grace_seconds": 0}, 3600 - 120),
        ],
    )
    def test_the_budget_is_max_runtime_minus_grace(self, request_, budget):
        assert main.run_budget_seconds(request_) == budget

    def test_runtime_timeout_is_in_the_closed_set(self):
        assert outcomes.RUNTIME_TIMEOUT in outcomes.ERROR_CODES
        assert outcomes.failed(outcomes.RUNTIME_TIMEOUT, "x").error_code == "RUNTIME_TIMEOUT"


class TestTheDeadline:
    def test_past_the_deadline_before_ownership_ends_runtime_timeout_with_no_write(self, world):
        w = world(run_budget=0.1)
        _slow_install(w)  # 0.3 s: the deadline passes during checkout
        res, _, db = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "RUNTIME_TIMEOUT")
        assert "before the claim step" in res["summary"]
        assert w.gh.writes() == []
        assert db.step_keys() == ["preflight", "refuse", "checkout"]
        assert [p["error_code"] for p in _terminal(db)] == ["RUNTIME_TIMEOUT"]
        assert "outcome" not in db.final()

    def test_past_the_deadline_after_a_confirmed_claim_still_disposes(self, world):
        now = [0.0]
        w = world(fix_loop=True, clock=lambda: now[0], run_budget=100.0)

        def hook(call) -> None:
            if call.method == "POST" and call.path.endswith("/reactions"):
                now[0] = 1_000.0  # the claim's 👀 landed; the clock jumps

        w.gh.hook = hook
        res, _, db = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "RUNTIME_TIMEOUT")
        assert "before the fix step" in res["summary"]
        assert [s for _, s in _write_shapes(w)] == [
            "comment:claim",
            "reaction:eyes",
            "comment:disposition",
            "reaction:confused",
        ]
        assert [p["error_code"] for p in _terminal(db)] == ["RUNTIME_TIMEOUT"]
        assert db.step_keys() == WAVE_A_STEPS

    def test_a_worker_stuck_past_the_deadline_is_ended_by_the_relay(self, world, monkeypatch):
        monkeypatch.setattr(main, "OVERDUE_SLACK_SECONDS", 0.1)
        w = world(run_budget=0.05, heartbeat_interval=0.02)
        release = _blocked_install(w)
        try:
            res, chunks, db = _invoke(w)
            terminal_now = list(_terminal(db))
        finally:
            release.set()
            _join_workers()
        assert (res["status"], res["error_code"]) == ("failed", "RUNTIME_TIMEOUT")
        assert "while a step was still running" in res["summary"]
        assert [(p["error_code"]) for p in terminal_now] == ["RUNTIME_TIMEOUT"]
        assert "ownership was not confirmed" in terminal_now[0]["error_message"]
        # Released, the worker stops at its next boundary: nothing more.
        assert w.gh.writes() == []
        assert len(_terminal(db)) == 1
        assert "claim" not in db.step_keys()

    def test_a_worker_that_reports_just_in_time_keeps_its_result(self, world, monkeypatch):
        w = world()
        ctx_seen: dict[str, Any] = {}
        real_worker = main.RunWorker

        class Worker(real_worker):  # type: ignore[misc, valid-type]
            def __init__(self, ctx):
                super().__init__(ctx)
                ctx_seen["w"] = self

            def join_until_deadline(self):
                self.join()
                raise main.RunOverdue()  # as if the relay timed out at the same time

        monkeypatch.setattr(main, "RunWorker", Worker)
        res, _, db = _invoke(w)
        _join_workers()
        assert res["outcome"] == "needs_review"
        assert [p["status"] for p in _terminal(db)] == ["succeeded"]

    def test_a_relay_fault_then_a_stuck_worker_ends_overdue(self, world, monkeypatch):
        monkeypatch.setattr(main, "OVERDUE_SLACK_SECONDS", 0.1)
        w = world(run_budget=0.05)
        release = _blocked_install(w)

        async def broken_relay(fn, *, interval, seq_start=0):
            yield heartbeat_chunk(1)
            raise RuntimeError("the relay broke")

        monkeypatch.setattr(main, "run_with_heartbeat", broken_relay)
        try:
            res, _, db = _invoke(w)
        finally:
            release.set()
            _join_workers()
        assert (res["status"], res["error_code"]) == ("failed", "RUNTIME_TIMEOUT")
        assert [p["error_code"] for p in _terminal(db)] == ["RUNTIME_TIMEOUT"]


# ---------------------------------------------------------------------------
# A process stop out of the relay stops the worker (QA gap 5)
# ---------------------------------------------------------------------------


class TestAProcessStopStopsTheWorker:
    @pytest.mark.parametrize("stop", [SystemExit, KeyboardInterrupt])
    def test_no_github_write_and_no_event_after_signal_termination(self, world, monkeypatch, stop):
        w = world(heartbeat_interval=0.02)
        _slow_install(w)

        async def dying_relay(fn, *, interval, seq_start=0):
            yield heartbeat_chunk(1)
            raise stop()

        monkeypatch.setattr(main, "run_with_heartbeat", dying_relay)

        async def go() -> list:
            return [c async for c in main.invoke(w.payload(), None)]

        try:
            with pytest.raises(stop):
                asyncio.run(go())
        finally:
            _join_workers()
        db = ReporterDB.instances[-1]
        terminal = _terminal(db)
        assert [(p["status"], p["error_code"]) for p in terminal] == [
            ("failed", "SIGNAL_TERMINATION")
        ]
        assert terminal[0]["error_message"] == f"the run stopped on {stop.__name__}"
        assert w.gh.writes() == []  # the worker never reached the claim
        # Nothing was written to the run after its terminal row, but closing
        # the step that was running.
        at = next(i for i, c in enumerate(db.calls) if c[1] == "runs" and c[2] is terminal[0])
        after = db.calls[at + 1 :]
        assert all(t == "run_steps" and op == "update" for op, t, _ in after), after
        assert "claim" not in db.step_keys()

    def test_a_worker_that_died_without_reporting_is_failed_by_the_entrypoint(
        self, world, monkeypatch
    ):
        def die(ctx):
            raise Died()

        monkeypatch.setattr(main, "execute", die)

        async def late_broken_relay(fn, *, interval, seq_start=0):
            _join_workers()  # the worker is gone, and wrote nothing
            yield heartbeat_chunk(1)
            raise RuntimeError("the relay broke")

        monkeypatch.setattr(main, "run_with_heartbeat", late_broken_relay)
        w = world()
        res, _, db = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "UNHANDLED_ERROR")
        assert [p["error_code"] for p in _terminal(db)] == ["UNHANDLED_ERROR"]


# ---------------------------------------------------------------------------
# Every reporter write is serialized (QA gap 6)
# ---------------------------------------------------------------------------


class _SlowDB(ReporterDB):
    in_flight = 0
    peak = 0
    guard = threading.Lock()

    def _enter(self) -> None:
        with _SlowDB.guard:
            _SlowDB.in_flight += 1
            _SlowDB.peak = max(_SlowDB.peak, _SlowDB.in_flight)
        time.sleep(0.002)
        with _SlowDB.guard:
            _SlowDB.in_flight -= 1

    def insert(self, table, rows):
        self._enter()
        return super().insert(table, rows)

    def update(self, table, filt, patch):
        self._enter()
        return super().update(table, filt, patch)


class TestReporterWritesAreSerialized:
    @staticmethod
    def _hammer(run: Any) -> None:
        def writer(i: int) -> None:
            for j in range(15):
                run.info(f"event {i}-{j}")
                run.flush()

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def test_concurrent_writers_never_overlap_on_the_handle(self, monkeypatch):
        monkeypatch.setattr(agent_reporter, "_SupabaseClient", _SlowDB)
        _SlowDB.peak = 0
        run = main.RunHandle(agent_reporter.RunReporter("u", "k", "r", capture_logging=False))
        self._hammer(run)
        assert _SlowDB.peak == 1
        seqs = [e["seq"] for e in ReporterDB.instances[-1].events()]
        assert sorted(seqs) == list(range(1, 91))  # no event lost or duplicated

    def test_without_the_handle_writers_do_overlap(self, monkeypatch):
        # The control: the vendored reporter alone is not thread-safe.
        monkeypatch.setattr(agent_reporter, "_SupabaseClient", _SlowDB)
        _SlowDB.peak = 0
        self._hammer(agent_reporter.RunReporter("u", "k", "r", capture_logging=False))
        assert _SlowDB.peak > 1

    def test_once_terminal_no_new_event_step_or_artifact(self, monkeypatch):
        monkeypatch.setattr(agent_reporter, "_SupabaseClient", ReporterDB)
        run = main.RunHandle(agent_reporter.RunReporter("u", "k", "r", capture_logging=False))
        run.start()
        run.fail("SIGNAL_TERMINATION", "stopped")
        db = ReporterDB.instances[-1]
        before = len(db.calls)
        run.info("late")
        run.warn("late")
        assert run.step("late") is None
        run.artifact("diff", url="x")
        run.flush()
        assert len(db.calls) == before
        assert run._terminal is True
        assert run.run_id == "r"  # reads pass through

    def test_a_signal_on_a_writing_thread_does_not_deadlock(self, monkeypatch):
        # The lock is re-entrant: the handler may run on the thread that writes.
        monkeypatch.setattr(agent_reporter, "_SupabaseClient", ReporterDB)
        run = main.RunHandle(agent_reporter.RunReporter("u", "k", "r", capture_logging=False))
        with run.write_lock:
            signal_backstop.handle_termination(lambda: run, list, None, "SIGTERM", budget=1)
        assert ReporterDB.instances[-1].final()["error_code"] == "SIGNAL_TERMINATION"
        assert run.stop_requested is True


# ---------------------------------------------------------------------------
# The branches QA listed as uncovered in main.py
# ---------------------------------------------------------------------------


class TestUncoveredBranches:
    def test_report_without_a_pre_report_note(self):
        run = MagicMock()
        ctx = SimpleNamespace(on_report=None, run=run, metrics=dict, secrets=SecretSet())
        main._report(ctx, outcomes.failed("UNHANDLED_ERROR", "x"))  # type: ignore[arg-type]
        run.fail.assert_called_once()

    def test_a_failing_pre_report_note_keeps_the_report(self, world, monkeypatch, caplog):
        def boom(self):
            raise RuntimeError("note broke")

        monkeypatch.setattr(main.RunWorker, "_note_close", boom)
        w = world()
        with caplog.at_level(logging.WARNING, logger="bug_fix"):
            res, _, db = _invoke(w)
        assert res["outcome"] == "needs_review"
        assert db.final()["outcome"] == "needs_review"
        assert any("pre-report note failed" in r.getMessage() for r in caplog.records)

    def test_a_raising_step_plan_is_unhandled_error(self, world, monkeypatch):
        def boom(ctx):
            raise RuntimeError("the plan broke")

        monkeypatch.setattr(main, "_steps", boom)
        w = world()
        res, _, db = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "UNHANDLED_ERROR")
        assert db.final()["error_code"] == "UNHANDLED_ERROR"

    def test_a_close_before_any_worker_exists(self, world, monkeypatch, caplog):
        # The probe refusal yields before a worker exists; closing there is
        # the GeneratorExit branch with no worker.
        monkeypatch.delenv("ALLOW_PROBE", raising=False)
        w = world()

        async def go() -> None:
            agen = main.invoke({**w.payload(), "__probe": True}, None)
            await agen.__anext__()
            await agen.aclose()

        with caplog.at_level(logging.WARNING, logger="bug_fix"):
            asyncio.run(go())
        db = ReporterDB.instances[-1]
        assert db.final()["error_code"] == "PROBE_REFUSED"
        assert any("had already reported" in r.getMessage() for r in caplog.records)
        assert signal_backstop.active_run() is None

    def test_a_stop_that_nobody_ends_is_reported_by_the_worker(self, world, monkeypatch):
        # A backstop that gave up on the write lock requested a stop and wrote
        # nothing: the worker still writes the run's one terminal row.
        monkeypatch.setattr(main, "STOP_WAIT_SECONDS", 0.1)
        w = world()
        real_execute = main.execute

        def execute(ctx):
            ctx.run.request_stop()
            return real_execute(ctx)

        monkeypatch.setattr(main, "execute", execute)
        res, _, db = _invoke(w)
        assert (res["status"], res["error_code"]) == ("failed", "SIGNAL_TERMINATION")
        assert db.step_keys() == []
        assert w.gh.writes() == []
        assert [p["error_code"] for p in _terminal(db)] == ["SIGNAL_TERMINATION"]

    def test_a_disposition_after_a_stop_is_skipped(self):
        disposer = SimpleNamespace(ownership_confirmed=True)
        run = SimpleNamespace(stop_requested=True, _terminal=False)
        ctx = SimpleNamespace(disposer=disposer, run=run, disposition_attempted=False)
        ctx.stopped = lambda: main.RunContext.stopped(ctx)  # type: ignore[arg-type]
        res = main.dispose_needs_review(ctx, "r", "w", "t")  # type: ignore[arg-type]
        assert res.error_code == "SIGNAL_TERMINATION"
        main._finally_dispose(ctx, res)  # type: ignore[arg-type]
        assert ctx.disposition_attempted is False
