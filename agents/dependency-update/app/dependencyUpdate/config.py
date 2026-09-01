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
# Issue #98: four timeout "clocks" must stay mutually consistent so a long
# inner operation (notably `pnpm test` inside the `validate` step) cannot
# outlive an outer bound and get the AgentCore container reclaimed mid-step
# before the agent writes a terminal status. The invariant is:
#
#     TOOL_COMMAND_TIMEOUT <= TEST_TIMEOUT <= IDLE_SESSION_TIMEOUT
#                          <= MAX_LIFETIME <= REAPER_THRESHOLD_SECONDS
#
# and the heartbeat must fire well below the idle bound (<= idle / 2) so the
# response stream never goes idle for IDLE_SESSION_TIMEOUT. `assert_clock_invariant`
# (below) enforces this; a unit test calls it against the shipped constants so an
# inconsistent configuration cannot ship silently.
#
# The container-side values (IDLE_SESSION_TIMEOUT, MAX_LIFETIME) MUST match
# `agentcore/agentcore.json` `lifecycleConfiguration`, and REAPER_THRESHOLD_SECONDS
# MUST match the Supabase run snapshot (`max_runtime_seconds` + `grace_seconds`).
# See docs/technical-guidelines.md §7/§8 for the single source of truth.

TOOL_COMMAND_TIMEOUT: int = int(os.environ.get("TOOL_COMMAND_TIMEOUT", "180"))
TEST_TIMEOUT: int = int(os.environ.get("TEST_TIMEOUT", "600"))

# Container lifecycle bounds — kept in sync with agentcore/agentcore.json.
# idle raised from 300 -> 900 so a bounded TEST_TIMEOUT (600) run streaming a
# heartbeat every 120 s can never trip the idle reclamation (#98 AC4).
IDLE_SESSION_TIMEOUT: int = int(os.environ.get("IDLE_SESSION_TIMEOUT", "900"))
MAX_LIFETIME: int = int(os.environ.get("MAX_LIFETIME", "3600"))

# Supabase reaper threshold = max_runtime_seconds (3600) + grace_seconds (120).
# The reaper is the outer backstop; the container must not outlive it.
REAPER_THRESHOLD_SECONDS: int = int(os.environ.get("REAPER_THRESHOLD_SECONDS", "3720"))

# Heartbeat cadence for keeping the AgentCore response stream alive during long
# blocking steps (#98). Must be well below IDLE_SESSION_TIMEOUT (<= idle / 2).
HEARTBEAT_INTERVAL: int = int(os.environ.get("HEARTBEAT_INTERVAL", "120"))


class ClockConsistencyError(ValueError):
    """Raised when the timeout clocks violate the #98 ordering invariant."""


def assert_clock_invariant(
    *,
    tool_command_timeout: int | None = None,
    test_timeout: int | None = None,
    idle_session_timeout: int | None = None,
    max_lifetime: int | None = None,
    reaper_threshold_seconds: int | None = None,
    heartbeat_interval: int | None = None,
) -> None:
    """Validate the timeout-clock ordering invariant (issue #98, AC4).

    Called with no arguments it checks the shipped module constants; each
    argument overrides one clock for testing. Raises
    :class:`ClockConsistencyError` with a specific message on the first
    violated relation. Pure and side-effect-free.

    Invariant::

        TOOL_COMMAND_TIMEOUT <= TEST_TIMEOUT <= IDLE_SESSION_TIMEOUT
                             <= MAX_LIFETIME <= REAPER_THRESHOLD_SECONDS
        0 < HEARTBEAT_INTERVAL <= IDLE_SESSION_TIMEOUT / 2
    """
    tool = TOOL_COMMAND_TIMEOUT if tool_command_timeout is None else tool_command_timeout
    test = TEST_TIMEOUT if test_timeout is None else test_timeout
    idle = IDLE_SESSION_TIMEOUT if idle_session_timeout is None else idle_session_timeout
    life = MAX_LIFETIME if max_lifetime is None else max_lifetime
    reaper = (
        REAPER_THRESHOLD_SECONDS if reaper_threshold_seconds is None else reaper_threshold_seconds
    )
    hb = HEARTBEAT_INTERVAL if heartbeat_interval is None else heartbeat_interval

    if tool > test:
        raise ClockConsistencyError(
            f"TOOL_COMMAND_TIMEOUT ({tool}) must be <= TEST_TIMEOUT ({test})"
        )
    if test > idle:
        raise ClockConsistencyError(
            f"TEST_TIMEOUT ({test}) must be <= IDLE_SESSION_TIMEOUT ({idle})"
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


# --- Agent behaviour ---
DEFAULT_FIX_MODE: str = "audit_only"
DEFAULT_MAX_FIX_ATTEMPTS: int = 3
MAX_FIX_ATTEMPTS_CEILING: int = 5
DEFAULT_FAIL_ON_FINDINGS: bool = True

# --- Token refresh ---
TOKEN_STALE_THRESHOLD_MINUTES: float = 45.0
