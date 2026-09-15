"""
Best-effort terminal-report backstop on abrupt termination (issue #98, AC6).

The normal terminal-report contract is `RunReporter.__exit__`, which always
writes a terminal status on any normal Python exit. It does *not* run when the
process is killed abruptly. This module adds a best-effort layer for the
*interceptable* case:

  - On SIGTERM (graceful stop / some container-reclaim paths), a handler marks
    the active run `failed / SIGNAL_TERMINATION` so it does not sit `running`
    until the pg_cron reaper.
  - A true SIGKILL / OOM cannot be intercepted by any process — that path is
    documented (docs/technical-guidelines.md) as reaper-only, which is the
    designed backstop.

The handler must never raise (it runs inside a signal context), and any detail
text it reports must be scrubbed of secrets.
"""

from __future__ import annotations

import signal
from typing import Any

from scrubber import scrub

_SIGNAL_ERROR_CODE = "SIGNAL_TERMINATION"


def report_abrupt_termination(
    run: Any | None,
    *,
    signal_name: str,
    secrets: list[str],
    detail: str = "",
) -> None:
    """Best-effort: mark ``run`` failed due to an abrupt signal. Never raises.

    No-op when ``run`` is ``None`` (no active run) or already terminal. The
    error message is scrubbed of any known secrets (EC-7).
    """
    if run is None:
        return
    try:
        if getattr(run, "_terminal", False):
            return
        msg = f"Process received {signal_name} — reporting best-effort terminal status."
        if detail:
            msg = f"{msg} {detail}"
        msg = scrub(msg, secrets)
        run.fail(
            error_code=_SIGNAL_ERROR_CODE,
            error_message=msg,
            outcome="not_applicable",
        )
    except Exception:  # noqa: BLE001 — a backstop must never raise
        return


def install_termination_backstop(get_run, get_secrets) -> None:
    """Install a SIGTERM handler that best-effort reports the active run.

    ``get_run`` / ``get_secrets`` are zero-arg callables resolved lazily inside
    the handler so the latest run/secrets are used. SIGKILL is intentionally not
    handled (it cannot be); that path relies on the reaper.
    """

    def _handler(signum, _frame):
        report_abrupt_termination(
            get_run(),
            signal_name=signal.Signals(signum).name,
            secrets=get_secrets(),
        )
        # Restore default and re-raise so the process still terminates.
        signal.signal(signum, signal.SIG_DFL)
        signal.raise_signal(signum)

    try:
        signal.signal(signal.SIGTERM, _handler)
    except (ValueError, OSError):
        # Not on the main thread (e.g. under some test/harness contexts) —
        # skip silently; the reaper remains the backstop.
        return
