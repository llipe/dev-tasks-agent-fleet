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

from unittest.mock import MagicMock

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
        assert kwargs["outcome"] == "not_applicable"

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

        from signal_backstop import install_termination_backstop

        original = _signal.getsignal(_signal.SIGTERM)
        try:
            install_termination_backstop(lambda: None, lambda: [])
            handler = _signal.getsignal(_signal.SIGTERM)
            # A handler was installed (no longer the default/previous object).
            assert callable(handler)
            assert handler is not original
        finally:
            _signal.signal(_signal.SIGTERM, original)

    def test_registration_is_noop_off_main_thread(self):
        import threading

        from signal_backstop import install_termination_backstop

        errors = []

        def _worker():
            try:
                # signal.signal raises ValueError off the main thread; the
                # backstop must swallow it and leave the reaper as the fallback.
                install_termination_backstop(lambda: None, lambda: [])
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        t = threading.Thread(target=_worker)
        t.start()
        t.join()
        assert errors == []
