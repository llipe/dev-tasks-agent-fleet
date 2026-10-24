# Copied from agents/security-analyst/app/securityAnalyst/signal_backstop.py
# Source commit: 8cfed33b9974f82047b065732ad956936d3fb5d0
# Extended (S-186): before `fail()`, the handler runs the run's disposition
# with a 10-second budget, only when the claim's ownership is confirmed (D-81).
# `report_abrupt_termination` is unchanged.
"""
Best-effort terminal-report backstop on abrupt termination (issue #98, AC6).

The normal terminal-report contract is `RunReporter.__exit__`, which always
writes a terminal status on any normal Python exit. It does *not* run when the
process is killed abruptly. This module adds a best-effort layer for the
*interceptable* case:

  - On SIGTERM (graceful stop / some container-reclaim paths), a handler marks
    the active run `failed / SIGNAL_TERMINATION` so it does not sit `running`
    until the pg_cron reaper.
  - bug-fix (S-186): first, if the run has confirmed ownership of its claim,
    the handler applies the disposition (diagnosis comment, 😕, board
    ``Ready``) in a worker thread and waits at most
    ``DISPOSITION_BUDGET_SECONDS``. A disposition still running at the budget
    is abandoned and ``fail()`` runs anyway; the reaper and a later
    ``/bug-fix`` are the recovery (D-94). Without confirmed ownership, nothing
    is posted (D-81).
  - A true SIGKILL / OOM cannot be intercepted by any process — that path is
    documented (docs/technical-guidelines.md) as reaper-only, which is the
    designed backstop.

The handler must never raise (it runs inside a signal context), and any detail
text it reports must be scrubbed of secrets.
"""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable
from typing import Any

from scrubber import scrub

log = logging.getLogger("bug_fix.signal_backstop")

_SIGNAL_ERROR_CODE = "SIGNAL_TERMINATION"
DISPOSITION_BUDGET_SECONDS = 10.0

# Returns the disposition to run, or None (no confirmed ownership).
DispositionGetter = Callable[[], Callable[[], object] | None]


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


def run_with_budget(action: Callable[[], object], budget: float) -> bool:
    """Run ``action`` in a daemon thread; True if it ended within ``budget`` s.

    An exception in ``action`` is logged (by type only) and counts as ended. A
    thread still running at the budget is abandoned; it dies with the process.
    """
    done = threading.Event()

    def _target() -> None:
        try:
            action()
        except Exception as exc:  # noqa: BLE001 — a backstop must never raise
            log.warning("backstop disposition failed (%s)", type(exc).__name__)
        finally:
            done.set()

    threading.Thread(target=_target, name="bug-fix-backstop-disposition", daemon=True).start()
    return done.wait(budget)


def handle_termination(
    get_run: Callable[[], Any],
    get_secrets: Callable[[], list[str]],
    get_disposition: DispositionGetter | None,
    signal_name: str,
    budget: float = DISPOSITION_BUDGET_SECONDS,
) -> None:
    """Dispose (if ownership is confirmed, within ``budget``), then ``fail()``. Never raises."""
    detail = ""
    action = None
    if get_disposition is not None:
        try:
            action = get_disposition()
        except Exception:  # noqa: BLE001 — a backstop must never raise
            action = None
    if action is not None:
        if run_with_budget(action, budget):
            detail = "Disposition attempted before stopping."
        else:
            detail = f"Disposition abandoned after {budget:g} s."
    try:
        run = get_run()
        secrets = get_secrets()
    except Exception:  # noqa: BLE001 — a backstop must never raise
        return
    report_abrupt_termination(run, signal_name=signal_name, secrets=secrets, detail=detail)


def install_termination_backstop(
    get_run: Callable[[], Any],
    get_secrets: Callable[[], list[str]],
    get_disposition: DispositionGetter | None = None,
    *,
    budget: float = DISPOSITION_BUDGET_SECONDS,
) -> None:
    """Install a SIGTERM handler that best-effort disposes and reports the active run.

    ``get_run`` / ``get_secrets`` / ``get_disposition`` are zero-arg callables
    resolved lazily inside the handler so the latest state is used. SIGKILL is
    intentionally not handled (it cannot be); that path relies on the reaper.
    """

    def _handler(signum, _frame):
        handle_termination(
            get_run,
            get_secrets,
            get_disposition,
            signal.Signals(signum).name,
            budget,
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
