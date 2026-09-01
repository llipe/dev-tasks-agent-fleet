"""
dependency-update agent — pipeline orchestrator entrypoint.

Receives invocation payloads via AgentCore HTTP protocol, runs a deterministic
audit-classify-update-validate-PR pipeline with an optional bounded LLM fix loop.

Step keys (req 61):
    resolve_credentials, checkout, detect_toolchain, install, audit,
    update, validate, llm_fix, open_pr
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import traceback

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from agent_reporter import RunReporter
from audit import (
    AuditResult,
    count_advisories_fixed,
    diff_packages,
    run_audit,
    snapshot_lockfile_packages,
)
from classifier import ClassifiedAdvisory, classify_advisory
from config import (
    DEFAULT_FAIL_ON_FINDINGS,
    DEFAULT_FIX_MODE,
    DEFAULT_MAX_FIX_ATTEMPTS,
    HEARTBEAT_INTERVAL,
    MAX_FIX_ATTEMPTS_CEILING,
    SUPABASE_URL,
    assert_clock_invariant,
)
from credentials import CredentialError, fetch_supabase_key, resolve_github_credentials
from fix_agent import _read_pkg_dependencies, run_fix_loop, verify_no_mandate_violation
from heartbeat import (
    HeartbeatResult,
    is_heartbeat_chunk,
    run_with_heartbeat,
    terminal_chunk,
)
from pull_request import PullRequestError, build_pr_body, open_pr_if_needed
from scrubber import scrub, scrub_process_error
from signal_backstop import install_termination_backstop
from toolchain import (
    ToolchainError,
    detect_package_manager,
    detect_scripts,
    ensure_pnpm_version,
)
from updater import UpdaterError, has_changes, install_deps, reconcile_lockfile, update_packages
from validator import (
    ValidationResult,
    run_format,
    run_lint,
    run_typecheck,
    run_validation,
)

app = BedrockAgentCoreApp()
log = app.logger

# ---------------------------------------------------------------------------
# Payload unwrapping and validation (req 9, 10)
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = ("run_id", "repository_org", "repository_name")

# Max nested ``prompt`` layers to strip. One layer is the historical control-plane
# form; two layers is the agentcore CLI >= 0.28.0 double-wrap (issue #97). The
# bound is a defensive guard against a pathological lone-``prompt`` chain — real
# payloads never approach it.
_MAX_UNWRAP_DEPTH = 16


def unwrap_payload(raw: dict) -> dict:
    """
    Handle the AgentCore ``prompt`` wrapper (req 9).

    AgentCore CLI/SDK wraps the JSON payload inside a ``prompt`` key as a JSON
    string. Historically this was a single wrap, so the pipeline received the
    inner payload after one unwrap.

    As of ``agentcore`` CLI >= 0.28.0 the CLI treats its invoke argument *as*
    the prompt and wraps it itself. An already-wrapped argument therefore
    arrives **double-wrapped** (``{"prompt": "{\\"prompt\\": \\"{...}\\"}"}``).
    To tolerate both conventions we unwrap **repeatedly**: keep unwrapping while
    the current value is a dict whose *only* key is ``prompt`` and whose string
    value parses to a JSON dict. See issue #97.

    Termination and safety (BR-1): the loop stops on any dict that is not a
    lone-``prompt`` wrapper (so a legitimate inner payload carrying its own
    ``prompt`` field or sibling keys is never over-unwrapped), on a non-string
    ``prompt`` value, and on a ``prompt`` string that does not parse to a JSON
    dict (invalid JSON, arrays, scalars) — in every case the current value is
    returned unchanged. Always returns a ``dict``.
    """
    current = raw
    # Bound the loop defensively; real payloads are wrapped at most a couple of
    # times, and each iteration must strip exactly one lone-``prompt`` layer.
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
    """True when ``payload`` is a dict whose only key is a string ``prompt``.

    This is the shape produced by an AgentCore prompt wrapper. A dict with
    ``prompt`` plus sibling keys is *not* a wrapper (EC-10), so it is left
    untouched by :func:`unwrap_payload`.
    """
    return (
        isinstance(payload, dict)
        and list(payload.keys()) == ["prompt"]
        and isinstance(payload["prompt"], str)
    )


def classify_invalid_payload(payload: str | dict) -> str:
    """Classify why a post-unwrap payload failed validation (issue #97, AC-3).

    Returns ``"wrapper_only"`` when the payload's only key is ``prompt`` — the
    tell-tale of a still-wrapped (e.g. double-wrapped) payload that could not be
    unwrapped to real fields — otherwise ``"missing_fields"``. Pure and
    importable so the distinction is testable without the coverage-excluded
    entrypoint.
    """
    if isinstance(payload, dict) and list(payload.keys()) == ["prompt"]:
        return "wrapper_only"
    return "missing_fields"


def validate_payload(payload: dict) -> dict | None:
    """
    Validate the payload against the expected schema (req 10).

    Returns the validated + defaults-applied payload, or None if invalid.
    On invalid payload, the error detail is returned as a string via the
    ``error`` key in the returned dict — caller should check before proceeding.
    """
    for field in _REQUIRED_FIELDS:
        if field not in payload or not isinstance(payload[field], str) or not payload[field]:
            return None
    return payload


def apply_defaults(payload: dict) -> dict:
    """
    Apply parameter defaults (req 11).

    Defaults: fix_mode=audit_only, fail_on_findings=true, max_fix_attempts=3.
    max_fix_attempts constrained to 0..5.
    """
    params = payload.get("params")
    if not isinstance(params, dict):
        params = {}

    params.setdefault("fix_mode", DEFAULT_FIX_MODE)
    params.setdefault("fail_on_findings", DEFAULT_FAIL_ON_FINDINGS)
    params.setdefault("max_fix_attempts", DEFAULT_MAX_FIX_ATTEMPTS)

    # Constrain max_fix_attempts to 0..5
    try:
        mfa = int(params["max_fix_attempts"])
    except (TypeError, ValueError):
        mfa = DEFAULT_MAX_FIX_ATTEMPTS
    params["max_fix_attempts"] = max(0, min(mfa, MAX_FIX_ATTEMPTS_CEILING))

    payload["params"] = params
    return payload


# ---------------------------------------------------------------------------
# Outcome determination — pure function (spec §8.1 table + precedence rules)
# ---------------------------------------------------------------------------


def determine_outcome(
    classified: list[ClassifiedAdvisory],
    params: dict,
    validation: ValidationResult | None,
    has_pr: bool,
    pr_existed: bool = False,
    has_working_changes: bool = True,
) -> tuple[str, str, str | None]:
    """
    Pure function: determine (status, outcome, error_code) from pipeline state.

    Precedence rules (req 42):
      1. VALIDATION_FAILING > MAJOR_UPDATE_REQUIRED > everything else.
      2. MAJOR_UPDATE_REQUIRED takes precedence over any succeeded outcome.
      3. In audit_only with fail_on_findings=false, always succeeded/needs_review
         regardless of major_required (req 42, third bullet).

    Parameters
    ----------
    classified : list of ClassifiedAdvisory after the relevant audit
    params : the validated params dict (fix_mode, fail_on_findings, max_fix_attempts)
    validation : ValidationResult or None (None in audit_only mode)
    has_pr : whether a new PR was opened in this run
    pr_existed : whether a PR already existed (idempotency short-circuit)
    has_working_changes : whether the update step produced changes
    """
    fix_mode = params.get("fix_mode", DEFAULT_FIX_MODE)
    fail_on_findings = params.get("fail_on_findings", DEFAULT_FAIL_ON_FINDINGS)

    has_major = any(a.bucket == "major_required" for a in classified)
    has_findings = len(classified) > 0

    # --- audit_only mode ---
    if fix_mode == "audit_only":
        if not has_findings:
            return "succeeded", "no_vulnerabilities", None
        if not fail_on_findings:
            # req 42 third bullet: always succeeded/needs_review regardless of major
            return "succeeded", "needs_review", None
        # fail_on_findings=true
        if has_major:
            return "failed", "needs_review", "MAJOR_UPDATE_REQUIRED"
        return "failed", "needs_review", "AUDIT_FINDINGS"

    # --- llm_fix mode ---

    # Validation failure takes highest precedence (req 42, first bullet)
    if validation is not None and not validation.passed:
        return "failed", "needs_review", "VALIDATION_FAILING"

    # No changes after update (D21)
    if not has_working_changes:
        if has_major:
            return "failed", "needs_review", "MAJOR_UPDATE_REQUIRED"
        return "succeeded", "no_vulnerabilities", None

    # PR already existed — idempotency
    if pr_existed:
        return "succeeded", "not_applicable", None

    # PR opened — check for remaining major_required
    if has_pr:
        if has_major:
            return "failed", "needs_review", "MAJOR_UPDATE_REQUIRED"
        # Determine if partial or fixed based on unknown bucket
        has_unknown = any(a.bucket == "unknown" for a in classified)
        if has_unknown:
            return "succeeded", "partial", None
        return "succeeded", "fixed", None

    # Fallback: no PR context — should not normally reach here
    return "succeeded", "no_vulnerabilities", None


# ---------------------------------------------------------------------------
# Post-fix re-validation and mandate gate (req 49, 50) — testable helpers
# ---------------------------------------------------------------------------


def rerun_static_checks_after_fix(
    workspace: str, pm: str, scripts, val_result: ValidationResult
) -> ValidationResult:
    """
    Re-run lint/format/typecheck after a successful LLM fix (req 49).

    The model may have touched source files after those checks last passed, so
    they are re-run. The original ``test`` result is preserved. ``llm_used`` and
    ``fix_attempts`` carry over. This is only meaningful when the fix succeeded
    (``val_result.passed and val_result.llm_used``); callers guard on that.
    """
    recheck = ValidationResult()
    recheck.llm_used = val_result.llm_used
    recheck.fix_attempts = val_result.fix_attempts
    run_lint(workspace, pm, scripts, recheck)
    run_format(workspace, pm, scripts, recheck)
    run_typecheck(workspace, pm, scripts, recheck)
    # Preserve the original test result
    if "test" in val_result.checks:
        recheck.checks["test"] = val_result.checks["test"]
    return recheck


def check_mandate(workspace: str, pkg_json_before: dict) -> str | None:
    """
    Run the package.json mandate check (req 50).

    Returns a human-readable violation-details string when the LLM widened a
    range, bumped a major, or added/removed a dependency; ``None`` when clean.
    A non-None result MUST terminate the run ``failed`` / ``needs_review`` /
    ``MANDATE_VIOLATION`` without opening a PR — this is the enforcement backstop
    for the prompt constraints (req 47).
    """
    violations = verify_no_mandate_violation(workspace, pkg_json_before)
    if not violations:
        return None
    return "; ".join(f"{v.package} ({v.field}): {v.reason}" for v in violations)


# ---------------------------------------------------------------------------
# Return payload assembly (spec §6.2)
# ---------------------------------------------------------------------------


def build_return_payload(
    status: str,
    outcome: str,
    error_code: str | None,
    pr_url: str | None = None,
    vuln_before: int = 0,
    vuln_after: int = 0,
    advisories_fixed: int = 0,
    advisories_major_required: int = 0,
    advisories_unknown: int = 0,
    packages_changed: int = 0,
    fix_attempts: int = 0,
    llm_used: bool = False,
) -> dict:
    """Assemble the structured return payload per spec §6.2."""
    return {
        "status": status,
        "outcome": outcome,
        "error_code": error_code,
        "pr_url": pr_url,
        "vulnerabilities_before": vuln_before,
        "vulnerabilities_after": vuln_after,
        "advisories_fixed": advisories_fixed,
        "advisories_major_required": advisories_major_required,
        "advisories_unknown": advisories_unknown,
        "packages_changed": packages_changed,
        "fix_attempts": fix_attempts,
        "llm_used": llm_used,
    }


# Metric fields persisted into the ``runs.metrics`` column (issue #77, req 52).
# status/outcome/error_code/pr_url are their own columns, not metrics.
_METRIC_FIELDS = (
    "vulnerabilities_before",
    "vulnerabilities_after",
    "advisories_fixed",
    "advisories_major_required",
    "advisories_unknown",
    "packages_changed",
    "fix_attempts",
    "llm_used",
)


def build_metrics(result: dict) -> dict:
    """
    Project the metric fields out of a return payload (issue #77, req 52).

    The pipeline already computes ``llm_used``, ``fix_attempts``, and the
    vulnerability / advisory / package counts for the entrypoint return payload.
    This helper selects exactly those fields so the same values are persisted
    into the ``runs.metrics`` jsonb column at termination, keeping the returned
    payload and the stored metrics in lockstep from a single source.
    """
    return {field: result[field] for field in _METRIC_FIELDS}


# ---------------------------------------------------------------------------
# Clone logic (req 12, 18)
# ---------------------------------------------------------------------------


def clone_repo(org: str, name: str, token: str, secrets: list[str]) -> str:
    """
    Clone the repository shallow (--depth 1) and scrub the token from .git/config.

    Returns the workspace path (temp directory).
    Clone URL is always derived (req 12): https://github.com/{org}/{name}.git
    """
    workspace = tempfile.mkdtemp(prefix=f"dep-update-{name}-")
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

    # Scrub token from .git/config (req 18)
    clean_url = f"https://github.com/{org}/{name}.git"
    subprocess.run(
        ["git", "remote", "set-url", "origin", clean_url],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )

    # Set git identity for commits
    subprocess.run(
        ["git", "config", "user.email", "agent@fleet.local"],
        cwd=workspace,
        capture_output=True,
        check=True,
        timeout=10,
    )
    subprocess.run(
        ["git", "config", "user.name", "dependency-update-agent"],
        cwd=workspace,
        capture_output=True,
        check=True,
        timeout=10,
    )

    return workspace


# ---------------------------------------------------------------------------
# Advisory classification helper
# ---------------------------------------------------------------------------


def classify_advisories(
    audit_result: AuditResult, workspace: str, pm: str
) -> list[ClassifiedAdvisory]:
    """Classify all advisories from an audit result using installed versions."""
    packages = snapshot_lockfile_packages(workspace, pm)
    classified: list[ClassifiedAdvisory] = []

    for adv in audit_result.advisories:
        module = adv.get("module_name", adv.get("name", "unknown"))
        installed_version = packages.get(module, "")
        classified.append(classify_advisory(adv, installed_version))

    return classified


# ---------------------------------------------------------------------------
# Reporter lifecycle helpers
# ---------------------------------------------------------------------------


def _report_terminal(
    run: RunReporter,
    status: str,
    outcome: str,
    error_code: str | None,
    metrics: dict | None = None,
) -> None:
    """Call run.succeed or run.fail with the correct argument signature."""
    if status == "succeeded":
        run.succeed(outcome, metrics=metrics)
    else:
        run.fail(
            error_code=error_code or "UNKNOWN",
            error_message=f"{outcome} ({error_code})",
            outcome=outcome,
            metrics=metrics,
        )


# ---------------------------------------------------------------------------
# Heartbeat keep-alive (issue #98)
# ---------------------------------------------------------------------------
#
# The reusable, unit-tested heartbeat logic lives in heartbeat.py. The
# entrypoint drives run_with_heartbeat inline (live-yielding heartbeat chunks as
# they occur) so the AgentCore response stream is never idle during a long
# blocking step. Nothing here touches the vendored agent_reporter.py (D13).


# ---------------------------------------------------------------------------
# Main orchestrator (spec §8.2)
# ---------------------------------------------------------------------------


@app.entrypoint
async def invoke(payload: dict, context):
    """
    Main invocation handler — deterministic pipeline orchestrator.

    Steps (req 61):
      resolve_credentials → checkout → detect_toolchain → install → audit →
      [update → validate → llm_fix → open_pr] (llm_fix mode only)
    """
    secrets: list[str] = []

    try:
        # Fail fast if the timeout clocks are inconsistent (issue #98, AC4):
        # a TEST_TIMEOUT above the container idle bound, or a heartbeat interval
        # at/above it, would let the container be reclaimed mid-step. Better to
        # refuse to start than to die silently at `validate`.
        assert_clock_invariant()

        # --- Unwrap and validate payload (req 9, 10) ---
        payload = unwrap_payload(payload)
        validated = validate_payload(payload)

        if validated is None:
            if classify_invalid_payload(payload) == "wrapper_only":
                # The payload's only key is still ``prompt`` after unwrapping —
                # the signature of a double-wrapped invocation (agentcore CLI
                # >= 0.28.0 wraps the prompt argument itself). See issue #97.
                log.error(
                    "Invalid payload — appears double-wrapped (only key is "
                    "'prompt' after unwrapping). Pass the bare inner JSON, not a "
                    "pre-wrapped '{\"prompt\": ...}' string; e.g. "
                    "`agentcore invoke --prompt-file <inner.json>`."
                )
            else:
                log.error("Invalid payload — missing required fields")
            result = build_return_payload("failed", "not_applicable", "INVALID_PARAMS")
            yield terminal_chunk(json.dumps(result))
            return

        payload = apply_defaults(validated)
        run_id = payload["run_id"]
        org = payload["repository_org"]
        name = payload["repository_name"]
        params = payload["params"]

        # --- Resolve Supabase key and init reporter (D24) ---
        supabase_key = fetch_supabase_key()
        secrets.append(supabase_key)
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = supabase_key
        os.environ["SUPABASE_URL"] = SUPABASE_URL
        os.environ["RUN_ID"] = run_id
        os.environ["RUN_PARAMS"] = json.dumps(payload)

        with RunReporter.from_env() as run:
            # Best-effort terminal-report backstop for an interceptable abrupt
            # stop (SIGTERM). A true SIGKILL/OOM cannot be intercepted — that
            # path is documented as reaper-only (issue #98, AC6).
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

            # --- Step: detect_toolchain ---
            with run.step("detect_toolchain"):
                pm = detect_package_manager(workspace)
                if pm == "pnpm":
                    ensure_pnpm_version(workspace)
                scripts = detect_scripts(workspace)
                log.info("Toolchain: pm=%s, scripts=%s", pm, scripts.test)

                # Emit warn events for absent optional scripts (req 23)
                for missing in scripts.missing_optional:
                    logging.getLogger(__name__).warning(
                        "Optional script '%s' not found — will be skipped", missing
                    )

            # --- Step: install ---
            with run.step("install"):
                install_deps(workspace, pm, frozen=True)
                log.info("Dependencies installed (frozen)")

            # --- Step: audit ---
            with run.step("audit"):
                audit_before = run_audit(workspace, pm)
                pkgs_before = snapshot_lockfile_packages(workspace, pm)
                classified = classify_advisories(audit_before, workspace, pm)

                # Emit error event per major_required advisory (req 40)
                for adv in classified:
                    if adv.bucket == "major_required":
                        logging.getLogger(__name__).error(
                            "Advisory %s (%s) requires major version bump: %s",
                            adv.id,
                            adv.module,
                            adv.title,
                        )

                # Emit summary event
                buckets = _bucket_counts(classified)
                log.info(
                    "Audit complete: %d total vulns, %d in_range, %d major_required, %d unknown",
                    audit_before.total_vulns,
                    buckets["in_range"],
                    buckets["major_required"],
                    buckets["unknown"],
                )

                # Record audit artifact. Metadata goes as explicit keyword args
                # because RunReporter.artifact collects it via **kwargs —
                # passing metadata={...} would yield metadata.metadata.* (#77).
                run.artifact(
                    "audit_report",
                    title="Audit Report",
                    total_vulns=audit_before.total_vulns,
                    vuln_counts=audit_before.vuln_counts,
                    in_range=buckets["in_range"],
                    major_required=buckets["major_required"],
                    unknown=buckets["unknown"],
                )

            # --- audit_only mode ---
            if params["fix_mode"] == "audit_only":
                status, outcome, error_code = determine_outcome(
                    classified, params, None, has_pr=False
                )
                result = build_return_payload(
                    status=status,
                    outcome=outcome,
                    error_code=error_code,
                    vuln_before=audit_before.total_vulns,
                    advisories_major_required=buckets["major_required"],
                    advisories_unknown=buckets["unknown"],
                )
                _report_terminal(run, status, outcome, error_code, metrics=build_metrics(result))
                yield terminal_chunk(json.dumps(result))
                return

            # --- llm_fix mode continues below ---

            # --- Step: update ---
            with run.step("update"):
                update_packages(workspace, pm)

                if not has_changes(workspace):
                    # No changes — determine outcome (D21)
                    status, outcome, error_code = determine_outcome(
                        classified,
                        params,
                        None,
                        has_pr=False,
                        has_working_changes=False,
                    )
                    result = build_return_payload(
                        status=status,
                        outcome=outcome,
                        error_code=error_code,
                        vuln_before=audit_before.total_vulns,
                        advisories_major_required=buckets["major_required"],
                        advisories_unknown=buckets["unknown"],
                    )
                    _report_terminal(
                        run, status, outcome, error_code, metrics=build_metrics(result)
                    )
                    yield terminal_chunk(json.dumps(result))
                    return

                # Reconcile lockfile (req 30)
                reconcile_lockfile(workspace, pm)

                # Re-audit after update
                audit_after = run_audit(workspace, pm)
                pkgs_after = snapshot_lockfile_packages(workspace, pm)
                reclassified = classify_advisories(audit_after, workspace, pm)
                pkg_changes = diff_packages(pkgs_before, pkgs_after)

                # Warn for non-semver changes
                from eligibility import parse_semver

                for change in pkg_changes:
                    if change.new_version and parse_semver(change.new_version) is None:
                        logging.getLogger(__name__).warning(
                            "Non-semver version change: %s %s → %s",
                            change.name,
                            change.old_version or "(new)",
                            change.new_version,
                        )

                log.info(
                    "Update applied: %d package version(s) changed "
                    "(working tree also has changes → proceeding to validate; "
                    "lockfile-only reconciliation shows 0 here). See issue #98 EC-9.",
                    len(pkg_changes),
                )

            # --- Step: validate ---
            # The longest blocking step: `pnpm test` on a large monorepo can run
            # for minutes. Run it in a worker thread and yield heartbeat chunks
            # live so the AgentCore response stream never goes idle and the
            # container is not reclaimed mid-step (issue #98, AC2).
            with run.step("validate"):
                _val_holder: dict = {}

                def _do_validation():
                    return run_validation(workspace, pm, scripts)

                async for _item in run_with_heartbeat(_do_validation, interval=HEARTBEAT_INTERVAL):
                    if isinstance(_item, HeartbeatResult):
                        if _item.error is not None:
                            raise _item.error
                        _val_holder["result"] = _item.value
                    elif is_heartbeat_chunk(_item):
                        yield _item
                val_result = _val_holder["result"]
                log.info("Validation: passed=%s", val_result.passed)

            # --- Step: llm_fix (only if validation failed and attempts > 0) ---
            # Snapshot package.json before fix agent for mandate check (req 50)
            pkg_json_before = _read_pkg_dependencies(os.path.join(workspace, "package.json"))

            if not val_result.passed and params["max_fix_attempts"] > 0:
                with run.step("llm_fix"):
                    log.info(
                        "Validation failed — invoking LLM fix agent (max_attempts=%d)",
                        params["max_fix_attempts"],
                    )
                    # The LLM fix loop is the longest step of all (multiple model
                    # calls + re-validation). Heartbeat it live too (issue #98,
                    # AC3).
                    _fix_holder: dict = {}

                    def _do_fix_loop():
                        return run_fix_loop(
                            workspace,
                            pm,
                            scripts,
                            params["max_fix_attempts"],
                            val_result,
                        )

                    async for _item in run_with_heartbeat(
                        _do_fix_loop, interval=HEARTBEAT_INTERVAL
                    ):
                        if isinstance(_item, HeartbeatResult):
                            if _item.error is not None:
                                raise _item.error
                            _fix_holder["result"] = _item.value
                        elif is_heartbeat_chunk(_item):
                            yield _item
                    val_result = _fix_holder["result"]

            # req 49: if fix succeeded, re-run lint/format/typecheck
            if val_result.passed and val_result.llm_used:
                log.info("Fix agent succeeded — re-running lint/format/typecheck")
                val_result = rerun_static_checks_after_fix(workspace, pm, scripts, val_result)

            # req 50: mandate check — package.json must be unchanged
            if val_result.llm_used:
                violation_details = check_mandate(workspace, pkg_json_before)
                if violation_details is not None:
                    log.error("Mandate violation detected: %s", violation_details)
                    result = build_return_payload(
                        status="failed",
                        outcome="needs_review",
                        error_code="MANDATE_VIOLATION",
                        vuln_before=audit_before.total_vulns,
                        vuln_after=audit_after.total_vulns,
                        packages_changed=len(pkg_changes),
                        fix_attempts=val_result.fix_attempts,
                        llm_used=True,
                        advisories_major_required=_bucket_counts(reclassified)["major_required"],
                        advisories_unknown=_bucket_counts(reclassified)["unknown"],
                    )
                    run.fail(
                        error_code="MANDATE_VIOLATION",
                        error_message=f"LLM modified package.json: {violation_details}",
                        outcome="needs_review",
                        metrics=build_metrics(result),
                    )
                    yield terminal_chunk(json.dumps(result))
                    return

            # Check validation after potential fix
            if not val_result.passed:
                status, outcome, error_code = determine_outcome(
                    reclassified, params, val_result, has_pr=False
                )
                result = build_return_payload(
                    status=status,
                    outcome=outcome,
                    error_code=error_code,
                    vuln_before=audit_before.total_vulns,
                    vuln_after=audit_after.total_vulns,
                    packages_changed=len(pkg_changes),
                    fix_attempts=val_result.fix_attempts,
                    llm_used=val_result.llm_used,
                    advisories_major_required=_bucket_counts(reclassified)["major_required"],
                    advisories_unknown=_bucket_counts(reclassified)["unknown"],
                )
                _report_terminal(run, status, outcome, error_code, metrics=build_metrics(result))
                yield terminal_chunk(json.dumps(result))
                return

            # --- Step: open_pr ---
            # Advisories actually resolved between the before/after audits
            # (issue #90): the ID-set diff drives BOTH the PR body Security
            # Summary and runs.metrics.advisories_fixed so they never disagree.
            fixed_count = count_advisories_fixed(audit_before.advisories, audit_after.advisories)

            # Snapshot the branch that update+fix produced, then open the PR
            # BEFORE evaluating MAJOR_UPDATE_REQUIRED so the reviewer always has
            # the fixed subset in hand even when a major bump remains (req 43).
            with run.step("open_pr"):
                # Refresh the installation token if it has aged past the
                # staleness threshold before we push (req 58).
                token_ctx = refresh_token_if_stale(token_ctx, org, secrets)

                pr_body = build_pr_body_from_state(
                    audit_before.total_vulns,
                    audit_after.total_vulns,
                    classified,
                    reclassified,
                    pkg_changes,
                    val_result,
                    advisories_fixed_count=fixed_count,
                )
                base_branch = payload.get("base_branch") or "main"
                pr_result = open_pr_if_needed(
                    workspace,
                    token_ctx.token,
                    base_branch,
                    pr_body,
                )
                pr_url = pr_result.url
                pr_existed = pr_result.existed
                has_new_pr = pr_result.created

                # Record the PR as an artifact regardless of new vs. existing (req 57).
                if pr_url:
                    run.artifact(
                        "pull_request",
                        url=pr_url,
                        title="Dependency Update PR",
                        existed=pr_existed,
                        branch=pr_result.branch,
                    )
                log.info(
                    "open_pr: url=%s created=%s existed=%s",
                    pr_url,
                    has_new_pr,
                    pr_existed,
                )

            # Final outcome determination
            status, outcome, error_code = determine_outcome(
                reclassified,
                params,
                val_result,
                has_pr=has_new_pr,
                pr_existed=pr_existed,
            )

            # Count fixed advisories: advisory IDs present before the update but
            # absent after it (issue #90). Computed above (before open_pr) so the
            # PR body and runs.metrics share one source of truth.
            result = build_return_payload(
                status=status,
                outcome=outcome,
                error_code=error_code,
                pr_url=pr_url,
                vuln_before=audit_before.total_vulns,
                vuln_after=audit_after.total_vulns,
                advisories_fixed=fixed_count,
                advisories_major_required=_bucket_counts(reclassified)["major_required"],
                advisories_unknown=_bucket_counts(reclassified)["unknown"],
                packages_changed=len(pkg_changes),
                fix_attempts=val_result.fix_attempts,
                llm_used=val_result.llm_used,
            )

            metrics = build_metrics(result)
            if status == "succeeded":
                run.succeed(outcome, metrics=metrics)
            else:
                _report_terminal(run, status, outcome, error_code, metrics=metrics)

            yield terminal_chunk(json.dumps(result))

    except CredentialError as exc:
        log.error("Credential error: %s", exc)
        result = build_return_payload("failed", "not_applicable", exc.code)
        yield {"event": {"contentBlockDelta": {"delta": {"text": json.dumps(result)}}}}

    except ToolchainError as exc:
        log.error("Toolchain error: %s", exc)
        result = build_return_payload("failed", "not_applicable", exc.code)
        yield {"event": {"contentBlockDelta": {"delta": {"text": json.dumps(result)}}}}

    except UpdaterError as exc:
        log.error("Updater error: %s", exc)
        result = build_return_payload("failed", "not_applicable", exc.code)
        yield {"event": {"contentBlockDelta": {"delta": {"text": json.dumps(result)}}}}

    except PullRequestError as exc:
        # A push/PR-create failure after the workspace changes are staged.
        # Map to the raised error_code and needs_review (the update itself
        # succeeded — only the PR handoff failed) rather than UNHANDLED_ERROR.
        log.error("Pull request error: %s", scrub(str(exc), secrets))
        result = build_return_payload("failed", "needs_review", exc.code)
        yield {"event": {"contentBlockDelta": {"delta": {"text": json.dumps(result)}}}}

    except Exception:
        # Unhandled exception — req 59: RunReporter context manager handles
        # marking the run failed + closing open steps. We still return a payload.
        tb = traceback.format_exc()
        log.error("Unhandled exception:\n%s", scrub(tb, secrets))
        result = build_return_payload("failed", "not_applicable", "UNHANDLED_ERROR")
        yield {"event": {"contentBlockDelta": {"delta": {"text": json.dumps(result)}}}}


# ---------------------------------------------------------------------------
# Token refresh + PR body assembly (issue #76)
# ---------------------------------------------------------------------------


def refresh_token_if_stale(token_ctx, org: str, secrets: list[str]):
    """
    Re-mint the GitHub installation token if it has aged past the threshold (req 58).

    ``resolve_github_credentials`` returns a :class:`TokenContext` without the PEM
    or app_id needed by ``credentials.refresh_if_stale``, so a stale token is
    refreshed by re-resolving credentials for the org (a fresh mint). The new
    token is appended to ``secrets`` so it is scrubbed from any later error path.
    """
    if not token_ctx.is_stale():
        return token_ctx
    log.info("Installation token stale (>45 min) — re-minting before push")
    new_ctx = resolve_github_credentials(org)
    secrets.append(new_ctx.token)
    return new_ctx


def _split_advisory_buckets(
    classified: list[ClassifiedAdvisory],
) -> tuple[list[ClassifiedAdvisory], list[ClassifiedAdvisory], list[ClassifiedAdvisory]]:
    """Split classified advisories into (fixed/in_range, major_required, unknown)."""
    fixed = [a for a in classified if a.bucket == "in_range"]
    major = [a for a in classified if a.bucket == "major_required"]
    unknown = [a for a in classified if a.bucket == "unknown"]
    return fixed, major, unknown


def build_pr_body_from_state(
    vuln_before: int,
    vuln_after: int,
    classified_before: list[ClassifiedAdvisory],
    reclassified_after: list[ClassifiedAdvisory],
    pkg_changes,
    val_result: ValidationResult,
    advisories_fixed_count: int | None = None,
) -> str:
    """
    Assemble the PR body from pipeline state (spec §8.9).

    - Fixed advisories: those that were in-range before the update (the update
      closed them) — listed in the "Fixed Advisories" table.
    - ``advisories_fixed_count``: the authoritative count shown in the Security
      Summary. When provided (issue #90), it is the audit ID-set diff and MUST
      match ``runs.metrics.advisories_fixed``. When ``None`` (older callers), it
      falls back to the length of the in-range table for backward compatibility.
    - Major-required / unknown: taken from the post-update reclassification —
      what still remains after the update lands.
    - Non-semver changes: package changes whose new version does not parse as
      semver (accepted but surfaced).
    """
    from eligibility import parse_semver

    fixed_before, _major_before, _unknown_before = _split_advisory_buckets(classified_before)
    _fixed_after, major_after, unknown_after = _split_advisory_buckets(reclassified_after)

    non_semver = [c for c in pkg_changes if c.new_version and parse_semver(c.new_version) is None]

    return build_pr_body(
        vuln_before=vuln_before,
        vuln_after=vuln_after,
        fixed_advisories=fixed_before,
        major_required=major_after,
        unknown_advisories=unknown_after,
        non_semver_changes=non_semver,
        upgraded=list(pkg_changes),
        validation=val_result,
        llm_used=val_result.llm_used,
        fix_attempts=val_result.fix_attempts,
        advisories_fixed_count=advisories_fixed_count,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bucket_counts(classified: list[ClassifiedAdvisory]) -> dict[str, int]:
    """Count advisories per bucket."""
    counts = {"in_range": 0, "major_required": 0, "unknown": 0}
    for adv in classified:
        if adv.bucket in counts:
            counts[adv.bucket] += 1
    return counts


if __name__ == "__main__":
    app.run()
