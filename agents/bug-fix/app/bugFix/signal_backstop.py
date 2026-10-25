# Copied from agents/security-analyst/app/securityAnalyst/signal_backstop.py
# Source commit: 8cfed33b9974f82047b065732ad956936d3fb5d0
# Extended (S-186): before `fail()`, the handler runs the run's disposition
# with a 10-second budget, only when the claim's ownership is confirmed (D-81).
# The `fail()` detail names what the disposition did: posted, already posted,
# skipped, failed or abandoned.
# Changed (S-190 fix round, DF-190-05): `report_abrupt_termination` no longer
# passes `outcome="not_applicable"`; a `failed` run carries no outcome, as
# `outcomes.RunResult` requires.
# Changed (S-190 fix round 2, #372): one process-wide SIGTERM handler installed
# on the main thread (at import and at app start), resolving the live run
# through a registry; it chains to the handler it replaced. The handler waits,
# within its budget, for a reporter write in flight (the run's `write_lock`).
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

**Where the handler lives (S-190 fix round 2).** ``signal.signal`` works only
on the main thread, and bedrock-agentcore runs an async-generator entrypoint
on its own ``agentcore-worker-loop`` thread, so a handler installed from the
entrypoint never lands. Instead :func:`install_process_backstop` installs one
handler on the main thread (``main`` calls it at import and at app start),
and each run registers itself with :func:`set_active_run`. Each install wraps
the handler it replaces and chains to it after the backstop, so uvicorn's own
shutdown still runs; a replaced ``SIG_DFL`` is restored and the signal
re-raised, so the process still ends. As PID 1 (the image's exec-form
``CMD``) the kernel ignores that re-raise, so the handler then calls
``os._exit(128 + signum)``.

**One terminal write.** A run whose reporter carries a ``write_lock`` (see
``main.RunHandle``) has every write serialized behind it. The handler waits,
within its budget, for a write in flight. When the run turned terminal
meanwhile, it does nothing more; otherwise it disposes (outside the lock, the
disposition writes events) and then fails the run under the lock.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from scrubber import scrub

log = logging.getLogger("bug_fix.signal_backstop")

_SIGNAL_ERROR_CODE = "SIGNAL_TERMINATION"
DISPOSITION_BUDGET_SECONDS = 10.0
# After a disposition used up the budget, fail() still waits this long for
# the write lock, so the run is not left ``running`` for want of a few ms.
_REPORT_WAIT_FLOOR_SECONDS = 1.0
_MARK = "_bug_fix_backstop"

# Returns the disposition to run, or None (no confirmed ownership).
DispositionGetter = Callable[[], Callable[[], object] | None]


def report_abrupt_termination(
    run: Any | None,
    *,
    signal_name: str,
    secrets: list[str],
    detail: str = "",
    error_code: str = _SIGNAL_ERROR_CODE,
    headline: str | None = None,
) -> None:
    """Best-effort: mark ``run`` failed due to an abrupt signal. Never raises.

    No-op when ``run`` is ``None`` (no active run) or already terminal. The
    error message is scrubbed of any known secrets (EC-7). ``error_code`` and
    ``headline`` let the run deadline reuse this path (``RUNTIME_TIMEOUT``).
    """
    if run is None:
        return
    try:
        if getattr(run, "_terminal", False):
            return
        msg = headline or (
            f"Process received {signal_name} — reporting best-effort terminal status."
        )
        if detail:
            msg = f"{msg} {detail}"
        msg = scrub(msg, secrets)
        # No outcome: a failed run has none (DF-190-05, outcomes.RunResult).
        run.fail(error_code=error_code, error_message=msg)
    except Exception:  # noqa: BLE001 — a backstop must never raise
        return


def run_with_budget(action: Callable[[], object], budget: float) -> bool:
    """Run ``action`` in a daemon thread; True if it ended within ``budget`` s.

    An exception in ``action`` is logged (by type only) and counts as ended. A
    thread still running at the budget is abandoned; it dies with the process.
    """
    return _run_with_budget(action, budget)[0]


def _run_with_budget(
    action: Callable[[], object], budget: float
) -> tuple[bool, object, BaseException | None]:
    """Like :func:`run_with_budget`, also returning the result or the exception."""
    done = threading.Event()
    outcome: dict[str, Any] = {"result": None, "error": None}

    def _target() -> None:
        try:
            outcome["result"] = action()
        except Exception as exc:  # noqa: BLE001 — a backstop must never raise
            log.warning("backstop disposition failed (%s)", type(exc).__name__)
            outcome["error"] = exc
        finally:
            done.set()

    threading.Thread(target=_target, name="bug-fix-backstop-disposition", daemon=True).start()
    finished = done.wait(budget)
    return finished, outcome["result"], outcome["error"]


