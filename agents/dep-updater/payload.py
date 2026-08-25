"""Control-plane payload envelope parser (S-009).

Parses the structured payload the orchestrator Lambda sends to the agent
via InvokeAgentRuntime. Handles:
- Envelope validation (session_id, repo required)
- Subject ID normalization via generated contract
- Params validation against generated schema (unknown keys rejected)
- Defaults application
- CLI prompt-unwrap shim for backward compatibility
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Add the generated contract to the path
_GENERATED_DIR = str(
    Path(__file__).resolve().parent.parent.parent / "packages" / "shared" / "generated"
)
if _GENERATED_DIR not in sys.path:
    sys.path.insert(0, _GENERATED_DIR)

from shared_contract import (  # noqa: E402
    DEP_UPDATER_PARAMS_SCHEMA,
    normalize_subject_id,
)


class PayloadError(Exception):
    """Raised when the payload envelope is invalid or incomplete."""


# ─── Defaults ─────────────────────────────────────────────────────────────────

_PARAM_DEFAULTS: dict[str, Any] = {
    "allow_fixes": True,
    "max_fix_attempts": 3,
}


# ─── Result type ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedPayload:
    """Validated and normalized invocation payload."""

    session_id: str
    repo: str
    clone_url: str
    params: dict[str, Any]


# ─── Params validation ────────────────────────────────────────────────────────


def _validate_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate params against the dep-updater schema.

    Rejects unknown keys (raises, does not strip).
    Validates types and ranges for known keys.
    Applies defaults for missing keys.
    """
    schema = DEP_UPDATER_PARAMS_SCHEMA

    # Check for unknown keys — reject, don't strip
    unknown_keys = set(params.keys()) - set(schema.keys())
    if unknown_keys:
        raise PayloadError(
            f"Unknown params key(s): {', '.join(sorted(unknown_keys))}. "
            f"Allowed keys: {', '.join(sorted(schema.keys()))}"
        )

    # Validate types and ranges for provided keys
    for key, value in params.items():
        constraints = schema[key]
        expected_type = constraints["type"]

        if expected_type == "boolean":
            if not isinstance(value, bool):
                raise PayloadError(
                    f"Invalid type for params.{key}: expected boolean, got {type(value).__name__}"
                )
        elif expected_type == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise PayloadError(
                    f"Invalid type for params.{key}: expected integer, got {type(value).__name__}"
                )
            minimum = constraints.get("minimum")
            maximum = constraints.get("maximum")
            if minimum is not None and value < minimum:
                raise PayloadError(
                    f"Invalid value for params.{key}: {value} is below minimum {minimum}"
                )
            if maximum is not None and value > maximum:
                raise PayloadError(
                    f"Invalid value for params.{key}: {value} is above maximum {maximum}"
                )

    # Merge with defaults (defaults fill in missing keys)
    result = {**_PARAM_DEFAULTS, **params}
    return result


# ─── Main parser ──────────────────────────────────────────────────────────────


def parse_payload(raw: dict[str, Any]) -> ParsedPayload:
    """Parse and validate the control-plane invocation payload.

    Supports:
    - Direct envelope: {session_id, repo, params}
    - CLI prompt shim: {prompt: "<json string>"}
    - Legacy repo_url alias for repo

    Raises PayloadError on missing required fields or invalid params.
    """
    # Prompt unwrap: CLI sends JSON inside a "prompt" key
    if "repo" not in raw and "repo_url" not in raw and "prompt" in raw:
        try:
            raw = json.loads(raw["prompt"])
        except (json.JSONDecodeError, TypeError) as e:
            raise PayloadError(f"Failed to parse prompt JSON: {e}") from e

    # Extract session_id (required)
    session_id = raw.get("session_id")
    if not session_id:
        raise PayloadError("Missing required field: session_id")

    # Extract repo (required; repo_url is a legacy alias)
    repo_raw = raw.get("repo") or raw.get("repo_url")
    if not repo_raw:
        raise PayloadError("Missing required field: repo (or repo_url)")

    # Normalize subject ID
    repo = normalize_subject_id(str(repo_raw))

    # Derive clone URL from normalized repo
    clone_url = f"https://github.com/{repo}"

    # Validate and apply defaults to params
    raw_params = raw.get("params")
    if raw_params is None or (isinstance(raw_params, dict) and len(raw_params) == 0):
        # null, missing, or empty → use all defaults
        params = dict(_PARAM_DEFAULTS)
    else:
        if not isinstance(raw_params, dict):
            raise PayloadError(f"params must be an object, got {type(raw_params).__name__}")
        params = _validate_params(raw_params)

    return ParsedPayload(
        session_id=str(session_id),
        repo=repo,
        clone_url=clone_url,
        params=params,
    )
