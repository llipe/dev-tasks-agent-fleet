# Copied from agents/security-analyst/app/securityAnalyst/tests/unit/test_signal_backstop.py
# Source commit: 8cfed33b9974f82047b065732ad956936d3fb5d0
# Extended (S-186): `handle_termination` edge cases for the disposition hook.
# Changed (S-190 fix round, DF-190-05): a `failed` report carries no outcome.
# Changed (S-190 fix round 2, #372): the process-wide handler, its registry,
# chaining, and the write-lock wait.
"""
Unit tests for the best-effort terminal-report backstop on abrupt termination
(issue #98, AC6 / EC-5 / EC-7).

On an *interceptable* signal (SIGTERM), the agent attempts a best-effort
terminal report so the run does not sit `running` until the reaper. A true
SIGKILL cannot be intercepted — that path is documented as reaper-only.

The reportable core is a pure function that, given a reporter-like object and a
secrets list, marks the run failed with a scrubbed message. We test that core
directly (no real signals) plus the handler registration wiring.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from signal_backstop import report_abrupt_termination


class TestReportAbruptTermination:
    def test_marks_run_failed_with_signal_error_code(self):
        run = MagicMock()
        run._terminal = False
        report_abrupt_termination(run, signal_name="SIGTERM", secrets=[])
        run.fail.assert_called_once()
        kwargs = run.fail.call_args.kwargs
        assert kwargs["error_code"] == "SIGNAL_TERMINATION"
        assert "SIGTERM" in kwargs["error_message"]
        # DF-190-05: like every failed result (outcomes.RunResult), no outcome.
        assert kwargs.get("outcome") is None

    def test_is_noop_when_already_terminal(self):
        run = MagicMock()
        run._terminal = True
        report_abrupt_termination(run, signal_name="SIGTERM", secrets=[])
        run.fail.assert_not_called()

    def test_scrubs_secrets_from_message(self):
        run = MagicMock()
        run._terminal = False
        secret = "ghs_supersecrettoken"
        report_abrupt_termination(
            run, signal_name="SIGTERM", secrets=[secret], detail=f"leak {secret} here"
        )
        msg = run.fail.call_args.kwargs["error_message"]
        assert secret not in msg
        assert "***" in msg

    def test_swallows_reporter_errors(self):
        # A backstop must never raise from within a signal handler.
        run = MagicMock()
        run._terminal = False
        run.fail.side_effect = RuntimeError("db down")
        # Should not raise.
        report_abrupt_termination(run, signal_name="SIGTERM", secrets=[])

    def test_handles_none_run(self):
        # No active run yet — must be a safe no-op.
        report_abrupt_termination(None, signal_name="SIGTERM", secrets=[])


class TestInstallTerminationBackstop:
    def test_registers_sigterm_handler_on_main_thread(self):
        import signal as _signal

        import signal_backstop
        from signal_backstop import install_termination_backstop

        original = _signal.getsignal(_signal.SIGTERM)
        # main installs the backstop at import; start from the default.
        _signal.signal(_signal.SIGTERM, _signal.SIG_DFL)
        try:
            target = install_termination_backstop(lambda: None, lambda: [])
            handler = _signal.getsignal(_signal.SIGTERM)
            # A handler was installed (no longer the default/previous object).
            assert callable(handler)
            assert handler is not _signal.SIG_DFL
            assert signal_backstop.is_backstop_handler(handler)
            assert handler.previous is _signal.SIG_DFL
            assert (target.installed, target.reason) == (True, "")
            assert signal_backstop.active_run() is target
        finally:
            _signal.signal(_signal.SIGTERM, original)
            signal_backstop.clear_active_run(signal_backstop.active_run())

    def test_registration_is_noop_off_main_thread(self):
        import threading

        import signal_backstop
        from signal_backstop import install_termination_backstop

        errors = []

        def _worker():
            try:
                # signal.signal raises ValueError off the main thread; the
                # backstop must not raise, and the reaper stays the fallback.
                install_termination_backstop(lambda: None, lambda: [])
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        t = threading.Thread(target=_worker)
        t.start()
        t.join()
        assert errors == []
        signal_backstop.clear_active_run(signal_backstop.active_run())


@pytest.fixture
def default_sigterm():
    """SIGTERM at SIG_DFL for the test, restored after; no active run left."""
    import signal as _signal

    import signal_backstop

    # Held now: a test may monkeypatch these, and this teardown can run first.
    set_handler, clear = _signal.signal, signal_backstop.clear_active_run
    original = _signal.getsignal(_signal.SIGTERM)
    set_handler(_signal.SIGTERM, _signal.SIG_DFL)
    try:
        yield
    finally:
        set_handler(_signal.SIGTERM, original)
        clear(signal_backstop._active)


class TestProcessBackstop:
    """S-190 fix round 2: one handler on the main thread, the live run via a registry."""

    def test_off_the_main_thread_a_missing_handler_is_reported_loudly(
        self, default_sigterm, caplog
    ):
        import threading

        import signal_backstop

        seen = {}

        def _worker():
            seen["target"] = signal_backstop.install_termination_backstop(lambda: None, list)

        with caplog.at_level("ERROR", logger="bug_fix.signal_backstop"):
            t = threading.Thread(target=_worker, name="agentcore-worker-loop")
            t.start()
            t.join()
        target = seen["target"]
        assert target.installed is False
        assert "SIG_DFL" in target.reason and "agentcore-worker-loop" in target.reason
        assert any("SIGTERM backstop not installed" in r.getMessage() for r in caplog.records)

    def test_off_the_main_thread_an_installed_handler_is_found(self, default_sigterm):
        import threading

        import signal_backstop

        assert signal_backstop.install_process_backstop("test") == (True, "")
        seen = {}

        def _worker():
            seen["target"] = signal_backstop.install_termination_backstop(lambda: None, list)

        t = threading.Thread(target=_worker)
        t.start()
        t.join()
        assert seen["target"].installed is True

    def test_install_is_idempotent(self, default_sigterm):
        import signal as _signal

        import signal_backstop

        signal_backstop.install_process_backstop()
        first = _signal.getsignal(_signal.SIGTERM)
        signal_backstop.install_process_backstop()
        assert _signal.getsignal(_signal.SIGTERM) is first

    def test_a_failing_install_is_reported(self, default_sigterm, monkeypatch, caplog):
        import signal as _signal

        import signal_backstop

        def _boom(*_a):
            raise OSError("nope")

        monkeypatch.setattr(_signal, "signal", _boom)
        with caplog.at_level("ERROR", logger="bug_fix.signal_backstop"):
            installed, reason = signal_backstop.install_process_backstop("test")
        assert installed is False and "OSError" in reason
        assert any("not installed at test" in r.getMessage() for r in caplog.records)

    def test_an_unreadable_handler_is_reported(self, monkeypatch):
        import signal as _signal

        import signal_backstop

        def _boom(*_a):
            raise RuntimeError("x")

        monkeypatch.setattr(_signal, "getsignal", _boom)
        installed, reason = signal_backstop.install_process_backstop()
        assert installed is False and "could not be read" in reason

    def test_the_handler_ends_the_active_run_then_chains_to_the_previous_one(self, default_sigterm):
        import signal as _signal

        import signal_backstop

        calls = []
        _signal.signal(_signal.SIGTERM, lambda s, f: calls.append(("previous", s)))
        signal_backstop.install_process_backstop()
        run = MagicMock()
        run._terminal = False
        run.fail.side_effect = lambda **kw: calls.append(("fail", kw["error_code"]))
        signal_backstop.install_termination_backstop(lambda: run, list)
        _signal.getsignal(_signal.SIGTERM)(_signal.SIGTERM, None)
        assert calls == [("fail", "SIGNAL_TERMINATION"), ("previous", _signal.SIGTERM)]

    def test_a_second_handler_for_the_same_run_only_chains(self, default_sigterm):
        import signal as _signal

        import signal_backstop

        chained = []
        _signal.signal(_signal.SIGTERM, lambda s, f: chained.append(s))
        signal_backstop.install_process_backstop()
        run = MagicMock()
        run._terminal = False
        signal_backstop.install_termination_backstop(lambda: run, list)
        handler = _signal.getsignal(_signal.SIGTERM)
        handler(_signal.SIGTERM, None)
        handler(_signal.SIGTERM, None)
        assert run.fail.call_count == 1
        assert chained == [_signal.SIGTERM, _signal.SIGTERM]

    def test_with_no_active_run_the_handler_only_chains(self, default_sigterm):
        import signal as _signal

        import signal_backstop

        chained = []
        _signal.signal(_signal.SIGTERM, lambda s, f: chained.append(s))
        signal_backstop.install_process_backstop()
        _signal.getsignal(_signal.SIGTERM)(_signal.SIGTERM, None)
        assert chained == [_signal.SIGTERM]

    def test_a_replaced_default_is_restored_and_re_raised(self, default_sigterm, monkeypatch):
        import signal as _signal

        import signal_backstop

        raised = []
        monkeypatch.setattr(_signal, "raise_signal", raised.append)
        signal_backstop.install_process_backstop()
        _signal.getsignal(_signal.SIGTERM)(_signal.SIGTERM, None)
        assert raised == [_signal.SIGTERM]
        assert _signal.getsignal(_signal.SIGTERM) is _signal.SIG_DFL

    def test_as_pid_1_the_process_exits_as_a_sigterm_death_would(
        self, default_sigterm, monkeypatch
    ):
        # In the image python is PID 1, and the kernel ignores a default-action
        # signal for a namespace's init: the re-raise alone would not end it.
        import os as _os
        import signal as _signal

        import signal_backstop

        exits = []
        monkeypatch.setattr(_signal, "raise_signal", lambda s: None)
        monkeypatch.setattr(_os, "getpid", lambda: 1)
        monkeypatch.setattr(_os, "_exit", exits.append)
        signal_backstop.install_process_backstop()
        _signal.getsignal(_signal.SIGTERM)(_signal.SIGTERM, None)
        assert exits == [128 + _signal.SIGTERM]

    def test_not_pid_1_the_re_raise_is_enough(self, default_sigterm, monkeypatch):
        import os as _os
        import signal as _signal

        import signal_backstop

        exits = []
        monkeypatch.setattr(_signal, "raise_signal", lambda s: None)
        monkeypatch.setattr(_os, "_exit", exits.append)
        signal_backstop.install_process_backstop()
        _signal.getsignal(_signal.SIGTERM)(_signal.SIGTERM, None)
        assert exits == []

    def test_a_replaced_ignore_stays_ignored(self, default_sigterm, monkeypatch):
        import signal as _signal

        import signal_backstop

        raised = []
        monkeypatch.setattr(_signal, "raise_signal", raised.append)
        _signal.signal(_signal.SIGTERM, _signal.SIG_IGN)
        signal_backstop.install_process_backstop()
        _signal.getsignal(_signal.SIGTERM)(_signal.SIGTERM, None)
        assert raised == []

    def test_a_raising_backstop_still_chains(self, default_sigterm, monkeypatch):
        import signal as _signal

        import signal_backstop

        chained = []
        _signal.signal(_signal.SIGTERM, lambda s, f: chained.append(s))
        signal_backstop.install_process_backstop()

        def _boom():
            raise RuntimeError("registry broke")

        monkeypatch.setattr(signal_backstop, "active_run", _boom)
        _signal.getsignal(_signal.SIGTERM)(_signal.SIGTERM, None)
        assert chained == [_signal.SIGTERM]

    def test_clearing_another_run_keeps_the_active_one(self):
        import signal_backstop

        a = signal_backstop.RunTarget(lambda: None, list)
        b = signal_backstop.RunTarget(lambda: None, list)
        signal_backstop.set_active_run(a)
        try:
            signal_backstop.clear_active_run(b)
            signal_backstop.clear_active_run(None)
            assert signal_backstop.active_run() is a
        finally:
            signal_backstop.clear_active_run(a)
        assert signal_backstop.active_run() is None

    def test_describe_names_every_kind_of_handler(self):
        import signal as _signal

        from signal_backstop import _describe

        assert _describe(_signal.SIG_DFL) == "SIG_DFL"
        assert _describe(_signal.SIG_IGN) == "SIG_IGN"
        assert _describe(None) == "a handler not installed from Python"
        assert _describe(len) == "len"


class _Run:
    """A reporter-like run with a write lock, as main.RunHandle has."""

    def __init__(self):
        import threading

        self.write_lock = threading.RLock()
        self._terminal = False
        self.fails = []
        self.stops = 0

    def request_stop(self):
        self.stops += 1

    def fail(self, **kw):
        self.fails.append(kw["error_code"])
        self._terminal = True


class TestHandleTerminationWithAWriteLock:
    def test_it_waits_for_a_write_in_flight_and_leaves_a_terminal_run(self):
        import threading
        import time

        from signal_backstop import handle_termination

        run = _Run()
        holding = threading.Event()

        def writer():
            with run.write_lock:
                holding.set()
                time.sleep(0.3)
                run._terminal = True  # the worker's own terminal write

        t = threading.Thread(target=writer)
        t.start()
        holding.wait(2)
        disposition = MagicMock()
        handle_termination(lambda: run, list, disposition, "SIGTERM", budget=5)
        t.join()
        assert run.fails == []  # one terminal write: the worker's
        disposition.assert_not_called()  # its owner disposed, if it had to
        assert run.stops == 1

    def test_a_write_in_flight_past_the_budget_is_left_alone(self, caplog):
        import threading

        from signal_backstop import handle_termination

        run = _Run()
        holding, release = threading.Event(), threading.Event()

        def writer():
            with run.write_lock:
                holding.set()
                release.wait(5)

        t = threading.Thread(target=writer)
        t.start()
        holding.wait(2)
        try:
            with caplog.at_level("ERROR", logger="bug_fix.signal_backstop"):
                handle_termination(lambda: run, list, None, "SIGTERM", budget=0.1)
        finally:
            release.set()
            t.join()
        assert run.fails == []
        assert any("still in flight" in r.getMessage() for r in caplog.records)

    def test_a_lock_taken_during_the_disposition_is_waited_for(self):
        import threading

        from signal_backstop import handle_termination

        run = _Run()
        release = threading.Event()
        started = threading.Event()

        def taker():
            with run.write_lock:
                started.set()
                release.wait(5)

        def action():
            threading.Thread(target=taker).start()
            started.wait(2)
            threading.Timer(0.2, release.set).start()
            return SimpleNamespace(status="applied")

        handle_termination(lambda: run, list, lambda: action, "SIGTERM", budget=5)
        assert run.fails == ["SIGNAL_TERMINATION"]

    def test_a_lock_that_stays_busy_after_the_disposition_is_reported(self, caplog):
        import threading

        from signal_backstop import handle_termination

        run = _Run()
        release = threading.Event()
        started = threading.Event()

        def taker():
            with run.write_lock:
                started.set()
                release.wait(5)

        def action():
            threading.Thread(target=taker).start()
            started.wait(2)

        try:
            with caplog.at_level("ERROR", logger="bug_fix.signal_backstop"):
                handle_termination(lambda: run, list, lambda: action, "SIGTERM", budget=0.05)
        finally:
            release.set()
        assert run.fails == []
        assert any("stayed busy" in r.getMessage() for r in caplog.records)

    def test_a_raising_stop_flag_is_swallowed(self):
        from signal_backstop import handle_termination

        run = _Run()

        def boom():
            raise RuntimeError("x")

        run.request_stop = boom
        handle_termination(lambda: run, list, None, "SIGTERM", budget=1)
        assert run.fails == ["SIGNAL_TERMINATION"]

    def test_a_raising_secrets_getter_is_swallowed(self):
        from signal_backstop import handle_termination

        run = _Run()

        def boom():
            raise RuntimeError("x")

        handle_termination(lambda: run, boom, None, "SIGTERM", budget=1)
        assert run.fails == []

    def test_the_deadline_reuses_the_path_with_its_own_code(self):
        from signal_backstop import handle_termination

        run = MagicMock()
        run._terminal = False
        handle_termination(
            lambda: run,
            list,
            None,
            "deadline",
            budget=1,
            error_code="RUNTIME_TIMEOUT",
            headline="past the deadline",
        )
        kwargs = run.fail.call_args.kwargs
        assert kwargs["error_code"] == "RUNTIME_TIMEOUT"
        assert kwargs["error_message"] == "past the deadline"


class TestHandleTerminationEdges:
    """S-186: the disposition hook never lets an error escape the handler."""

    def test_raising_disposition_still_fails_the_run(self):
        from signal_backstop import handle_termination

        run = MagicMock()
        run._terminal = False

        def action():
            raise RuntimeError("github down")

        handle_termination(lambda: run, list, lambda: action, "SIGTERM", budget=2)
        run.fail.assert_called_once()
        assert "attempted" in run.fail.call_args.kwargs["error_message"]

    def test_raising_run_getter_is_swallowed(self):
        from signal_backstop import handle_termination

        def boom():
            raise RuntimeError("no run")

        handle_termination(boom, list, None, "SIGTERM")


class TestHandleTerminationDetail:
    """DF-186-04: the ``fail()`` detail names what the disposition actually did."""

    @staticmethod
    def _message(get_disposition, budget=2.0):
        from signal_backstop import handle_termination

        run = MagicMock()
        run._terminal = False
        handle_termination(lambda: run, list, get_disposition, "SIGTERM", budget=budget)
        return run.fail.call_args.kwargs["error_message"]

    @pytest.mark.parametrize(
        ("status", "detail"),
        [
            ("applied", "Disposition posted before stopping."),
            (
                "already_disposed",
                "Disposition was already posted for this run; nothing new was written.",
            ),
            (
                "in_progress",
                "Disposition skipped: another disposition for this run was still in flight.",
            ),
            ("not_owned", "Disposition skipped: claim ownership was not confirmed."),
            ("something_else", "Disposition attempted before stopping."),
        ],
    )
    def test_detail_follows_the_result_status(self, status, detail):
        result = SimpleNamespace(status=status)
        assert self._message(lambda: lambda: result).endswith(detail)

    def test_no_action_means_ownership_not_confirmed(self):
        msg = self._message(lambda: None)
        assert msg.endswith("Disposition skipped: claim ownership was not confirmed.")

    def test_a_raising_getter_is_reported(self):
        def boom():
            raise RuntimeError("x")

        assert self._message(boom).endswith("Disposition skipped: it could not be prepared.")

    def test_a_raising_action_names_the_error_type(self):
        def action():
            raise TimeoutError("slow")

        msg = self._message(lambda: action)
        assert msg.endswith("Disposition attempted but failed (TimeoutError).")

    def test_a_timed_out_action_is_abandoned(self):
        import threading

        gate = threading.Event()
        try:
            msg = self._message(lambda: gate.wait, budget=0.1)
        finally:
            gate.set()
        assert msg.endswith("Disposition abandoned after 0.1 s.")

    def test_without_a_disposition_hook_there_is_no_detail(self):
        msg = self._message(None)
        assert "Disposition" not in msg
