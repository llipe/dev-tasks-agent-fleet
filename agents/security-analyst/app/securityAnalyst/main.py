"""
security-analyst agent — pipeline orchestrator entrypoint.

Receives invocation payloads via AgentCore HTTP protocol. This story (S-125)
scaffolds the project, deploy, and reporting/credential pipe: the entrypoint
validates the payload and runs a placeholder pipeline that goes straight to
`succeeded` / `no_findings` — zero scanners run yet. Later stories (S-126+)
replace the placeholder `scan` step with the real five-tool dispatcher.

Step keys (spec S8.8, this story's subset):
    resolve_credentials, checkout
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import traceback

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from agent_reporter import RunReporter
from config import (
    DEFAULT_FAIL_ON_FINDINGS,
    DEFAULT_MAX_FIX_ATTEMPTS,
    DEFAULT_MIN_SEVERITY,
    DEFAULT_MODE,
    MAX_FIX_ATTEMPTS_CEILING,
    SUPABASE_URL,
    assert_clock_invariant,
)
from credentials import CredentialError, fetch_supabase_key, resolve_github_credentials
from heartbeat import terminal_chunk
from scrubber import scrub, scrub_process_error
from signal_backstop import install_termination_backstop

app = BedrockAgentCoreApp()
log = app.logger

# ---------------------------------------------------------------------------
# Payload unwrapping and validation (spec S6.1)
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = {"run_id", "repository_org", "repository_name"}
_VALID_MODES = {"audit_only", "fix"}
_VALID_SCANNERS = {"semgrep", "gitleaks", "trivy", "checkov", "codeql"}
_VALID_SEVERITIES = {"low", "medium", "high", "critical"}  # PRD S7.4b / D31

# Max nested ``prompt`` layers to strip. One layer is the historical control-plane
# form; two layers is the agentcore CLI >= 0.28.0 double-wrap (mirrors the
# sibling agent's issue #97 fix). The bound is a defensive guard against a
# pathological lone-``prompt`` chain — real payloads never approach it.
_MAX_UNWRAP_DEPTH = 16


class InvalidParamsError(Exception):
    """Raised when the invocation payload fails validation (PRD AC28)."""


def unwrap_payload(raw: dict) -> dict:
    """
    Handle the AgentCore ``prompt`` wrapper (spec S6.1, mirrors sibling agent).

    Repeatedly unwraps while the current value is a dict whose *only* key is
    ``prompt`` and whose string value parses to a JSON dict, tolerating both
    the historical single-wrap and the agentcore CLI >= 0.28.0 double-wrap.
    Always returns a ``dict``.
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


def _is_lone_prompt_wrapper(payload: dict) -> bool:
    """True when ``payload`` is a dict whose only key is a string ``prompt``."""
    return (
        isinstance(payload, dict)
        and list(payload.keys()) == ["prompt"]
        and isinstance(payload["prompt"], str)
    )


def validate_payload(payload: dict) -> None:
    """
    Validate the payload against the expected schema (spec S6.1, PRD AC28).

    Raises :class:`InvalidParamsError` on the first violation. Never mutates
    ``payload``.
    """
    missing = _REQUIRED_FIELDS - payload.keys()
    if missing:
        raise InvalidParamsError(f"missing required fields: {sorted(missing)}")

    params = payload.get("params")
    if not isinstance(params, dict):
        params = {}

    mode = params.get("mode", DEFAULT_MODE)
    if mode not in _VALID_MODES:
        raise InvalidParamsError(f"unknown mode: {mode!r}")

    scanners = set(params.get("scanners", sorted(_VALID_SCANNERS)))
    if not scanners or not scanners.issubset(_VALID_SCANNERS):
        raise InvalidParamsError(f"invalid scanners list: {sorted(scanners)!r}")

    min_severity = params.get("min_severity", DEFAULT_MIN_SEVERITY)
    if min_severity not in _VALID_SEVERITIES:
        raise InvalidParamsError(f"unknown min_severity: {min_severity!r}")


