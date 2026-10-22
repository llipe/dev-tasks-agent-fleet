"""
code-review agent — AgentCore entrypoint.

Reviews one pull request with one Bedrock Converse call over an expanded diff
and posts one PR comment (PRD FR-1, D-07). This module owns the invocation
contract (spec §6.1, D-21): unwrap the AgentCore ``prompt`` wrapper, validate
the payload and ``params`` against spec §5.1 (defense in depth: the panel has
already validated them), apply defaults, and run the pipeline under the
vendored ``RunReporter``.

S-204 ships a **skeleton** pipeline: a valid invocation starts the run, opens
the ``load_pr`` step, and ends ``failed``/``INTERNAL_ERROR`` "not implemented".
S-213 replaces :func:`load_pr` and :func:`run_review` with the real pipeline
(``load_pr`` -> ``context`` -> ``review`` -> ``validate`` -> ``post``, spec §8.1).

Error codes used here (spec §13): ``INVALID_PARAMS`` for a payload or params
violation (no GitHub call is ever made), ``INTERNAL_ERROR`` for anything else.
"""

from __future__ import annotations

import json
import re
import traceback
from dataclasses import dataclass
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from agent_reporter import RunReporter
from config import (
    DEFAULT_PARAMS,
    PARAMS_SCHEMA,
    ClockConsistencyError,
    ConfigError,
    Settings,
    assert_clock_invariant,
    load_settings,
)
from credentials import CredentialError, fetch_supabase_key, resolve_github_credentials
from heartbeat import terminal_chunk
from scrubber import scrub
from signal_backstop import install_termination_backstop

app = BedrockAgentCoreApp()
log = app.logger

__all__ = [
    "CredentialError",
    "InvalidParams",
    "ReviewRequest",
    "apply_defaults",
    "build_return_payload",
    "classify_invalid_payload",
    "invoke",
    "resolve_github_credentials",
    "unwrap_payload",
    "validate_params",
    "validate_payload",
]

# ---------------------------------------------------------------------------
# Payload unwrapping (spec §6.1, D-21 — mirrors the security-analyst sibling)
# ---------------------------------------------------------------------------

# Max nested ``prompt`` layers to strip. One layer is the control-plane form; two
# is the agentcore CLI >= 0.28.0 double wrap. The bound guards a pathological
# lone-``prompt`` chain; real payloads never approach it.
_MAX_UNWRAP_DEPTH = 16


def unwrap_payload(raw: Any) -> Any:
    """Strip the AgentCore ``prompt`` wrapper (single or CLI double wrap).

    Repeatedly unwraps while the value is a dict whose *only* key is ``prompt``
    and whose string value parses to a JSON object. Anything else is returned
    unchanged, so validation sees exactly what arrived.
    """
    current = raw
    for _ in range(_MAX_UNWRAP_DEPTH):
        if not _is_lone_prompt_wrapper(current):
            return current
        try:
            inner = json.loads(current["prompt"])
        except (json.JSONDecodeError, TypeError):
            return current
        if not isinstance(inner, dict):
            return current
        current = inner
    return current


def _is_lone_prompt_wrapper(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and list(payload.keys()) == ["prompt"]
        and isinstance(payload["prompt"], str)
    )


def classify_invalid_payload(payload: Any) -> str:
    """``"wrapper_only"`` for a still-wrapped payload, else ``"missing_fields"``."""
    if isinstance(payload, dict) and list(payload.keys()) == ["prompt"]:
        return "wrapper_only"
    return "missing_fields"


# ---------------------------------------------------------------------------
# Validation (spec §5.1 / §6.1)
# ---------------------------------------------------------------------------

_MAX_FIELD_CHARS = 100
_MAX_MESSAGE_CHARS = 300

_TOP_LEVEL_FIELDS = ("run_id", "repository_org", "repository_name")

# run_id is interpolated into PostgREST filters by the reporter, so it must be
# a real UUID, not merely a string.
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class InvalidParams(ValueError):
    """The invocation payload or its ``params`` violate the contract.

    ``field`` names the offending field (``run_id``, ``params``,
    ``params.<key>``, ...). The message never echoes the offending value.
    """

    def __init__(self, field: str, problem: str) -> None:
        self.field = field[:_MAX_FIELD_CHARS]
        super().__init__(f"{self.field}: {problem}"[:_MAX_MESSAGE_CHARS])