_DETAILS = {
    "applied": "Disposition posted before stopping.",
    "already_disposed": "Disposition was already posted for this run; nothing new was written.",
    "in_progress": "Disposition skipped: another disposition for this run was still in flight.",
    "not_owned": "Disposition skipped: claim ownership was not confirmed.",
}


def _detail(finished: bool, result: object, error: BaseException | None, budget: float) -> str:
    """The ``fail()`` detail naming what the backstop's disposition did."""
    if not finished:
        return f"Disposition abandoned after {budget:g} s."
    if error is not None:
        return f"Disposition attempted but failed ({type(error).__name__})."
    status = getattr(result, "status", None)
    return _DETAILS.get(
        status if isinstance(status, str) else "", "Disposition attempted before stopping."
    )


def _is_terminal(run: Any) -> bool:
    return getattr(run, "_terminal", False) is True


def _write_lock(run: Any) -> Any | None:
    """The run's write lock (``main.RunHandle.write_lock``), or None."""
    lock = getattr(run, "write_lock", None)
    return lock if callable(getattr(lock, "acquire", None)) else None


def _request_stop(run: Any) -> None:
    """Tell the run's worker to stop between steps (``main.RunHandle``)."""
    stop = getattr(run, "request_stop", None)
    if callable(stop):
        try:
            stop()
        except Exception:  # noqa: BLE001 — a backstop must never raise
            log.warning("the run's stop flag could not be set")


def handle_termination(
    get_run: Callable[[], Any],
    get_secrets: Callable[[], list[str]],
    get_disposition: DispositionGetter | None,
    signal_name: str,
    budget: float = DISPOSITION_BUDGET_SECONDS,
    *,
    error_code: str = _SIGNAL_ERROR_CODE,
    headline: str | None = None,
) -> None:
    """Dispose (if ownership is confirmed, within ``budget``), then ``fail()``. Never raises.

    With a run that has a ``write_lock``, the whole body fits in ``budget``:

    1. stop the worker between steps;
    2. wait for a write in flight; a run that turned terminal is left as is
       (its owner reported, and disposed if it had to), so there is exactly
       one terminal write in every interleaving;
    3. dispose, outside the lock, with what is left of the budget;
    4. ``fail()`` under the lock (a no-op if the run turned terminal).
    """
    started = time.monotonic()

    def left() -> float:
        return max(0.0, budget - (time.monotonic() - started))

    try:
        run = get_run()
    except Exception:  # noqa: BLE001 — a backstop must never raise
        return
    _request_stop(run)
    lock = _write_lock(run)
    if lock is not None:
        if not lock.acquire(timeout=left()):
            log.error(
                "backstop: a reporter write was still in flight after %g s; "
                "the run's own write stands",
                budget,
            )
            return
        try:
            terminal = _is_terminal(run)
        finally:
            lock.release()
        if terminal:
            log.info("backstop: the run is already terminal; nothing to do")
            return
    detail = ""
    action = None
    if get_disposition is not None:
        try:
            action = get_disposition()
        except Exception:  # noqa: BLE001 — a backstop must never raise
            detail = "Disposition skipped: it could not be prepared."
        else:
            if action is None:
                detail = _DETAILS["not_owned"]
    if action is not None:
        remaining = left() if lock is not None else budget
        detail = _detail(*_run_with_budget(action, remaining), budget)
    try:
        secrets = get_secrets()
    except Exception:  # noqa: BLE001 — a backstop must never raise
        return
    if lock is not None and not lock.acquire(timeout=max(left(), _REPORT_WAIT_FLOOR_SECONDS)):
        log.error("backstop: the write lock stayed busy; the run's own write stands")
        return
    try:
        report_abrupt_termination(
            run,
            signal_name=signal_name,
            secrets=secrets,
            detail=detail,
            error_code=error_code,
            headline=headline,
        )
    finally:
        if lock is not None:
            lock.release()


# ---------------------------------------------------------------------------
# The live run: a process-wide registry the handler resolves
# ---------------------------------------------------------------------------


@dataclass(eq=False)
class RunTarget:
    """One run, as the process-wide handler sees it.

    ``installed`` says whether the backstop handler was the process's SIGTERM
    handler when the run registered; ``reason`` says why not.
    """

    get_run: Callable[[], Any]
    get_secrets: Callable[[], list[str]]
    get_disposition: DispositionGetter | None = None
    budget: float = DISPOSITION_BUDGET_SECONDS
    installed: bool = False
    reason: str = ""
    _fired: bool = field(default=False, repr=False)
    _fire_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def claim_fire(self) -> bool:
        """True the first time only: one backstop per run, however many handlers run."""
        with self._fire_lock:
            if self._fired:
                return False
            self._fired = True
            return True


_registry_lock = threading.Lock()
_active: RunTarget | None = None


def set_active_run(target: RunTarget) -> None:
    """Make ``target`` the run the SIGTERM handler ends."""
    global _active
    with _registry_lock:
        _active = target


