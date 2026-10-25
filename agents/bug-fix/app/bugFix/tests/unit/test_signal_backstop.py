# Copied from agents/security-analyst/app/securityAnalyst/tests/unit/test_signal_backstop.py
# Source commit: 8cfed33b9974f82047b065732ad956936d3fb5d0
# Extended (S-186): `handle_termination` edge cases for the disposition hook.
# Changed (S-190 fix round, DF-190-05): a `failed` report carries no outcome.
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