def apply_defaults(params: dict) -> dict:
    """
    Apply parameter defaults (spec S6.1, req 64).

    Defaults: mode=audit_only, fail_on_findings=true, min_severity=low
    (additive — req 64), max_fix_attempts=3 (clamped 0..5), scanners=all five.
    """
    mfa_raw = params.get("max_fix_attempts", DEFAULT_MAX_FIX_ATTEMPTS)
    try:
        mfa = int(mfa_raw)
    except (TypeError, ValueError):
        mfa = DEFAULT_MAX_FIX_ATTEMPTS
    mfa = max(0, min(mfa, MAX_FIX_ATTEMPTS_CEILING))

    return {
        "mode": params.get("mode", DEFAULT_MODE),
        "fail_on_findings": params.get("fail_on_findings", DEFAULT_FAIL_ON_FINDINGS),
        "min_severity": params.get("min_severity", DEFAULT_MIN_SEVERITY),
        "max_fix_attempts": mfa,
        "scanners": params.get("scanners", sorted(_VALID_SCANNERS)),
    }


def classify_invalid_payload(payload: str | dict) -> str:
    """Classify why a post-unwrap payload failed validation (mirrors sibling agent).

    Returns ``"wrapper_only"`` when the payload's only key is ``prompt`` — the
    tell-tale of a still-wrapped (e.g. double-wrapped) payload that could not be
    unwrapped to real fields — otherwise ``"missing_fields"``.
    """
    if isinstance(payload, dict) and list(payload.keys()) == ["prompt"]:
        return "wrapper_only"
    return "missing_fields"


# ---------------------------------------------------------------------------
# Return payload assembly (spec S6.2)
# ---------------------------------------------------------------------------


def build_return_payload(
    status: str,
    outcome: str,
    error_code: str | None,
    pr_url: str | None = None,
    findings_before: dict | None = None,
    findings_after: dict | None = None,
    findings_fixed: int = 0,
    scanners_run: list | None = None,
    scanners_skipped: list | None = None,
    scanners_failed: list | None = None,
    fix_attempts_deterministic: int = 0,
    fix_attempts_llm: int = 0,
    llm_used: bool = False,
) -> dict:
    """Assemble the structured return payload per spec S6.2."""
    return {
        "status": status,
        "outcome": outcome,
        "error_code": error_code,
        "pr_url": pr_url,
        "findings_before": findings_before or {"mechanical": 0, "manual": 0, "unscannable": 0},
        "findings_after": findings_after,
        "findings_fixed": findings_fixed,
        "scanners_run": scanners_run or [],
        "scanners_skipped": scanners_skipped or [],
        "scanners_failed": scanners_failed or [],
        "fix_attempts_deterministic": fix_attempts_deterministic,
        "fix_attempts_llm": fix_attempts_llm,
        "llm_used": llm_used,
    }


# Metric fields persisted into the ``runs.metrics`` column (spec S6.2, mirrors
# sibling agent's build_metrics). status/outcome/error_code/pr_url are their
# own columns, not metrics.
_METRIC_FIELDS = (
    "llm_used",
    "fix_attempts_deterministic",
    "fix_attempts_llm",
    "findings_fixed",
    "scanners_run",
    "scanners_skipped",
    "scanners_failed",
)


def build_metrics(result: dict) -> dict:
    """Project the metric fields out of a return payload (spec S6.2)."""
    metrics = {field: result[field] for field in _METRIC_FIELDS}
    metrics["findings_before"] = result["findings_before"]
    metrics["findings_after"] = result["findings_after"]
    return metrics


# ---------------------------------------------------------------------------
# Clone logic (mirrors sibling agent, no caller-supplied URL)
# ---------------------------------------------------------------------------


def clone_repo(org: str, name: str, token: str, secrets: list[str]) -> str:
    """
    Clone the repository shallow (--depth 1) and scrub the token from .git/config.

    Returns the workspace path (temp directory). Clone URL is always derived:
    https://github.com/{org}/{name}.git — no caller-supplied URL.
    """
    workspace = tempfile.mkdtemp(prefix=f"security-analyst-{name}-")
    url = f"https://x-access-token:{token}@github.com/{org}/{name}.git"

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", url, workspace],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except subprocess.CalledProcessError as exc:
        scrub_process_error(exc, secrets)
        raise

    # Scrub token from .git/config
    clean_url = f"https://github.com/{org}/{name}.git"
    subprocess.run(
        ["git", "remote", "set-url", "origin", clean_url],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )

    subprocess.run(
        ["git", "config", "user.email", "agent@fleet.local"],
        cwd=workspace,
        capture_output=True,
        check=True,
        timeout=10,
    )
    subprocess.run(
        ["git", "config", "user.name", "security-analyst-agent"],
        cwd=workspace,
        capture_output=True,
        check=True,
        timeout=10,
    )

    return workspace


