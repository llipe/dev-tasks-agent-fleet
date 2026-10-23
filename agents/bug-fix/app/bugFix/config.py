"""
Configuration — typed runtime env and constants.

``load_config()`` reads the runtime env (set in ``agentcore/agentcore.json``)
into a frozen :class:`Config`. Only secret **IDs** live in the env; the values
are fetched from Secrets Manager by the wrapper and held in memory (spec §12).

A missing or invalid required variable raises :class:`ConfigError`, which
names the variable and never its value, and is raised ``from None`` so no
exception context carries the env mapping into a traceback (S-180 edge cases).

The model is served by the Anthropic API (D-50): ``MODEL_ID`` is a plain
Anthropic model id, and a cloud inference-profile id is rejected.

The Projects board is best effort (FR-34, D-99, DF-36): a missing
``PROJECTS_TOKEN_SECRET_ID`` disables the board with a reason; it never fails
the run.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

# --- Legacy module-level reads ---------------------------------------------
# ``credentials.py`` (copied from the sibling) imports these names, with the
# sibling's default secret ID. ``main.py`` passes the validated value from
# ``load_config()`` explicitly, so the default is only a fallback for callers
# that omit it.
SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY_SECRET_ID: str = os.environ.get(
    "SUPABASE_KEY_SECRET_ID", "agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY"
)

# --- Timeouts / clocks (seconds) -------------------------------------------
# MAX_LIFETIME and IDLE_SESSION_TIMEOUT MUST match agentcore.json
# `lifecycleConfiguration`; the seed's `max_runtime_seconds` (S-184) MUST
# equal MAX_LIFETIME (research Q7). A unit test pins both.
MAX_LIFETIME: int = 3600
IDLE_SESSION_TIMEOUT: int = 900
# Heartbeat cadence for long blocking steps; well below the idle bound.
HEARTBEAT_INTERVAL: int = 120

# --- Token refresh ---
TOKEN_STALE_THRESHOLD_MINUTES: float = 45.0

# Required variables, in the order they are checked.
REQUIRED_VARS: tuple[str, ...] = (
    "SUPABASE_URL",
    "SUPABASE_KEY_SECRET_ID",
    "ANTHROPIC_KEY_SECRET_ID",
    "MODEL_ID",
)

# Cloud inference-profile ids (regional prefix, or a provider-namespaced id).
_PROVIDER_MODEL_ID = re.compile(r"^((us|eu|apac|global)\.)?anthropic\.")


class ConfigError(ValueError):
    """A required runtime variable is missing or invalid.

    The message names the variable and the reason. It never contains a value.
    """

    def __init__(self, variable: str, reason: str) -> None:
        self.variable = variable
        self.reason = reason
        super().__init__(f"{variable} {reason}")

    def __repr__(self) -> str:
        return f"ConfigError(variable={self.variable!r}, reason={self.reason!r})"


@dataclass(frozen=True)
class Config:
    supabase_url: str
    supabase_key_secret_id: str
    anthropic_key_secret_id: str
    model_id: str
    projects_token_secret_id: str | None
    board_updates_enabled: bool
    # None when the board is enabled; otherwise "flag_off" or "no_token_secret_id".
    board_disabled_reason: str | None


def _get(env: Mapping[str, str], name: str) -> str | None:
    raw = env.get(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _require(env: Mapping[str, str], name: str) -> str:
    value = _get(env, name)
    if value is None:
        raise ConfigError(name, "is not set") from None
    return value


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """Read and validate the runtime env. Raises :class:`ConfigError`."""
    source: Mapping[str, str] = os.environ if env is None else env

    values = {name: _require(source, name) for name in REQUIRED_VARS}

    if _PROVIDER_MODEL_ID.match(values["MODEL_ID"]):
        raise ConfigError(
            "MODEL_ID",
            "is a cloud inference-profile id; use an Anthropic API model id (D-50)",
        ) from None

    flag = _get(source, "BOARD_UPDATES_ENABLED")
    if flag not in (None, "0", "1"):
        raise ConfigError("BOARD_UPDATES_ENABLED", "must be 1 or 0") from None

    projects_id = _get(source, "PROJECTS_TOKEN_SECRET_ID")
    reason: str | None = None
    if flag != "1":
        reason = "flag_off"
    elif projects_id is None:
        reason = "no_token_secret_id"

    return Config(
        supabase_url=values["SUPABASE_URL"],
        supabase_key_secret_id=values["SUPABASE_KEY_SECRET_ID"],
        anthropic_key_secret_id=values["ANTHROPIC_KEY_SECRET_ID"],
        model_id=values["MODEL_ID"],
        projects_token_secret_id=projects_id,
        board_updates_enabled=reason is None,
        board_disabled_reason=reason,
    )
