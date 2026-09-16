"""
security-analyst agent — pipeline orchestrator entrypoint.

Receives invocation payloads via AgentCore HTTP protocol. S-125 scaffolded
the project, deploy, and reporting/credential pipe with a placeholder
pipeline that went straight to `succeeded` / `no_findings` for every mode —
zero scanners run. This story (S-135) replaces that placeholder for
`mode=audit_only` with the real five-tool dispatch → dedupe → classify →
report → `determine_outcome()` pipeline (spec §8.8's state machine up to and
including `audit_report`). `mode=fix` is intentionally left on the S-125
placeholder here — S-136-S-140 wire `fix`/`rescan`/`open_pr` into it; this
story's task list explicitly scopes out touching that path.

Step keys (spec S8.8, this story's subset):
    resolve_credentials, checkout, scan, classify
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import traceback
from pathlib import Path

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from agent_reporter import RunReporter
from classifier import Bucket, classify
from config import (
    DEFAULT_FAIL_ON_FINDINGS,
    DEFAULT_MAX_FIX_ATTEMPTS,
    DEFAULT_MIN_SEVERITY,
    DEFAULT_MODE,
    HEARTBEAT_INTERVAL,
    MAX_FIX_ATTEMPTS_CEILING,
    SCANNER_TIMEOUT,
    SUPABASE_URL,
    assert_clock_invariant,
)
from credentials import CredentialError, fetch_supabase_key, resolve_github_credentials
from dedupe import MergedFinding, dedupe
from heartbeat import HeartbeatResult, is_heartbeat_chunk, run_with_heartbeat, terminal_chunk
from scanners import AllScannersFailedError, run_scanners
from scanners.types import ScanStatus
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
# State machine — status/outcome mapping (spec §8.10, PRD §8.1 / D31)
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _at_or_above_floor(findings: list[MergedFinding], min_severity: str) -> list[MergedFinding]:
    """Filter `findings` to those at/above `min_severity` (spec §8.10).

    Used ONLY by `determine_outcome()` to decide the terminal status — never
    to narrow what is scanned, fixed, or reported (PRD requirement 63). The
    `audit_report` artifact (`build_audit_report()` below) is built from the
    full, unfiltered set, deliberately never from this function's output.
    """
    floor = _SEVERITY_ORDER[min_severity]
    return [f for f in findings if _SEVERITY_ORDER[f.finding.severity.value] >= floor]


def determine_outcome(
    mode: str,
    findings: list[MergedFinding],
    min_severity: str,
    fail_on_findings: bool,
) -> tuple[str, str, str | None]:
    """Pure function: (status, outcome, error_code) from pipeline state (spec §8.10).

    `findings` MUST be the full, unfiltered set — `min_severity` is applied
    here only, via `_at_or_above_floor()` (PRD requirement 63).

    Scope (story S-135): only the `audit_only` branch of spec §8.10's
    pseudocode is implemented. `mode="fix"` is out of this story's scope
    (S-136-S-140 wire `fix`/`rescan`/`open_pr`); callers must not reach this
    function with `mode="fix"` yet — `main.invoke()` keeps that mode on the
    S-125 placeholder pipeline instead of calling this function.

    Deviation from spec §8.10's literal pseudocode: the spec's
    `determine_outcome()` returns a 4-tuple `(status, outcome, error_code,
    pr_opened)`, mirroring the sibling agent's `PipelineState`-driven shape.
    This story's caller has no PR-opening branch to report (`audit_only`
    never opens a PR — PRD §8.1), so `pr_opened` is dropped here rather than
    hard-coded to `False` at every call site; this mirrors the sibling
    agent's own `main.py::determine_outcome()`, which returns a 3-tuple for
    the identical reason. S-140 (which adds the `fix` branch, where
    `pr_opened` is meaningful) is expected to either widen this signature
    back to 4 elements or compute `pr_opened` separately at the call site, as
    the sibling agent does — a call-site decision, not re-litigated here.
    """
    gated_findings = _at_or_above_floor(findings, min_severity)

    if mode == "audit_only":
        if not gated_findings:
            return "succeeded", "no_findings", None
        if not fail_on_findings:
            return "succeeded", "needs_review", None
        return "failed", "needs_review", "AUDIT_FINDINGS"

    raise NotImplementedError(f"determine_outcome: mode={mode!r} not yet wired (S-136-S-140 scope)")


def _finding_summary(merged: MergedFinding, bucket: Bucket) -> dict:
    """One finding's JSON-safe summary for the `audit_report` artifact (task 11.3).

    Enums are projected to their `.value` explicitly (never left for
    `agent_reporter`'s `json.dumps(..., default=str)` fallback, which would
    stringify them as e.g. ``"Severity.HIGH"`` instead of ``"high"``).
    """
    f = merged.finding
    return {
        "tool": f.tool,
        "rule_id": f.rule_id,
        "severity": f.severity.value,
        "file_path": f.file_path,
        "line_start": f.line_start,
        "line_end": f.line_end,
        "message": f.message,
        "cwe_or_category": f.cwe_or_category,
        "bucket": bucket.value,
        "reported_by": list(merged.reported_by),
    }


def build_audit_report(classified: list[tuple[MergedFinding, Bucket]]) -> dict:
    """Build the `audit_report` artifact metadata (spec §8.5/§8.10, task 11.3).

    Groups every finding by bucket/tool/severity. Includes EVERY finding
    regardless of `min_severity` — the floor gates only the terminal status
    (`determine_outcome()`, above), never what is reported here (PRD
    requirement 62 / AC-12b, task 11.8). ``classified`` is expected to carry
    the full, unfiltered finding set for exactly that reason.
    """
    summaries = [_finding_summary(m, b) for m, b in classified]
    by_bucket: dict[str, list[dict]] = {
        "mechanical": [],
        "manual": [],
        "unscannable": [],
    }
    by_tool: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for summary in summaries:
        by_bucket[summary["bucket"]].append(summary)
        by_tool[summary["tool"]] = by_tool.get(summary["tool"], 0) + 1
        by_severity[summary["severity"]] = by_severity.get(summary["severity"], 0) + 1
    return {
        "total_findings": len(summaries),
        "by_bucket": by_bucket,
        "by_tool": by_tool,
        "by_severity": by_severity,
    }


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
    Main invocation handler — pipeline orchestrator.

    `mode=audit_only` (this story, S-135): resolve_credentials -> checkout ->
    scan -> classify -> `audit_report` artifact -> `determine_outcome()`.
    `scan` is wrapped in `heartbeat.run_with_heartbeat()` (spec §8.8 — the
    single longest step, CodeQL's database-build phase in particular).

    `mode=fix` remains on the S-125 placeholder pipeline (straight to
    `succeeded`/`no_findings`, no scanners run) — S-136-S-140 wire
    `fix`/`rescan`/`open_pr` into it; out of this story's scope.
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

            if params["mode"] == "audit_only":
                # --- Step: scan (S-135) — heartbeated, longest step ---
                with run.step("scan"):

                    def _do_scan():
                        return run_scanners(Path(workspace), params["scanners"], SCANNER_TIMEOUT)

                    _scan_holder: dict = {}
                    async for _item in run_with_heartbeat(_do_scan, interval=HEARTBEAT_INTERVAL):
                        if isinstance(_item, HeartbeatResult):
                            if _item.error is not None:
                                raise _item.error
                            _scan_holder["result"] = _item.value
                        elif is_heartbeat_chunk(_item):
                            yield _item
                    scan_results = _scan_holder["result"]

                scanners_run = [r.tool for r in scan_results if r.status == ScanStatus.PASSED]
                scanners_skipped = [r.tool for r in scan_results if r.status == ScanStatus.SKIPPED]
                scanners_failed = [r.tool for r in scan_results if r.status == ScanStatus.FAILED]
                for r in scan_results:
                    if r.status == ScanStatus.FAILED:
                        # req 18 -- per-tool failure recorded at error level,
                        # non-fatal to the run (AllScannersFailedError already
                        # handles the all-failed case, raised inside run_scanners).
                        log.error("Scanner %s failed: %s", r.tool, r.reason)
                log.info(
                    "Scan complete: run=%s skipped=%s failed=%s",
                    scanners_run,
                    scanners_skipped,
                    scanners_failed,
                )

                # --- Step: classify (S-135) — dedupe then classify ---
                with run.step("classify"):
                    all_findings = [f for r in scan_results for f in r.findings]
                    merged = dedupe(all_findings)
                    classified = [(m, classify(m)) for m in merged]

                # --- audit_report artifact (task 11.3) — full, unfiltered set ---
                audit_report = build_audit_report(classified)
                run.artifact("audit_report", title="Security scan findings", **audit_report)

                findings_before = {
                    "mechanical": len(audit_report["by_bucket"]["mechanical"]),
                    "manual": len(audit_report["by_bucket"]["manual"]),
                    "unscannable": len(audit_report["by_bucket"]["unscannable"]),
                }

                status, outcome, error_code = determine_outcome(
                    mode="audit_only",
                    findings=merged,
                    min_severity=params["min_severity"],
                    fail_on_findings=params["fail_on_findings"],
                )

                result = build_return_payload(
                    status=status,
                    outcome=outcome,
                    error_code=error_code,
                    findings_before=findings_before,
                    scanners_run=scanners_run,
                    scanners_skipped=scanners_skipped,
                    scanners_failed=scanners_failed,
                )
                if status == "succeeded":
                    run.succeed(outcome, metrics=build_metrics(result))
                else:
                    # `determine_outcome()`'s only `status="failed"` branch for
                    # `audit_only` always pairs it with `error_code="AUDIT_FINDINGS"`
                    # (spec §8.10) -- narrow the type for `run.fail()`'s `str` param.
                    assert error_code is not None
                    run.fail(
                        error_code,
                        error_message=(
                            f"audit_only run found {audit_report['total_findings']} "
                            f"finding(s) at/above min_severity={params['min_severity']!r} "
                            "with fail_on_findings=true"
                        ),
                        outcome=outcome,
                        metrics=build_metrics(result),
                    )
                yield terminal_chunk(json.dumps(result))

            else:
                # --- Placeholder outcome for mode=fix (S-136-S-140 wire this) ---
                result = build_return_payload(
                    status="succeeded",
                    outcome="no_findings",
                    error_code=None,
                    scanners_skipped=params["scanners"],
                )
                run.succeed(result["outcome"], metrics=build_metrics(result))
                yield terminal_chunk(json.dumps(result))

    except AllScannersFailedError as exc:
        # req 18 / AC-24 -- every requested scanner failed; the whole audit
        # produced no usable signal. Distinct error_code, not UNHANDLED_ERROR.
        log.error("All requested scanners failed: %s", exc)
        result = build_return_payload(
            "failed",
            "not_applicable",
            "ALL_SCANNERS_FAILED",
            scanners_failed=[r.tool for r in exc.results],
        )
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
