"""
security-analyst agent — pipeline orchestrator entrypoint.

Receives invocation payloads via AgentCore HTTP protocol. S-125 scaffolded
the project, deploy, and reporting/credential pipe with a placeholder
pipeline that went straight to `succeeded` / `no_findings` for every mode —
zero scanners run. S-135 replaced that placeholder for `mode=audit_only`
with the real five-tool dispatch → dedupe → classify → report →
`determine_outcome()` pipeline (spec §8.8's state machine up to and
including `audit_report`). This story (S-140) is the capstone: it wires
`mode=fix`'s `fix` → `rescan` → `open_pr` steps into the same orchestrator,
completing the full state machine for both modes and reconciling the two
forward-reference gaps S-135/S-139 left open (see `determine_outcome()`'s
and `pull_request.py`'s docstrings for the resolution of each).

Step keys (spec S8.8):
    resolve_credentials, checkout, scan, classify — shared by both modes.
    fix, rescan, open_pr — `mode=fix` only (spec §8.8's diagram: `classify
    --> fix: mode=fix`; `classify --> audit_report: mode=audit_only` has no
    step of its own — `audit_report` is an artifact, not a `run_steps` key,
    exactly as `fix`/`rescan`/`open_pr` are).

`mode=fix`'s no-mechanical-findings short-circuit (AC21) enters only the
`fix` step and then terminates — `rescan`/`open_pr` are never entered in
that case, mirroring how `audit_only` mode never enters `fix`/`rescan`/
`open_pr` at all. AC29's "all 7 run_steps present" is therefore a property
of the full happy/blocked-at-rescan path (where mechanical findings existed
and the run reached at least the `rescan` step), not every possible branch
— the same precedent already established by `audit_only`'s 4-step-only
happy path never needing a 5th step for `audit_report`.
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
from fingerprint import fingerprint
from fix_agent import run_fix_loop_for_finding
from fixers.semgrep_autofix import apply_semgrep_autofix
from fixers.trivy_bump import apply_trivy_bump
from heartbeat import HeartbeatResult, is_heartbeat_chunk, run_with_heartbeat, terminal_chunk
from pull_request import PipelineState, PullRequestError, build_pr_body, open_pr_if_needed
from rescan import rescan_gate
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
    *,
    mechanical_findings: list[MergedFinding] | None = None,
    manual_or_unscannable_findings: list[MergedFinding] | None = None,
    rescan_clean: bool | None = None,
    pr_existed: bool = False,
) -> tuple[str, str, str | None]:
    """Pure function: (status, outcome, error_code) from pipeline state (spec §8.10).

    `findings` MUST be the full, unfiltered set — `min_severity` is applied
    here only, via `_at_or_above_floor()` (PRD requirement 63). For
    `mode="fix"`, `findings` is only used by callers for logging/symmetry;
    the actual gating input is `manual_or_unscannable_findings` (see below).

    `audit_only` (story S-135, unchanged): `mechanical_findings` /
    `manual_or_unscannable_findings` / `rescan_clean` / `pr_existed` are all
    ignored — this branch's behavior and return values are byte-for-byte
    identical to before this story, so every already-merged `audit_only`
    test keeps passing unmodified.

    `fix` (story S-140, spec §8.10's second pseudocode block):
      - `mechanical_findings` empty -> `succeeded`, outcome is
        `needs_review` if any of `manual_or_unscannable_findings` clears
        `min_severity`, else `no_findings` (AC21). `min_severity` never
        changes *which* findings were fixed/scanned (req 63) — it only
        labels the outcome here, exactly as the `audit_only` branch does.
      - `mechanical_findings` non-empty and `rescan_clean` is falsy ->
        `failed`/`needs_review`/`RESCAN_NOT_CLEAN`, no PR (AC14/AC15).
      - `mechanical_findings` non-empty and `rescan_clean` is true and
        `pr_existed` -> `succeeded`/`not_applicable` (PRD AC22's
        idempotency short-circuit).
      - Otherwise -> `succeeded`, `fixed` if `manual_or_unscannable_findings`
        is empty else `partial` (AC13).

    Deviation from spec §8.10's literal pseudocode, carried forward
    unchanged from S-135 and now resolved by this story (documented in both
    places per that story's own forward-reference note): the spec's
    `determine_outcome()` returns a 4-tuple `(status, outcome, error_code,
    pr_opened)`. This function keeps the existing 3-tuple shape for BOTH
    modes — `audit_only` never opens a PR (`pr_opened` would always be
    `False`, redundant to carry), and for `fix` mode, `pr_opened` is fully
    recoverable by the caller as `status == "succeeded" and outcome in
    ("fixed", "partial")` (it is *not* opened for `not_applicable` — the
    idempotency case — since no NEW PR is created there, only an existing
    one referenced). `main.invoke()` computes `pr_opened` at the call site
    for exactly this reason, mirroring the sibling agent's own
    `determine_outcome()`, which likewise takes `pr_existed` as a
    caller-supplied flag it does not compute internally rather than
    re-deriving it from a raw URL. Widening the tuple was the other
    documented option; a 3-tuple was chosen because it required zero changes
    to every already-merged `audit_only` call site/test (this story's
    explicit mandate: "keeps `audit_only`'s already-merged, already-tested
    behavior unchanged").

    A second, related deviation: spec §8.10's pseudocode checks
    `state.existing_pr_url` as the very FIRST statement in the function,
    before even computing `gated_findings` — implying idempotency is
    resolved before any mode branching. This function instead takes
    `pr_existed` as a plain bool, checked only within the `fix`/clean-gate
    branch (mirroring the sibling agent's own `determine_outcome()`, which
    also takes `pr_existed` as a narrow, call-site-supplied flag rather than
    a URL it resolves itself). `main.invoke()` only calls
    `pull_request.open_pr_if_needed()` — which performs the actual
    `existing_pr()` lookup — from within the `open_pr` step, itself only
    reached after a clean re-scan with mechanical findings present (spec
    §8.8's diagram: `rescan --> open_pr: gate clean` is the only edge into
    `open_pr`). Checking idempotency any earlier (e.g. before `scan`) is not
    supported by the state diagram and is not implemented.
    """
    if mode == "audit_only":
        gated_findings = _at_or_above_floor(findings, min_severity)
        if not gated_findings:
            return "succeeded", "no_findings", None
        if not fail_on_findings:
            return "succeeded", "needs_review", None
        return "failed", "needs_review", "AUDIT_FINDINGS"

    if mode == "fix":
        mechanical = mechanical_findings or []
        remainder = manual_or_unscannable_findings or []

        if not mechanical:
            gated_remainder = _at_or_above_floor(remainder, min_severity)
            outcome = "needs_review" if gated_remainder else "no_findings"
            return "succeeded", outcome, None

        if not rescan_clean:
            return "failed", "needs_review", "RESCAN_NOT_CLEAN"

        if pr_existed:
            return "succeeded", "not_applicable", None

        outcome = "partial" if remainder else "fixed"
        return "succeeded", outcome, None

    raise NotImplementedError(f"determine_outcome: mode={mode!r} is not a recognized mode")


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


def build_fix_audit_report(
    after_classified: list[tuple[MergedFinding, Bucket]],
    findings_before: dict,
    findings_after: dict,
) -> dict:
    """The fix-mode `audit_report` artifact (spec §6 "plus before/after counts
    in `fix` mode", PRD requirement 36 / user story 4).

    S-141 real-invocation finding: every fix-mode terminal path originally
    wrote no `audit_report` at all -- only the PR body (when a PR opened)
    carried the remaining findings. Two paths therefore left the operator
    blind to what "needs review": the nothing-mechanical no-op (requirement
    37 -- a real `fix` run against a repo whose only findings were Gitleaks
    `unscannable` ones terminated `succeeded`/`needs_review` with the two
    findings visible nowhere but a `metrics` count), and `RESCAN_NOT_CLEAN`,
    where requirement 36 says the after-scan's full result MUST be recorded
    as a `run_artifacts` row. Same grouping as `build_audit_report()` over
    the post-fix finding set, plus the before/after bucket counts.
    """
    return {
        **build_audit_report(after_classified),
        "findings_before": findings_before,
        "findings_after": findings_after,
    }


def _bucket_counts(classified: list[tuple[MergedFinding, Bucket]]) -> dict:
    """The `{"mechanical": n, "manual": n, "unscannable": n}` shape used for
    both `findings_before` and `findings_after` (requirement 47, story
    S-140). Reuses `build_audit_report()`'s own grouping rather than
    re-deriving it, discarding the `by_tool`/`by_severity` breakdown that
    shape also carries (not part of `findings_before`/`findings_after`'s own
    contract, spec S6.2)."""
    report = build_audit_report(classified)
    return {
        "mechanical": len(report["by_bucket"]["mechanical"]),
        "manual": len(report["by_bucket"]["manual"]),
        "unscannable": len(report["by_bucket"]["unscannable"]),
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
# Heartbeated scan (spec §9.2) — shared by the initial `scan` step and the
# `fix`-mode `rescan` step (story S-140) so both invocations of
# `run_scanners()` share one heartbeat-draining implementation rather than
# duplicating it.
# ---------------------------------------------------------------------------


async def _scan_with_heartbeat(workspace: str, scanners: list[str]):
    """Run `run_scanners()` in a worker thread under `run_with_heartbeat()`,
    yielding heartbeat chunks as they arrive and finally a `HeartbeatResult`
    carrying the scan results (or re-raising the underlying error). Callers
    drain this exactly like `run_with_heartbeat()` itself: `isinstance(item,
    HeartbeatResult)` marks the terminal item, everything else is a
    heartbeat chunk to `yield` straight through the entrypoint's own
    generator so the AgentCore response stream never goes idle (issue #98 /
    spec §9.2)."""

    def _do_scan():
        return run_scanners(Path(workspace), scanners, SCANNER_TIMEOUT)

    holder: dict = {}
    async for item in run_with_heartbeat(_do_scan, interval=HEARTBEAT_INTERVAL):
        if isinstance(item, HeartbeatResult):
            if item.error is not None:
                raise item.error
            holder["result"] = item.value
        elif is_heartbeat_chunk(item):
            yield item
    yield HeartbeatResult(value=holder["result"])


# ---------------------------------------------------------------------------
# Main orchestrator (spec S8.8, full state machine — story S-140)
# ---------------------------------------------------------------------------


@app.entrypoint
async def invoke(payload: dict, context):
    """
    Main invocation handler — pipeline orchestrator (spec §8.8's full state
    machine, both modes).

    `mode=audit_only` (S-135): resolve_credentials -> checkout -> scan ->
    classify -> `audit_report` artifact -> `determine_outcome()`.

    `mode=fix` (this story, S-140): resolve_credentials -> checkout -> scan
    -> classify -> fix (deterministic fixers, then the LLM escape hatch for
    findings they could not resolve) -> rescan -> open_pr (only reached on a
    clean re-scan gate — D23, no PR without one) -> `determine_outcome()`.
    `scan` and `rescan` are both wrapped in `heartbeat.run_with_heartbeat()`
    via `_scan_with_heartbeat()` (spec §8.8/§9.2 — CodeQL's database-build
    phase is the single most likely step to exceed the idle-session bound
    without it).
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

            # --- Step: scan — heartbeated, shared by both modes ---
            with run.step("scan"):
                scan_holder: dict = {}
                async for _item in _scan_with_heartbeat(workspace, params["scanners"]):
                    if isinstance(_item, HeartbeatResult):
                        scan_holder["result"] = _item.value
                    else:
                        yield _item
                scan_results = scan_holder["result"]

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

            # --- Step: classify — dedupe then classify, shared by both modes ---
            with run.step("classify"):
                all_findings = [f for r in scan_results for f in r.findings]
                merged = dedupe(all_findings)
                classified = [(m, classify(m)) for m in merged]

            findings_before = _bucket_counts(classified)

            if params["mode"] == "audit_only":
                # --- audit_report artifact (task 11.3) — full, unfiltered set ---
                audit_report = build_audit_report(classified)
                run.artifact("audit_report", title="Security scan findings", **audit_report)

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
                return

            # --- mode=fix (story S-140) ---
            mechanical = [m for m, b in classified if b == Bucket.MECHANICAL]
            manual_findings = [m for m, b in classified if b == Bucket.MANUAL]
            unscannable_findings = [m for m, b in classified if b == Bucket.UNSCANNABLE]
            remainder = manual_findings + unscannable_findings

            # --- Step: fix ---
            with run.step("fix"):
                if not mechanical:
                    # AC21 -- nothing mechanical to fix. `rescan`/`open_pr`
                    # are never entered (module docstring): there is nothing
                    # to re-verify and D23 permits no PR without a fix to
                    # verify in the first place.
                    fix_attempts_deterministic = 0
                    fix_attempts_llm = 0
                    llm_used = False
                    llm_fixed: list[MergedFinding] = []
                else:
                    semgrep_outcome = apply_semgrep_autofix(Path(workspace), mechanical)
                    trivy_outcome = apply_trivy_bump(Path(workspace), mechanical)
                    unresolved_deterministic = list(semgrep_outcome.unresolved) + list(
                        trivy_outcome.unresolved
                    )
                    fix_attempts_deterministic = len(mechanical)

                    # AC13 -- the LLM escape hatch is invoked ONLY for
                    # findings the deterministic fixers left unresolved, and
                    # ONLY when `max_fix_attempts > 0`. A finding fully
                    # resolved by the deterministic path never reaches this
                    # loop -- `run_fix_loop_for_finding` (and therefore
                    # `Agent(...)`/Bedrock) is never called for it, not
                    # merely called-and-immediately-successful. When
                    # `unresolved_deterministic` is empty (every mechanical
                    # finding resolved deterministically), this loop body
                    # never executes at all -- zero LLM invocations, so
                    # `fix_attempts_llm`/`llm_used` stay at their falsy
                    # defaults, matching AC13's `metrics.llm_used=false`.
                    llm_fixed = []
                    fix_attempts_llm = 0
                    if unresolved_deterministic and params["max_fix_attempts"] > 0:
                        for mf in unresolved_deterministic:
                            fix_attempts_llm += 1
                            fa_result = run_fix_loop_for_finding(
                                workspace, mf, params["max_fix_attempts"]
                            )
                            if fa_result.resolved:
                                llm_fixed.append(mf)
                    llm_used = fix_attempts_llm > 0

            if not mechanical:
                status, outcome, error_code = determine_outcome(
                    mode="fix",
                    findings=merged,
                    min_severity=params["min_severity"],
                    fail_on_findings=params["fail_on_findings"],
                    mechanical_findings=[],
                    manual_or_unscannable_findings=remainder,
                )
                result = build_return_payload(
                    status=status,
                    outcome=outcome,
                    error_code=error_code,
                    findings_before=findings_before,
                    findings_after=findings_before,
                    scanners_run=scanners_run,
                    scanners_skipped=scanners_skipped,
                    scanners_failed=scanners_failed,
                )
                # Nothing was fixed, so before == after; the remaining
                # manual/unscannable findings must still be visible somewhere
                # (user story 4) and there is no PR body to carry them.
                run.artifact(
                    "audit_report",
                    title="Security scan findings",
                    **build_fix_audit_report(classified, findings_before, findings_before),
                )
                # AC21's branch is always `succeeded` (spec §8.10) -- there is
                # no failure path when there was nothing mechanical to fix.
                run.succeed(outcome, metrics=build_metrics(result))
                yield terminal_chunk(json.dumps(result))
                return

            targeted_fingerprints = {fingerprint(mf.finding) for mf in mechanical}

            # --- Step: rescan — heartbeated, full re-scan against the same
            # scanner set as the initial scan (rescan.py's gate needs a
            # comprehensive before/after picture, not just the fixed files'
            # own tool, to catch an unrelated regression anywhere -- AC15).
            with run.step("rescan"):
                rescan_holder: dict = {}
                async for _item in _scan_with_heartbeat(workspace, params["scanners"]):
                    if isinstance(_item, HeartbeatResult):
                        rescan_holder["result"] = _item.value
                    else:
                        yield _item
                rescan_results = rescan_holder["result"]

                rescan_all_findings = [f for r in rescan_results for f in r.findings]
                after_merged = dedupe(rescan_all_findings)
                gate = rescan_gate(
                    before=merged, after=after_merged, targeted=targeted_fingerprints
                )
                if not gate.clean:
                    log.error(
                        "Re-scan gate not clean: still_present=%s unexplained_new=%s",
                        sorted(gate.still_present),
                        sorted(gate.unexplained_new),
                    )

            after_classified = [(m, classify(m)) for m in after_merged]
            findings_after = _bucket_counts(after_classified)

            if not gate.clean:
                # AC14/AC15 -- the re-scan gate blocks the PR even though the
                # working tree may carry a genuine local change (an
                # unresolved fix attempt, or the LLM's mandate-confined
                # edits): `open_pr` is never entered (spec §8.8's diagram
                # has no edge from a not-clean `rescan` into `open_pr`), so
                # no branch is ever created/pushed and no PR is ever opened.
                status, outcome, error_code = determine_outcome(
                    mode="fix",
                    findings=merged,
                    min_severity=params["min_severity"],
                    fail_on_findings=params["fail_on_findings"],
                    mechanical_findings=mechanical,
                    manual_or_unscannable_findings=remainder,
                    rescan_clean=False,
                )
                result = build_return_payload(
                    status=status,
                    outcome=outcome,
                    error_code=error_code,
                    findings_before=findings_before,
                    findings_after=findings_after,
                    scanners_run=scanners_run,
                    scanners_skipped=scanners_skipped,
                    scanners_failed=scanners_failed,
                    fix_attempts_deterministic=fix_attempts_deterministic,
                    fix_attempts_llm=fix_attempts_llm,
                    llm_used=llm_used,
                )
                # Requirement 36: the after-scan's full result MUST be
                # recorded so the operator can see exactly what remained.
                run.artifact(
                    "audit_report",
                    title="Security scan findings (after fix attempt, re-scan not clean)",
                    **build_fix_audit_report(after_classified, findings_before, findings_after),
                )
                assert error_code is not None
                run.fail(
                    error_code,
                    error_message=(
                        "re-scan gate not clean: "
                        f"still_present={sorted(gate.still_present)} "
                        f"unexplained_new={sorted(gate.unexplained_new)}"
                    ),
                    outcome=outcome,
                    metrics=build_metrics(result),
                )
                yield terminal_chunk(json.dumps(result))
                return

            # --- Step: open_pr — only reached on a clean re-scan gate (D23) ---
            # Spec §6: fix-mode audit_report carries before/after counts.
            # Written before open_pr so it exists even if PR creation fails.
            run.artifact(
                "audit_report",
                title="Security scan findings (after fix)",
                **build_fix_audit_report(after_classified, findings_before, findings_after),
            )

            with run.step("open_pr"):
                dependency_update_boundary = [
                    m
                    for m in manual_findings
                    if m.finding.remediation is not None
                    and m.finding.remediation.kind == "version_bump"
                    and m.finding.remediation.lockfile_managed
                ]
                major_version_guard = [
                    m
                    for m in manual_findings
                    if m.finding.remediation is not None
                    and m.finding.remediation.kind == "version_bump"
                    and not m.finding.remediation.lockfile_managed
                ]

                pr_state = PipelineState(
                    findings_before=len(merged),
                    fixed=list(mechanical),
                    manual_remaining=manual_findings,
                    unscannable_remaining=unscannable_findings,
                    dependency_update_boundary=dependency_update_boundary,
                    major_version_guard=major_version_guard,
                    llm_used=llm_used,
                    llm_fixed=llm_fixed,
                    rescan_before_count=len(merged),
                    rescan_after_count=len(after_merged),
                )
                pr_body = build_pr_body(pr_state)
                base_branch = payload.get("base_branch") or "main"
                pr_result = open_pr_if_needed(workspace, token_ctx.token, base_branch, pr_body)
                if pr_result.url:
                    # req 43 -- recorded regardless of new vs. existing.
                    run.artifact(
                        "pull_request",
                        url=pr_result.url,
                        title="fix(security): automated mechanical security fixes",
                        existed=pr_result.existed,
                        branch=pr_result.branch,
                    )
                log.info(
                    "open_pr: url=%s created=%s existed=%s",
                    pr_result.url,
                    pr_result.created,
                    pr_result.existed,
                )

            status, outcome, error_code = determine_outcome(
                mode="fix",
                findings=merged,
                min_severity=params["min_severity"],
                fail_on_findings=params["fail_on_findings"],
                mechanical_findings=mechanical,
                manual_or_unscannable_findings=remainder,
                rescan_clean=True,
                pr_existed=pr_result.existed,
            )
            result = build_return_payload(
                status=status,
                outcome=outcome,
                error_code=error_code,
                pr_url=pr_result.url,
                findings_before=findings_before,
                findings_after=findings_after,
                findings_fixed=len(mechanical),
                scanners_run=scanners_run,
                scanners_skipped=scanners_skipped,
                scanners_failed=scanners_failed,
                fix_attempts_deterministic=fix_attempts_deterministic,
                fix_attempts_llm=fix_attempts_llm,
                llm_used=llm_used,
            )
            # This branch's `determine_outcome()` calls are always
            # `succeeded` (spec §8.10's `fix` branch has no `status="failed"`
            # outcome once the gate is clean -- D23's whole point is that a
            # not-clean gate is caught upstream, above, before `open_pr` is
            # ever entered).
            run.succeed(outcome, metrics=build_metrics(result))
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

    except PullRequestError as exc:
        # A push/PR-create failure after the workspace changes are staged
        # and the re-scan gate already confirmed clean -- the fix itself
        # succeeded, only the PR handoff failed, so this maps to
        # needs_review (mirrors the sibling agent's identical PullRequestError
        # handling) rather than UNHANDLED_ERROR.
        log.error("Pull request error: %s", scrub(str(exc), secrets))
        result = build_return_payload("failed", "needs_review", exc.code)
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
