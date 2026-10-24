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

``PANEL_BASE_URL`` is the panel's ``https`` origin. :meth:`Config.run_link`
builds ``<origin>/runs/<run_id>``, the run link in the claim comment and every
other agent comment (S-188). It is optional: without it a comment names the
run id instead, so a missing link never fails the run. A value that isn't a
bare ``https`` origin is a :class:`ConfigError`.
"""

from __future__ import annotations

import os
import re
import uuid
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

# Cloud/provider model ids, matched case-insensitively (D-50): an ARN, a
# provider-slash id (``anthropic/claude-...``), or a provider-namespaced id with
# or without a region prefix (``anthropic.claude-...``, ``US.anthropic....``,
# ``global.anthropic....``). A plain Anthropic API id (``claude-...``) has none.
_PROVIDER_MODEL_ID = re.compile(r"^arn:|/|(?:^|\.)anthropic\.", re.IGNORECASE)

# A bare https origin: a DNS host and an optional port. No user info, path,
# query or fragment, so the run link can't point anywhere but the panel.
_PANEL_ORIGIN = re.compile(
    r"https://[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*"
    r"(?::[0-9]{1,5})?"
)


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
    # The panel's https origin (no trailing slash), or None when unset.
    panel_base_url: str | None = None

    def run_link(self, run_id: str) -> str | None:
        """``<panel>/runs/<run_id>``, or ``None`` without a panel origin or a UUID."""
        if self.panel_base_url is None:
            return None
        try:
            rid = str(uuid.UUID(run_id))
        except (TypeError, ValueError, AttributeError):
            return None
        return f"{self.panel_base_url}/runs/{rid}"


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

    if _PROVIDER_MODEL_ID.search(values["MODEL_ID"]):
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

    panel = _get(source, "PANEL_BASE_URL")
    if panel is not None:
        panel = panel.removesuffix("/")
        if not _PANEL_ORIGIN.fullmatch(panel):
            raise ConfigError("PANEL_BASE_URL", "must be an https origin with no path") from None

    return Config(
        supabase_url=values["SUPABASE_URL"],
        supabase_key_secret_id=values["SUPABASE_KEY_SECRET_ID"],
        anthropic_key_secret_id=values["ANTHROPIC_KEY_SECRET_ID"],
        model_id=values["MODEL_ID"],
        projects_token_secret_id=projects_id,
        board_updates_enabled=reason is None,
        board_disabled_reason=reason,
        panel_base_url=panel,
    )