def _is_int(value: Any) -> bool:
    # JSON Schema `integer`: bool is an int subclass in Python but never valid.
    return isinstance(value, int) and not isinstance(value, bool)


def _check_property(name: str, prop: dict[str, Any], value: Any) -> None:
    field = f"params.{name}"
    kind = prop["type"]
    if kind == "integer":
        if not _is_int(value):
            raise InvalidParams(field, "must be an integer")
        if "minimum" in prop and value < prop["minimum"]:
            raise InvalidParams(field, f"must be >= {prop['minimum']}")
        if "maximum" in prop and value > prop["maximum"]:
            raise InvalidParams(field, f"must be <= {prop['maximum']}")
    elif kind == "string":
        if not isinstance(value, str):
            raise InvalidParams(field, "must be a string")
        if "enum" in prop and value not in prop["enum"]:
            raise InvalidParams(field, f"must be one of {', '.join(prop['enum'])}")
    else:  # pragma: no cover - guarded by test_seed_contract (schema equals spec §5.1)
        raise InvalidParams(field, f"unsupported schema type {kind!r}")


def validate_params(params: Any) -> None:
    """Validate ``params`` against ``PARAMS_SCHEMA`` (spec §5.1).

    Same verdicts as the panel's Ajv path (CT-01): an object with no unknown
    keys, ``pr_number`` present, integers in range (``bool`` rejected), and
    ``reasoning_effort`` in its enum. Raises :class:`InvalidParams`.
    """
    if not isinstance(params, dict):
        raise InvalidParams("params", "must be an object")
    properties: dict[str, dict[str, Any]] = PARAMS_SCHEMA["properties"]
    unknown = sorted(str(k) for k in params if k not in properties)
    if unknown:
        raise InvalidParams(f"params.{unknown[0]}", "is not a known parameter")
    for name in PARAMS_SCHEMA["required"]:
        if name not in params:
            raise InvalidParams(f"params.{name}", "is required")
    for name, prop in properties.items():
        if name in params:
            _check_property(name, prop, params[name])


def validate_payload(payload: Any) -> None:
    """Validate the unwrapped invocation payload (spec §6.1). Never mutates it.

    Requires non-empty string ``run_id`` (a UUID), ``repository_org`` and
    ``repository_name``, plus a valid ``params`` object. Unknown top-level keys
    are tolerated (sibling behavior, CT-03). Raises :class:`InvalidParams`.
    """
    if not isinstance(payload, dict):
        raise InvalidParams("payload", "must be an object")
    for name in _TOP_LEVEL_FIELDS:
        if name not in payload:
            raise InvalidParams(name, "is required")
        value = payload[name]
        if not isinstance(value, str) or not value.strip():
            raise InvalidParams(name, "must be a non-empty string")
    if not _UUID.fullmatch(payload["run_id"]):
        raise InvalidParams("run_id", "must be a UUID")
    if "params" not in payload:
        raise InvalidParams("params", "is required")
    validate_params(payload["params"])


