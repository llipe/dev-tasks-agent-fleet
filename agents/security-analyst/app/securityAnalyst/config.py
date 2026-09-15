"""
Configuration — environment variable reads and constants.
"""

from __future__ import annotations

import os

# --- Supabase ---
SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY_SECRET_ID: str = os.environ.get(
    "SUPABASE_KEY_SECRET_ID", "agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY"
)

# --- AWS / Model ---
MODEL_ID: str = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6")

# --- Timeouts / clocks (seconds) -------------------------------------------
#
# security-analyst inherits ADR-006's mechanism wholesale (the heartbeat
# generator and `assert_clock_invariant()` fail-fast, proven against
# dependency-update's #98 defect class) but recomputes the invariant chain for
# its own, higher bounds (spec S9.2, PRD S12.3): a five-scanner step (notably
# CodeQL's database-build phase) can legitimately run far longer than the
# sibling agent's `pnpm test`, so every constant here is this agent's own, not
# a copy of the sibling's numbers. The invariant is:
#
#     FIX_COMMAND_TIMEOUT <= SCANNER_TIMEOUT <= IDLE_SESSION_TIMEOUT
#                          <= MAX_LIFETIME <= REAPER_THRESHOLD_SECONDS
#
# and the heartbeat must fire well below the idle bound (<= idle / 2) so the
# response stream never goes idle for IDLE_SESSION_TIMEOUT. `assert_clock_invariant`
# (below) enforces this; a unit test calls it against the shipped constants so an
# inconsistent configuration cannot ship silently (PRD AC31 groundwork).
#
# The container-side values (IDLE_SESSION_TIMEOUT, MAX_LIFETIME) MUST match
# `agentcore/agentcore.json` `lifecycleConfiguration`, and REAPER_THRESHOLD_SECONDS
# MUST match the Supabase run snapshot (`max_runtime_seconds` + `grace_seconds`,
# set in S-141's `supabase/seed.sql` entry). See docs/technical-guidelines.md
# S7/S8 and ADR-006 for the single source of truth.

# Bounds each of the five scanner subprocess calls independently (spec S8.5) —
# no shared timeout budget across scanners, so one slow tool cannot silently
# consume the whole step's share of MAX_LIFETIME.
SCANNER_TIMEOUT: int = int(os.environ.get("SCANNER_TIMEOUT", "600"))

# Per-LLM-shell-call budget inside the fix agent (narrower blast radius than
# the sibling agent's per-run TOOL_COMMAND_TIMEOUT, since this agent's LLM
# invocation is scoped to a single finding rather than a whole update).
FIX_COMMAND_TIMEOUT: int = int(os.environ.get("FIX_COMMAND_TIMEOUT", "180"))

# Container lifecycle bounds — kept in sync with agentcore/agentcore.json.
IDLE_SESSION_TIMEOUT: int = int(os.environ.get("IDLE_SESSION_TIMEOUT", "900"))
MAX_LIFETIME: int = int(os.environ.get("MAX_LIFETIME", "5400"))

# Supabase reaper threshold = max_runtime_seconds (MAX_LIFETIME) + grace_seconds
# (120), per supabase/seed.sql. The reaper is the outer backstop; the container
# must not outlive it.
REAPER_THRESHOLD_SECONDS: int = int(
    os.environ.get("REAPER_THRESHOLD_SECONDS", str(MAX_LIFETIME + 120))
)

# Heartbeat cadence for keeping the AgentCore response stream alive during long
# blocking steps (`scan`/`rescan`). Must be well below IDLE_SESSION_TIMEOUT
# (<= idle / 2).
HEARTBEAT_INTERVAL: int = int(os.environ.get("HEARTBEAT_INTERVAL", "120"))


class ClockConsistencyError(ValueError):
    """Raised when the timeout clocks violate the spec S9.2 ordering invariant."""


def assert_clock_invariant(
    *,
    fix_command_timeout: int | None = None,
    scanner_timeout: int | None = None,
    idle_session_timeout: int | None = None,
    max_lifetime: int | None = None,
    reaper_threshold_seconds: int | None = None,
    heartbeat_interval: int | None = None,
) -> None:
    """Validate the timeout-clock ordering invariant (spec S9.2, PRD AC31).

    Called with no arguments it checks the shipped module constants; each
    argument overrides one clock for testing. Raises
    :class:`ClockConsistencyError` with a specific message on the first
    violated relation. Pure and side-effect-free.

    Invariant::

        FIX_COMMAND_TIMEOUT <= SCANNER_TIMEOUT <= IDLE_SESSION_TIMEOUT
                             <= MAX_LIFETIME <= REAPER_THRESHOLD_SECONDS
        0 < HEARTBEAT_INTERVAL <= IDLE_SESSION_TIMEOUT / 2
    """
    fix = FIX_COMMAND_TIMEOUT if fix_command_timeout is None else fix_command_timeout
    scan = SCANNER_TIMEOUT if scanner_timeout is None else scanner_timeout
    idle = IDLE_SESSION_TIMEOUT if idle_session_timeout is None else idle_session_timeout
    life = MAX_LIFETIME if max_lifetime is None else max_lifetime
    reaper = (
        REAPER_THRESHOLD_SECONDS if reaper_threshold_seconds is None else reaper_threshold_seconds
    )
    hb = HEARTBEAT_INTERVAL if heartbeat_interval is None else heartbeat_interval

    if fix > scan:
        raise ClockConsistencyError(
            f"FIX_COMMAND_TIMEOUT ({fix}) must be <= SCANNER_TIMEOUT ({scan})"
        )
    if scan > idle:
        raise ClockConsistencyError(
            f"SCANNER_TIMEOUT ({scan}) must be <= IDLE_SESSION_TIMEOUT ({idle})"
        )
    if idle > life:
        raise ClockConsistencyError(
            f"IDLE_SESSION_TIMEOUT ({idle}) must be <= MAX_LIFETIME ({life})"
        )
    if life > reaper:
        raise ClockConsistencyError(
            f"MAX_LIFETIME ({life}) must be <= REAPER_THRESHOLD_SECONDS ({reaper})"
        )
    if hb <= 0:
        raise ClockConsistencyError(f"HEARTBEAT_INTERVAL ({hb}) must be > 0")
    if hb > idle / 2:
        raise ClockConsistencyError(
            f"HEARTBEAT_INTERVAL ({hb}) must be <= IDLE_SESSION_TIMEOUT/2 ({idle / 2})"
        )


# --- Agent behaviour (spec S6.1) ---
DEFAULT_MODE: str = "audit_only"
DEFAULT_FAIL_ON_FINDINGS: bool = True
DEFAULT_MIN_SEVERITY: str = "low"
DEFAULT_MAX_FIX_ATTEMPTS: int = 3
MAX_FIX_ATTEMPTS_CEILING: int = 5

# --- Token refresh ---
TOKEN_STALE_THRESHOLD_MINUTES: float = 45.0
