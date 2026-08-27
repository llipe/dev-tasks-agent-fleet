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
    diff_packages,
    run_audit,
    snapshot_lockfile_packages,
)
from classifier import ClassifiedAdvisory, classify_advisory
from config import (
    DEFAULT_FAIL_ON_FINDINGS,
    DEFAULT_FIX_MODE,
    DEFAULT_MAX_FIX_ATTEMPTS,
    MAX_FIX_ATTEMPTS_CEILING,
    SUPABASE_URL,
)
from credentials import CredentialError, fetch_supabase_key, resolve_github_credentials
from fix_agent import _read_pkg_dependencies, run_fix_loop, verify_no_mandate_violation
from scrubber import scrub, scrub_process_error
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


def unwrap_payload(raw: dict) -> dict:
    """
    Handle the AgentCore ``prompt`` wrapper (req 9).

    AgentCore CLI/SDK wraps the JSON payload inside a ``prompt`` key as a JSON
    string. Unwrap transparently so the rest of the pipeline sees the inner payload.
    """
    if "prompt" in raw and isinstance(raw["prompt"], str):
        try:
            inner = json.loads(raw["prompt"])
            if isinstance(inner, dict):
                return inner
        except (json.JSONDecodeError, TypeError):
            pass
    return raw


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


def _report_terminal(run: RunReporter, status: str, outcome: str, error_code: str | None) -> None:
    """Call run.succeed or run.fail with the correct argument signature."""
    if status == "succeeded":
        run.succeed(outcome)
    else:
        run.fail(
            error_code=error_code or "UNKNOWN",
            error_message=f"{outcome} ({error_code})",
            outcome=outcome,
        )


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
        # --- Unwrap and validate payload (req 9, 10) ---
        payload = unwrap_payload(payload)
        validated = validate_payload(payload)

        if validated is None:
            log.error("Invalid payload — missing required fields")
            result = build_return_payload("failed", "not_applicable", "INVALID_PARAMS")
            yield {"event": {"contentBlockDelta": {"delta": {"text": json.dumps(result)}}}}
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

                # Record audit artifact
                run.artifact(
                    "audit_report",
                    title="Audit Report",
                    metadata={
                        "total_vulns": audit_before.total_vulns,
                        "vuln_counts": audit_before.vuln_counts,
                        "in_range": buckets["in_range"],
                        "major_required": buckets["major_required"],
                        "unknown": buckets["unknown"],
                    },
                )

            # --- audit_only mode ---
            if params["fix_mode"] == "audit_only":
                status, outcome, error_code = determine_outcome(
                    classified, params, None, has_pr=False
                )
                _report_terminal(run, status, outcome, error_code)
                result = build_return_payload(
                    status=status,
                    outcome=outcome,
                    error_code=error_code,
                    vuln_before=audit_before.total_vulns,
                    advisories_major_required=buckets["major_required"],
                    advisories_unknown=buckets["unknown"],
                )
                yield {"event": {"contentBlockDelta": {"delta": {"text": json.dumps(result)}}}}
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
                    _report_terminal(run, status, outcome, error_code)
                    result = build_return_payload(
                        status=status,
                        outcome=outcome,
                        error_code=error_code,
                        vuln_before=audit_before.total_vulns,
                        advisories_major_required=buckets["major_required"],
                        advisories_unknown=buckets["unknown"],
                    )
                    yield {"event": {"contentBlockDelta": {"delta": {"text": json.dumps(result)}}}}
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
                    "Update applied: %d packages changed",
                    len(pkg_changes),
                )

            # --- Step: validate ---
            with run.step("validate"):
                val_result = run_validation(workspace, pm, scripts)
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
                    val_result = run_fix_loop(
                        workspace,
                        pm,
                        scripts,
                        params["max_fix_attempts"],
                        val_result,
                    )

            # req 49: if fix succeeded, re-run lint/format/typecheck
            if val_result.passed and val_result.llm_used:
                log.info("Fix agent succeeded — re-running lint/format/typecheck")
                recheck = ValidationResult()
                recheck.llm_used = val_result.llm_used
                recheck.fix_attempts = val_result.fix_attempts
                run_lint(workspace, pm, scripts, recheck)
                run_format(workspace, pm, scripts, recheck)
                run_typecheck(workspace, pm, scripts, recheck)
                # Preserve the original test result
                if "test" in val_result.checks:
                    recheck.checks["test"] = val_result.checks["test"]
                val_result = recheck

            # req 50: mandate check — package.json must be unchanged
            if val_result.llm_used:
                violations = verify_no_mandate_violation(workspace, pkg_json_before)
                if violations:
                    violation_details = "; ".join(
                        f"{v.package} ({v.field}): {v.reason}" for v in violations
                    )
                    log.error("Mandate violation detected: %s", violation_details)
                    run.fail(
                        error_code="MANDATE_VIOLATION",
                        error_message=f"LLM modified package.json: {violation_details}",
                        outcome="needs_review",
                    )
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
                    yield {"event": {"contentBlockDelta": {"delta": {"text": json.dumps(result)}}}}
                    return

            # Check validation after potential fix
            if not val_result.passed:
                status, outcome, error_code = determine_outcome(
                    reclassified, params, val_result, has_pr=False
                )
                _report_terminal(run, status, outcome, error_code)
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
                yield {"event": {"contentBlockDelta": {"delta": {"text": json.dumps(result)}}}}
                return

            # --- Step: open_pr ---
            with run.step("open_pr"):
                # PR creation is implemented in issue #76 — stub for now
                # When #76 is implemented, this becomes:
                # pr_url, pr_existed = open_pr_if_needed(workspace, token_ctx, ...)
                pr_url: str | None = None
                pr_existed = False
                has_new_pr = False
                log.info("PR creation step — not yet implemented (issue #76)")

            # Final outcome determination
            status, outcome, error_code = determine_outcome(
                reclassified,
                params,
                val_result,
                has_pr=has_new_pr,
                pr_existed=pr_existed,
            )

            if status == "succeeded":
                run.succeed(outcome)
            else:
                _report_terminal(run, status, outcome, error_code)

            # Count fixed advisories
            fixed_count = sum(1 for a in classified if a.bucket == "in_range") - sum(
                1 for a in reclassified if a.bucket == "in_range"
            )
            fixed_count = max(0, fixed_count)

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
            yield {"event": {"contentBlockDelta": {"delta": {"text": json.dumps(result)}}}}

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

    except Exception:
        # Unhandled exception — req 59: RunReporter context manager handles
        # marking the run failed + closing open steps. We still return a payload.
        tb = traceback.format_exc()
        log.error("Unhandled exception:\n%s", scrub(tb, secrets))
        result = build_return_payload("failed", "not_applicable", "UNHANDLED_ERROR")
        yield {"event": {"contentBlockDelta": {"delta": {"text": json.dumps(result)}}}}


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