def clear_active_run(target: RunTarget | None) -> None:
    """Forget ``target``, only if it is still the active run."""
    global _active
    with _registry_lock:
        if target is not None and _active is target:
            _active = None


def active_run() -> RunTarget | None:
    with _registry_lock:
        return _active


# ---------------------------------------------------------------------------
# The one process-wide handler, installed on the main thread
# ---------------------------------------------------------------------------


def is_backstop_handler(handler: object) -> bool:
    return getattr(handler, _MARK, False) is True


def _describe(handler: object) -> str:
    if handler is signal.SIG_DFL:
        return "SIG_DFL"
    if handler is signal.SIG_IGN:
        return "SIG_IGN"
    if handler is None:
        return "a handler not installed from Python"
    return getattr(handler, "__qualname__", type(handler).__name__)


def _on_signal(signum: int) -> None:
    """The backstop for the active run, once per run. Never raises."""
    try:
        target = active_run()
        if target is None:
            log.warning("%s with no active run", signal.Signals(signum).name)
            return
        if not target.claim_fire():
            return
        handle_termination(
            target.get_run,
            target.get_secrets,
            target.get_disposition,
            signal.Signals(signum).name,
            target.budget,
        )
    except Exception:  # noqa: BLE001 — a backstop must never raise
        log.exception("backstop failed")


def _chain(previous: Any, signum: int, frame: Any) -> None:
    """Hand the signal on to the handler the backstop replaced."""
    if callable(previous):
        previous(signum, frame)  # e.g. uvicorn's handle_exit: a graceful shutdown
        return
    if previous is signal.SIG_IGN:
        return
    # SIG_DFL, or a handler not installed from Python: end the process.
    signal.signal(signum, signal.SIG_DFL)
    signal.raise_signal(signum)
    if os.getpid() == 1:
        # PID 1 (the image's exec-form CMD): the kernel ignores a signal whose
        # action is the default for a namespace's init process, so the
        # re-raise above did nothing. The run's terminal row is already
        # written; exit as a SIGTERM death would.
        os._exit(128 + signum)


def _make_handler(previous: Any) -> Callable[[int, Any], None]:
    def _handler(signum: int, frame: Any) -> None:
        try:
            _on_signal(signum)
        finally:
            _chain(previous, signum, frame)

    setattr(_handler, _MARK, True)
    _handler.previous = previous  # type: ignore[attr-defined]
    return _handler


def install_process_backstop(where: str = "") -> tuple[bool, str]:
    """Put the backstop handler on top of SIGTERM. Returns ``(installed, reason)``.

    Idempotent: a no-op when the backstop is already the current handler.
    Off the main thread nothing can be installed, so it only reports whether
    the backstop is the current handler. A failure is logged at ERROR, never
    swallowed.
    """
    try:
        current = signal.getsignal(signal.SIGTERM)
    except Exception as exc:  # noqa: BLE001 — reported, never raised
        reason = f"SIGTERM handler could not be read ({type(exc).__name__})"
        log.error("SIGTERM backstop not installed%s: %s", f" at {where}" if where else "", reason)
        return False, reason
    if is_backstop_handler(current):
        return True, ""
    thread = threading.current_thread()
    if thread is not threading.main_thread():
        reason = (
            f"the SIGTERM handler is {_describe(current)}, and the {thread.name!r} thread "
            "cannot install one (only the main thread can)"
        )
        log.error("SIGTERM backstop not installed%s: %s", f" at {where}" if where else "", reason)
        return False, reason
    try:
        signal.signal(signal.SIGTERM, _make_handler(current))
    except (ValueError, OSError, TypeError) as exc:
        reason = f"signal.signal failed ({type(exc).__name__})"
        log.error("SIGTERM backstop not installed%s: %s", f" at {where}" if where else "", reason)
        return False, reason
    log.info(
        "SIGTERM backstop installed%s, chaining to %s",
        f" at {where}" if where else "",
        _describe(current),
    )
    return True, ""


def install_termination_backstop(
    get_run: Callable[[], Any],
    get_secrets: Callable[[], list[str]],
    get_disposition: DispositionGetter | None = None,
    *,
    budget: float = DISPOSITION_BUDGET_SECONDS,
) -> RunTarget:
    """Register the run with the process-wide SIGTERM backstop; return its target.

    ``get_run`` / ``get_secrets`` / ``get_disposition`` are zero-arg callables
    resolved lazily inside the handler so the latest state is used. The run
    becomes the active run; the caller clears it (:func:`clear_active_run`)
    when the run can no longer be written to. On the main thread this also
    installs the handler; elsewhere it only checks it, and the target's
    ``installed``/``reason`` say what it found. SIGKILL is intentionally not
    handled (it cannot be); that path relies on the reaper.
    """
    target = RunTarget(get_run, get_secrets, get_disposition, budget=budget)
    set_active_run(target)
    target.installed, target.reason = install_process_backstop("run start")
    return target
