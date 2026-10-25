"""
Outcome mapping: every terminal path of a run as one :class:`RunResult`
(spec §8.9 v2.5; S-190; FR-26; D-20, D-61, D-67).

A run ends in exactly one of these shapes:

=========================================  ===========================  =================
Path                                        status / outcome             error_code
=========================================  ===========================  =================
Draft PR opened (Wave B)                    succeeded / fixed            —
Refusal (a)–(e), ``invalid_params``         succeeded / not_applicable   —
Lost race (own comment deleted or gone)     succeeded / not_applicable   —
Fix loop not yet enabled (Wave A)           succeeded / needs_review     —
A fault (§8.9 rows; D-67)                   failed                       the fault's code
=========================================  ===========================  =================

Rules:

- **Breaker** (D-20): only ``failed`` counts toward the webhook rule's
  breaker and G3. :attr:`RunResult.counts_toward_breaker` is ``status ==
  "failed"``; every ``succeeded`` result is breaker-free.
- **Summary** (FR-26): every result has a non-empty ``summary``. A
  ``not_applicable`` or ``needs_review`` result also has a non-empty
  ``reason``, and :meth:`RunResult.result` puts both in ``runs.result``, so the
  panel shows why a green run did nothing. An empty one raises
  :class:`OutcomeError`.
- **Closed sets.** ``outcome`` is one of :data:`PRODUCIBLE_OUTCOMES` (never
  ``no_findings``: there is no selection, FR-4 removed). A refusal ``reason``
  is one of :data:`REFUSAL_REASONS`. ``error_code`` is one of
  :data:`ERROR_CODES`. ``failed`` has no outcome, and ``succeeded`` has no
  ``error_code``.
- **Typed faults** map by their own code (:func:`from_exception`): a
  ``CredentialError`` by ``exc.error_code`` (``PermissionMissing`` →
  ``GITHUB_PERMISSION_MISSING``, a mint failure → ``CREDENTIALS_UNAVAILABLE``),
  a ``GitHubError`` or ``SupabaseUnavailable`` by ``exc.code``, anything else
  ``UNHANDLED_ERROR``. Every summary built from an exception is scrubbed.

The builders :func:`from_check`, :func:`from_checkout` and :func:`from_claim`
read the step results of ``refusal.py``, ``checkout.py`` and ``claim.py``, and
return ``None`` when the step lets the run continue.

This module does no I/O. :meth:`RunResult.report` is the one call into the
run reporter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from credentials import CredentialError
from github_client import GitHubError
from refusal import SupabaseUnavailable
from scrubber import SecretsLike, scrub_all, scrub_exception

SUCCEEDED = "succeeded"
FAILED = "failed"

# The outcomes this agent can produce on ``succeeded`` (TC-190-12).
PRODUCIBLE_OUTCOMES: frozenset[str] = frozenset({"fixed", "not_applicable", "needs_review"})
BREAKER_FREE_STATUSES: frozenset[str] = frozenset({SUCCEEDED})

# Refusal codes (spec §8.2, D-92, D-104), in the order the checks run.
REFUSAL_REASONS: tuple[str, ...] = (
    "pull_request",
    "closed",
    "linked_pr",
    "active_run",
    "repo_gate",
    "invalid_params",
)
LOST_RACE_REASON = "active_run"
FIX_LOOP_DISABLED_REASON = "fix_loop_disabled"
FIX_LOOP_DISABLED = "fix loop not yet enabled"

# Every ``error_code`` a run can end with (spec §8.9, plus the entrypoint's
# own pre-run codes). ``RUNTIME_TIMEOUT`` is the reaper's, never the agent's.
ERROR_CODES: frozenset[str] = frozenset(
    {
        "GITHUB_PERMISSION_MISSING",
        "CREDENTIALS_UNAVAILABLE",
        "CLONE_FAILED",
        "INSTALL_FAILED",
        "CLI_CRASHED",
        "GITHUB_UNAVAILABLE",
        "GITHUB_REQUEST_REJECTED",
        "SUPABASE_UNAVAILABLE",
        "PR_CREATE_FAILED",
        "UNHANDLED_ERROR",
        # The entrypoint, before or around the steps.
        "CONFIG_INVALID",
        "INVALID_PAYLOAD",
        "PROBE_REFUSED",
        "SIGNAL_TERMINATION",
    }
)
UNHANDLED_ERROR = "UNHANDLED_ERROR"


class OutcomeError(ValueError):
    """A result that breaks the rules above (an empty summary, an open code)."""


def _blank(value: object) -> bool:
    return not isinstance(value, str) or not value.strip()


@dataclass(frozen=True)
class RunResult:
    """One run's terminal result. Validated on construction."""

    status: str
    outcome: str | None
    summary: str
    reason: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if _blank(self.summary):
            raise OutcomeError("a run result needs a non-empty summary")
        if self.status == SUCCEEDED:
            if self.outcome not in PRODUCIBLE_OUTCOMES:
                raise OutcomeError(f"outcome must be one of {sorted(PRODUCIBLE_OUTCOMES)}")
            if self.error_code is not None:
                raise OutcomeError("a succeeded result has no error_code")
            if self.outcome != "fixed" and _blank(self.reason):
                raise OutcomeError(f"a {self.outcome} result needs a reason")
        elif self.status == FAILED:
            if self.outcome is not None:
                raise OutcomeError("a failed result has no outcome")
            if self.error_code not in ERROR_CODES:
                raise OutcomeError("error_code is not in the closed set")
        else:
            raise OutcomeError("status must be succeeded or failed")

    @property
    def counts_toward_breaker(self) -> bool:
        """Only ``failed`` counts toward the breaker (D-20)."""
        return self.status not in BREAKER_FREE_STATUSES

    def result(self) -> dict[str, Any]:
        """``runs.result``: the summary, and the reason when there is one."""
        out: dict[str, Any] = {"summary": self.summary}
        if self.reason is not None:
            out["reason"] = self.reason
        return out

    def terminal(self) -> dict[str, Any]:
        """The terminal chunk's JSON object (the entrypoint's return value)."""
        out: dict[str, Any] = {"status": self.status}
        if self.outcome is not None:
            out["outcome"] = self.outcome
        if self.reason is not None:
            out["reason"] = self.reason
        if self.error_code is not None:
            out["error_code"] = self.error_code
        out["summary"] = self.summary
        return out

    def report(self, run: Any, metrics: dict[str, Any] | None = None) -> None:
        """End ``run`` with this result: ``succeed()`` or ``fail()``."""
        if self.status == SUCCEEDED:
            run.succeed(self.outcome, result=self.result(), metrics=metrics)
        else:
            assert self.error_code is not None  # checked in __post_init__
            run.fail(self.error_code, self.summary, metrics=metrics)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def refused(reason: str, summary: str) -> RunResult:
    """A refusal: ``succeeded``/``not_applicable``, reason = the code."""
    if reason not in REFUSAL_REASONS:
        raise OutcomeError("unknown refusal reason")
    return RunResult(SUCCEEDED, "not_applicable", summary, reason=reason)