def apply_defaults(params: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with the spec §5.1 defaults filled in. Idempotent."""
    out = dict(params)
    for key, value in DEFAULT_PARAMS.items():
        out.setdefault(key, value)
    return out


def _reportable_run_id(payload: Any) -> str | None:
    """The run_id if it is safe to report against, else ``None``."""
    if not isinstance(payload, dict):
        return None
    run_id = payload.get("run_id")
    if isinstance(run_id, str) and _UUID.fullmatch(run_id):
        return run_id
    return None


# ---------------------------------------------------------------------------
# Return payload (spec §6.1)
# ---------------------------------------------------------------------------


def build_return_payload(
    status: str,
    outcome: str,
    error_code: str | None,
    *,
    verdict: str | None = None,
    comment_url: str | None = None,
) -> dict[str, Any]:
    """The terminal chunk body: ``{outcome, verdict, comment_url}`` plus status/error."""
    return {
        "status": status,
        "outcome": outcome,
        "verdict": verdict,
        "comment_url": comment_url,
        "error_code": error_code,
    }


def _failed(error_code: str) -> dict[str, Any]:
    return build_return_payload("failed", "not_applicable", error_code)


# ---------------------------------------------------------------------------
# Pipeline (spec §8.1) — S-204 skeleton, replaced in S-213
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewRequest:
    """A validated invocation with defaults applied."""

    run_id: str
    repository_org: str
    repository_name: str
    params: dict[str, Any]
    settings: Settings


def load_pr(request: ReviewRequest) -> None:
    """Step ``load_pr``: mint the token and read the pull request (S-213)."""
    raise NotImplementedError("not implemented")


def run_review(run: RunReporter, request: ReviewRequest) -> dict[str, Any]:
    """Run the review pipeline under ``run`` and return the terminal payload."""
    with run.step("load_pr"):
        load_pr(request)
    return build_return_payload("succeeded", "not_applicable", None)  # pragma: no cover - S-213


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


@app.entrypoint
async def invoke(payload: Any, context: Any):
    """AgentCore entrypoint: validate, report, run the pipeline, yield one terminal chunk."""
    secrets: list[str] = []

    # Refuse to start with inconsistent clocks (D-32): better than dying silently.
    try:
        assert_clock_invariant()
    except ClockConsistencyError as exc:
        log.error("Clock invariant violated: %s", exc)
        yield terminal_chunk(json.dumps(_failed("INTERNAL_ERROR")))
        return

    payload = unwrap_payload(payload)
    invalid: InvalidParams | None = None
    try:
        validate_payload(payload)
    except InvalidParams as exc:
        invalid = exc
        if classify_invalid_payload(payload) == "wrapper_only":
            log.error(
                "Invalid payload: still wrapped after unwrapping (only key is 'prompt'). "
                "Pass the bare inner JSON, e.g. `agentcore invoke --prompt-file <inner.json>`."
            )
        else:
            log.error("Invalid payload: %s", exc)

    run_id = _reportable_run_id(payload)
    if invalid is not None and run_id is None:
        # No trustworthy run row to update; the reaper closes it (if any).
        yield terminal_chunk(json.dumps(_failed("INVALID_PARAMS")))
        return
    assert run_id is not None

    try:
        settings = load_settings()
    except ConfigError as exc:
        log.error("Configuration error: %s", exc)
        yield terminal_chunk(json.dumps(_failed("INTERNAL_ERROR")))
        return

    try:
        supabase_key = fetch_supabase_key(settings.supabase_key_secret_id)
    except Exception as exc:
        code = exc.code if isinstance(exc, CredentialError) else type(exc).__name__
        log.error("Could not resolve the Supabase key (%s)", code)
        yield terminal_chunk(json.dumps(_failed("INTERNAL_ERROR")))
        return
    secrets.append(supabase_key)

    run = RunReporter(
        supabase_url=settings.supabase_url,
        supabase_key=supabase_key,
        run_id=run_id,
        params=payload,
    )
    with run:
        install_termination_backstop(lambda: run, lambda: secrets)
        if invalid is not None:
            run.fail(
                error_code="INVALID_PARAMS",
                error_message=str(invalid),
                outcome="not_applicable",
            )
            result = _failed("INVALID_PARAMS")
        else:
            request = ReviewRequest(
                run_id=run_id,
                repository_org=payload["repository_org"],
                repository_name=payload["repository_name"],
                params=apply_defaults(payload["params"]),
                settings=settings,
            )
            try:
                result = run_review(run, request)
            except Exception as exc:
                log.error("Unhandled exception:\n%s", scrub(traceback.format_exc(), secrets))
                message = scrub(str(exc), secrets) or type(exc).__name__
                run.fail(
                    error_code="INTERNAL_ERROR",
                    error_message=message,
                    outcome="not_applicable",
                )
                result = _failed("INTERNAL_ERROR")

    yield terminal_chunk(json.dumps(result))


if __name__ == "__main__":
    app.run()