# ---------------------------------------------------------------------------
# Main orchestrator (placeholder pipeline, spec S8.8 subset)
# ---------------------------------------------------------------------------


@app.entrypoint
async def invoke(payload: dict, context):
    """
    Main invocation handler — placeholder pipeline orchestrator (S-125).

    Steps this story implements:
      resolve_credentials -> checkout -> succeeded/no_findings

    No scanner runs yet (S-126+ replaces this with the real `scan` step). The
    outcome is a deliberate placeholder, not a shortcut: it proves the
    deploy/credential/reporting pipe end-to-end before any scanner logic
    exists.
    """
    secrets: list[str] = []

    try:
        # Fail fast if the timeout clocks are inconsistent (PRD AC31
        # groundwork): better to refuse to start than to die silently later.
        assert_clock_invariant()

        # --- Unwrap and validate payload (spec S6.1, PRD AC28) ---
        payload = unwrap_payload(payload)
        try:
            validate_payload(payload)
        except InvalidParamsError:
            if classify_invalid_payload(payload) == "wrapper_only":
                log.error(
                    "Invalid payload — appears double-wrapped (only key is "
                    "'prompt' after unwrapping). Pass the bare inner JSON, not a "
                    "pre-wrapped '{\"prompt\": ...}' string; e.g. "
                    "`agentcore invoke --prompt-file <inner.json>`."
                )
            else:
                log.error("Invalid payload — missing/invalid required fields")
            result = build_return_payload("failed", "not_applicable", "INVALID_PARAMS")
            yield terminal_chunk(json.dumps(result))
            return

        params_in = payload.get("params")
        params = apply_defaults(params_in if isinstance(params_in, dict) else {})
        payload["params"] = params
        run_id = payload["run_id"]
        org = payload["repository_org"]
        name = payload["repository_name"]

        # --- Resolve Supabase key and init reporter (mirrors sibling D24) ---
        supabase_key = fetch_supabase_key()
        secrets.append(supabase_key)
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = supabase_key
        os.environ["SUPABASE_URL"] = SUPABASE_URL
        os.environ["RUN_ID"] = run_id
        os.environ["RUN_PARAMS"] = json.dumps(payload)

        with RunReporter.from_env() as run:
            install_termination_backstop(lambda: run, lambda: secrets)

            # --- Step: resolve_credentials ---
            with run.step("resolve_credentials"):
                token_ctx = resolve_github_credentials(org)
                secrets.append(token_ctx.token)
                log.info("GitHub credentials resolved for org=%s", org)

            # --- Step: checkout ---
            with run.step("checkout"):
                workspace = clone_repo(org, name, token_ctx.token, secrets)
                log.info("Repository cloned to %s", workspace)

            # --- Placeholder outcome: no scanners run yet (S-126+) ---
            result = build_return_payload(
                status="succeeded",
                outcome="no_findings",
                error_code=None,
                scanners_skipped=params["scanners"],
            )
            run.succeed(result["outcome"], metrics=build_metrics(result))
            yield terminal_chunk(json.dumps(result))

    except CredentialError as exc:
        log.error("Credential error: %s", exc)
        result = build_return_payload("failed", "not_applicable", exc.code)
        yield terminal_chunk(json.dumps(result))

    except Exception:
        # Unhandled exception — RunReporter's context manager handles marking
        # the run failed + closing open steps. We still return a payload.
        tb = traceback.format_exc()
        log.error("Unhandled exception:\n%s", scrub(tb, secrets))
        result = build_return_payload("failed", "not_applicable", "UNHANDLED_ERROR")
        yield terminal_chunk(json.dumps(result))


if __name__ == "__main__":
    app.run()