def lost_race(summary: str) -> RunResult:
    """Another run claimed first: ``not_applicable``, reason ``active_run``."""
    return RunResult(SUCCEEDED, "not_applicable", summary, reason=LOST_RACE_REASON)


def needs_review(reason: str, summary: str) -> RunResult:
    """Claimed, no PR, disposition applied: ``succeeded``/``needs_review``."""
    return RunResult(SUCCEEDED, "needs_review", summary, reason=reason)


def fix_loop_disabled() -> RunResult:
    """Wave A: the claim held, and ``FIX_LOOP_ENABLED`` is not 1."""
    return needs_review(FIX_LOOP_DISABLED_REASON, FIX_LOOP_DISABLED)


def fixed(summary: str) -> RunResult:
    """A Draft PR was opened (Wave B)."""
    return RunResult(SUCCEEDED, "fixed", summary)


def failed(error_code: str, summary: str) -> RunResult:
    """A fault. Counts toward the breaker."""
    return RunResult(FAILED, None, summary, error_code=error_code)


def exception_code(exc: BaseException) -> str:
    """The ``error_code`` a typed fault carries; ``UNHANDLED_ERROR`` otherwise."""
    if isinstance(exc, CredentialError):
        code = exc.error_code
    elif isinstance(exc, GitHubError | SupabaseUnavailable):
        code = exc.code
    else:
        return UNHANDLED_ERROR
    return code if code in ERROR_CODES else UNHANDLED_ERROR


