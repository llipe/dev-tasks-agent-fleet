"""
bug-fix agent — AgentCore entrypoint (S-180 skeleton).

This story ships only the skeleton: the entrypoint validates its config and
payload, resolves the Supabase key, reports ``started`` through
``agent_reporter``, and ends ``succeeded``/``not_applicable`` with the summary
"not yet implemented". A deploy of this image is therefore harmless (S-181).
The step orchestration and the spec §8.9 outcome mapping land in S-190.

Payload (spec §6, D-60): ``{run_id, repository_org, repository_name,
base_branch, params}``, optionally wrapped as ``{"prompt": "<json>"}``.

Secrets (spec §12): every resolved secret is held in a :class:`SecretSet` in
this process's memory. Nothing is exported to ``os.environ``, so no child
process can inherit a secret, and every message leaving the process is
scrubbed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from agent_reporter import RunReporter
from config import ConfigError, load_config
from credentials import CredentialError, fetch_supabase_key
from heartbeat import terminal_chunk
from scrubber import SecretSet, scrub_all, scrub_exception
from signal_backstop import install_termination_backstop

log = logging.getLogger("bug_fix")

app = BedrockAgentCoreApp()

NOT_IMPLEMENTED = "not yet implemented"


class InvalidPayloadError(ValueError):
    """The invocation payload is not a usable run request."""


def _result(status: str, outcome: str, summary: str, error_code: str | None = None) -> dict:
    out: dict[str, Any] = {"status": status, "outcome": outcome, "summary": summary}
    if error_code is not None:
        out["error_code"] = error_code
    return out


def unwrap_payload(payload: Any) -> dict:
    """Return the run request, unwrapping ``{"prompt": "<json>"}`` once."""
    if isinstance(payload, dict) and set(payload) == {"prompt"}:
        try:
            payload = json.loads(payload["prompt"])
        except (TypeError, ValueError):
            raise InvalidPayloadError("prompt is not JSON") from None
    if not isinstance(payload, dict):
        raise InvalidPayloadError("payload is not an object")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise InvalidPayloadError("run_id is missing")
    return payload


def _run_steps(run: RunReporter) -> None:
    """The run's work. S-180: a stub that ends ``not_applicable``."""
    run.info("bug-fix agent started (S-180 skeleton)")
    run.succeed("not_applicable", result={"summary": NOT_IMPLEMENTED})


@app.entrypoint
async def invoke(payload: Any, context: Any) -> AsyncIterator[dict]:
    secrets = SecretSet()

    try:
        cfg = load_config()
    except ConfigError as exc:
        # The message names the variable, never its value.
        log.error("Configuration error: %s", exc)
        yield terminal_chunk(
            json.dumps(_result("failed", "not_applicable", str(exc), "CONFIG_INVALID"))
        )
        return

    try:
        request = unwrap_payload(payload)
    except InvalidPayloadError as exc:
        log.error("Invalid payload: %s", exc)
        yield terminal_chunk(
            json.dumps(_result("failed", "not_applicable", str(exc), "INVALID_PAYLOAD"))
        )
        return

    try:
        supabase_key = fetch_supabase_key(cfg.supabase_key_secret_id)
    except CredentialError as exc:
        # Spec §8.9: secrets / token mint -> failed / CREDENTIALS_UNAVAILABLE.
        summary = scrub_all(f"credentials unavailable ({exc.code})", secrets)
        log.error("%s", summary)
        yield terminal_chunk(
            json.dumps(_result("failed", "not_applicable", summary, "CREDENTIALS_UNAVAILABLE"))
        )
        return
    secrets.add("SUPABASE_SERVICE_ROLE_KEY", supabase_key)

    run = RunReporter(
        supabase_url=cfg.supabase_url,
        supabase_key=supabase_key,
        run_id=request["run_id"],
        params=request,
    )
    with run:  # start(): status running (the "started" report)
        install_termination_backstop(lambda: run, secrets.values)
        try:
            _run_steps(run)
        except Exception as exc:  # noqa: BLE001 — reported, scrubbed, never re-raised
            message = scrub_exception(exc, secrets)
            log.error("Unhandled error: %s", message)
            # Report here, scrubbed, so RunReporter.__exit__ never writes the
            # raw exception text to Supabase.
            run.fail("UNHANDLED_ERROR", message, outcome="not_applicable")
            yield terminal_chunk(
                json.dumps(_result("failed", "not_applicable", message, "UNHANDLED_ERROR"))
            )
            return

    yield terminal_chunk(json.dumps(_result("succeeded", "not_applicable", NOT_IMPLEMENTED)))


if __name__ == "__main__":
    app.run()
