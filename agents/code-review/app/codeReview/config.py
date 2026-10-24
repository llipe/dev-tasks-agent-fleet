"""
Configuration — environment settings, the params contract, and the clock invariant.

Three things live here:

- **Settings** (spec §9, D-29): the environment variables the runtime reads.
  ``load_settings()`` validates them and raises :class:`ConfigError` naming the
  missing or malformed variable, never echoing any value.
- **The params contract** (spec §5.1): ``PARAMS_SCHEMA`` is the same JSON Schema
  the ``agents`` seed row carries, and ``DEFAULT_PARAMS`` its defaults. The panel
  validates against the seeded copy; the runtime re-validates against this one
  (defense in depth). ``tests/unit/test_seed_contract.py`` pins the two equal.
- **The clock invariant** (spec §8.9, D-32, ADR-006): see
  :func:`assert_clock_invariant`.

The module-level ``SUPABASE_URL`` / ``SUPABASE_KEY_SECRET_ID`` /
``TOKEN_STALE_THRESHOLD_MINUTES`` constants exist because ``credentials.py`` is
copied verbatim from the security-analyst sibling (D-20) and imports them.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# --- Module constants read by the copied credentials.py -------------------
SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY_SECRET_ID: str = os.environ.get(
    "SUPABASE_KEY_SECRET_ID", "agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY"
)
TOKEN_STALE_THRESHOLD_MINUTES: float = 45.0

# ---------------------------------------------------------------------------
# Params contract (spec §5.1). Keep byte-for-byte equal in meaning to the
# `params_schema` / `default_params` in supabase/seed.sql and the
# *_seed_code_review_agent.sql migration.
# ---------------------------------------------------------------------------

PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["pr_number"],
    "properties": {
        "pr_number": {"type": "integer", "minimum": 1, "title": "Pull request number"},
        "max_diff_lines": {"type": "integer", "minimum": 100, "maximum": 10000, "default": 2000},
        "max_context_tokens": {
            "type": "integer",
            "minimum": 20000,
            "maximum": 400000,
            "default": 150000,
        },
        "max_suggestions": {"type": "integer", "minimum": 0, "maximum": 20, "default": 5},
        "run_timeout_seconds": {"type": "integer", "minimum": 120, "maximum": 900, "default": 900},
        "reasoning_effort": {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "default": "high",
        },
    },
}

DEFAULT_PARAMS: dict[str, Any] = {
    key: prop["default"] for key, prop in PARAMS_SCHEMA["properties"].items() if "default" in prop
}

# ---------------------------------------------------------------------------
# Clocks (seconds) — spec §8.9, D-32, ADR-006
# ---------------------------------------------------------------------------
#
#     run_timeout_seconds <= IDLE_SESSION_TIMEOUT <= MAX_LIFETIME
#                         <= REAPER_THRESHOLD_SECONDS
#     0 < HEARTBEAT_INTERVAL <= IDLE_SESSION_TIMEOUT / 2
#     DEADLINE_RESERVE_SECONDS < run_timeout_seconds
#
# IDLE_SESSION_TIMEOUT and MAX_LIFETIME MUST match `lifecycleConfiguration` in
# agents/code-review/agentcore/agentcore.json (lands with S-214).
# MAX_LIFETIME MUST equal `agents.max_runtime_seconds` and GRACE_SECONDS
# `agents.grace_seconds` in the seed row, so REAPER_THRESHOLD_SECONDS is the
# pg_cron reaper's actual threshold.

# Upper bound of the `run_timeout_seconds` param; the schema is the source.
RUN_TIMEOUT_MAX_SECONDS: int = int(PARAMS_SCHEMA["properties"]["run_timeout_seconds"]["maximum"])

IDLE_SESSION_TIMEOUT: int = int(os.environ.get("IDLE_SESSION_TIMEOUT", "900"))
MAX_LIFETIME: int = int(os.environ.get("MAX_LIFETIME", "1800"))
GRACE_SECONDS: int = 120
REAPER_THRESHOLD_SECONDS: int = int(
    os.environ.get("REAPER_THRESHOLD_SECONDS", str(MAX_LIFETIME + GRACE_SECONDS))
)

# Keep-alive cadence around the GitHub fetch and the Converse calls.
HEARTBEAT_INTERVAL: int = int(os.environ.get("HEARTBEAT_INTERVAL", "120"))

# The run-level deadline is `start + run_timeout_seconds - DEADLINE_RESERVE_SECONDS`;
# the reserve pays for the failure comment and the reporter flush.
DEADLINE_RESERVE_SECONDS: int = 60


class ClockConsistencyError(ValueError):
    """Raised when the timeout clocks violate the spec §8.9 ordering invariant."""


def assert_clock_invariant(
    *,
    run_timeout_seconds: int | None = None,
    idle_session_timeout: int | None = None,
    max_lifetime: int | None = None,
    reaper_threshold_seconds: int | None = None,
    heartbeat_interval: int | None = None,
) -> None:
    """Validate the timeout-clock ordering invariant (spec §8.9, D-32).

    Called with no arguments it checks the shipped constants, with
    ``run_timeout_seconds`` at its schema maximum (the worst case any run can
    request). Each argument overrides one clock for testing. Raises
    :class:`ClockConsistencyError` naming the first violated relation. Pure.
    """
    run = RUN_TIMEOUT_MAX_SECONDS if run_timeout_seconds is None else run_timeout_seconds
    idle = IDLE_SESSION_TIMEOUT if idle_session_timeout is None else idle_session_timeout
    life = MAX_LIFETIME if max_lifetime is None else max_lifetime
    reaper = (
        REAPER_THRESHOLD_SECONDS if reaper_threshold_seconds is None else reaper_threshold_seconds
    )
    hb = HEARTBEAT_INTERVAL if heartbeat_interval is None else heartbeat_interval

    if run <= DEADLINE_RESERVE_SECONDS:
        raise ClockConsistencyError(
            f"run_timeout_seconds ({run}) must be > DEADLINE_RESERVE_SECONDS "
            f"({DEADLINE_RESERVE_SECONDS})"
        )
    if run > idle:
        raise ClockConsistencyError(
            f"run_timeout_seconds ({run}) must be <= IDLE_SESSION_TIMEOUT ({idle})"
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


# ---------------------------------------------------------------------------
# Environment settings (spec §9)
# ---------------------------------------------------------------------------

_REQUIRED_VARS = ("SUPABASE_URL", "SUPABASE_KEY_SECRET_ID", "MODEL_ID", "PANEL_BASE_URL")


class ConfigError(ValueError):
    """A required environment variable is missing or a variable is malformed.

    The message names the variable and never includes any variable's value.
    """

    def __init__(self, var: str, problem: str) -> None:
        self.var = var
        super().__init__(f"{var} {problem}")


@dataclass(frozen=True)
class Settings:
    """Validated runtime settings."""

    supabase_url: str
    supabase_key_secret_id: str
    model_id: str
    panel_base_url: str
    price_input_per_mtok: float | None = None
    price_output_per_mtok: float | None = None

    def run_url(self, run_id: str) -> str:
        """The panel link for a run (D-29)."""
        return f"{self.panel_base_url}/runs/{run_id}"


def _price(env: Mapping[str, str], var: str) -> float | None:
    raw = env.get(var, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(var, "must be a number") from None
    if not math.isfinite(value) or value < 0:
        raise ConfigError(var, "must be a finite, non-negative number")
    return value


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Read and validate the runtime settings from ``environ`` (default: ``os.environ``)."""
    env = os.environ if environ is None else environ
    values: dict[str, str] = {}
    for var in _REQUIRED_VARS:
        value = env.get(var, "").strip()
        if not value:
            raise ConfigError(var, "is required but not set")
        values[var] = value
    return Settings(
        supabase_url=values["SUPABASE_URL"],
        supabase_key_secret_id=values["SUPABASE_KEY_SECRET_ID"],
        model_id=values["MODEL_ID"],
        panel_base_url=values["PANEL_BASE_URL"].rstrip("/"),
        price_input_per_mtok=_price(env, "PRICE_INPUT_PER_MTOK"),
        price_output_per_mtok=_price(env, "PRICE_OUTPUT_PER_MTOK"),
    )