def from_exception(exc: BaseException, secrets: SecretsLike) -> RunResult:
    """A ``failed`` result for ``exc``, its message scrubbed."""
    code = exception_code(exc)
    # ``scrub_exception`` is already ``Type: message`` (``Type`` alone for an
    # empty message), so the type is named once (QA-190-03).
    detail = scrub_exception(exc, secrets) or type(exc).__name__
    return failed(code, scrub_all(f"{code}: {detail}", secrets))


def _from_step(status: str, summary: str, reason: str | None, code: str | None) -> RunResult:
    if status == FAILED:
        return failed(code if code in ERROR_CODES else UNHANDLED_ERROR, summary)
    return refused(reason or "", summary)


def from_check(out: Any) -> RunResult | None:
    """A ``refusal.CheckOutcome``: ``None`` to proceed, else its result."""
    if out.proceed:
        return None
    return _from_step(out.status, out.summary, out.reason, out.error_code)


def from_checkout(out: Any) -> RunResult | None:
    """A ``checkout.CheckoutResult``: ``None`` to proceed, else its result."""
    if out.proceed:
        return None
    if out.status == "refused" and out.refusal is not None:
        return from_check(out.refusal)
    return failed(out.error_code if out.error_code in ERROR_CODES else "CLONE_FAILED", out.summary)


def from_claim(out: Any) -> RunResult | None:
    """A ``claim.ClaimOutcome``: ``None`` once owned, else its result."""
    if out.owned:
        return None
    if out.status == "lost":
        return lost_race(out.summary)
    return failed(out.error_code if out.error_code in ERROR_CODES else UNHANDLED_ERROR, out.summary)


# ---------------------------------------------------------------------------
# The Wave A rows of spec §8.9 (TC-190-03)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    path: str
    status: str
    outcome: str | None
    error_code: str | None
    breaker: bool
    build: Callable[[], RunResult]


def _refusal_row(code: str) -> Row:
    return Row(
        f"refusal:{code}",
        SUCCEEDED,
        "not_applicable",
        None,
        False,
        lambda: refused(code, f"refused: {code}"),
    )


def _fault_row(code: str) -> Row:
    return Row(code, FAILED, None, code, True, lambda: failed(code, f"{code}: fault"))


WAVE_A_ROWS: tuple[Row, ...] = (
    *(_refusal_row(code) for code in REFUSAL_REASONS),
    Row(
        "lost_race",
        SUCCEEDED,
        "not_applicable",
        None,
        False,
        lambda: lost_race("another run claimed first; this run withdrew its claim"),
    ),
    Row("fix_loop_disabled", SUCCEEDED, "needs_review", None, False, fix_loop_disabled),
    *(
        _fault_row(code)
        for code in (
            "GITHUB_PERMISSION_MISSING",
            "CREDENTIALS_UNAVAILABLE",
            "CLONE_FAILED",
            "INSTALL_FAILED",
            "GITHUB_UNAVAILABLE",
            "GITHUB_REQUEST_REJECTED",
            "SUPABASE_UNAVAILABLE",
            UNHANDLED_ERROR,
        )
    ),
)
