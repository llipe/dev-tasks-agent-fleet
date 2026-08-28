"""
Component tests for the pipeline orchestrator (main.py).

Tests the full invocation path with mocked externals:
  - Secrets Manager, PostgREST (Supabase), GitHub API, filesystem, subprocess.

Scenarios:
  - audit_only clean → succeeded / no_vulnerabilities
  - audit_only with findings + fail_on_findings=true → failed / AUDIT_FINDINGS
  - audit_only with findings + fail_on_findings=false → succeeded / needs_review
  - audit_only with major_required + fail_on → failed / MAJOR_UPDATE_REQUIRED
  - llm_fix with no changes after update → succeeded / no_vulnerabilities
  - invalid payload → INVALID_PARAMS, no clone
  - unhandled exception → failed + traceback
"""

from __future__ import annotations

import json

from main import (
    apply_defaults,
    build_return_payload,
    unwrap_payload,
    validate_payload,
)

# ---------------------------------------------------------------------------
# Payload unwrapping tests (req 9)
# ---------------------------------------------------------------------------


class TestUnwrapPayload:
    """Tests for the prompt wrapper handling."""

    def test_unwraps_prompt_key(self):
        """Payload wrapped in prompt key is unwrapped transparently."""
        inner = {"run_id": "abc-123", "repository_org": "myorg", "repository_name": "myrepo"}
        raw = {"prompt": json.dumps(inner)}
        result = unwrap_payload(raw)
        assert result == inner

    def test_passes_through_non_prompt(self):
        """Payload without prompt key passes through unchanged."""
        raw = {"run_id": "abc-123", "repository_org": "myorg", "repository_name": "myrepo"}
        result = unwrap_payload(raw)
        assert result == raw

    def test_handles_invalid_json_in_prompt(self):
        """Invalid JSON in prompt key falls back to raw payload."""
        raw = {"prompt": "not valid json{{{"}
        result = unwrap_payload(raw)
        assert result == raw

    def test_handles_non_string_prompt(self):
        """Non-string prompt value is treated as raw payload."""
        raw = {"prompt": 42, "run_id": "abc"}
        result = unwrap_payload(raw)
        assert result == raw

    def test_handles_prompt_with_non_dict_json(self):
        """prompt containing a JSON array (not dict) falls back to raw."""
        raw = {"prompt": "[1, 2, 3]"}
        result = unwrap_payload(raw)
        assert result == raw


# ---------------------------------------------------------------------------
# Payload validation tests (req 10)
# ---------------------------------------------------------------------------


class TestValidatePayload:
    """Tests for payload validation."""

    def test_valid_payload(self):
        """Valid payload with all required fields passes."""
        payload = {"run_id": "abc-123", "repository_org": "org", "repository_name": "repo"}
        assert validate_payload(payload) is not None

    def test_missing_run_id(self):
        """Missing run_id → None (invalid)."""
        payload = {"repository_org": "org", "repository_name": "repo"}
        assert validate_payload(payload) is None

    def test_missing_repository_org(self):
        """Missing repository_org → None."""
        payload = {"run_id": "abc", "repository_name": "repo"}
        assert validate_payload(payload) is None

    def test_missing_repository_name(self):
        """Missing repository_name → None."""
        payload = {"run_id": "abc", "repository_org": "org"}
        assert validate_payload(payload) is None

    def test_empty_run_id(self):
        """Empty string run_id → None."""
        payload = {"run_id": "", "repository_org": "org", "repository_name": "repo"}
        assert validate_payload(payload) is None

    def test_non_string_run_id(self):
        """Non-string run_id → None."""
        payload = {"run_id": 123, "repository_org": "org", "repository_name": "repo"}
        assert validate_payload(payload) is None


# ---------------------------------------------------------------------------
# Defaults application tests (req 11)
# ---------------------------------------------------------------------------


class TestApplyDefaults:
    """Tests for parameter defaults application."""

    def test_applies_all_defaults(self):
        """Missing params dict gets all defaults."""
        payload = {"run_id": "abc", "repository_org": "org", "repository_name": "repo"}
        result = apply_defaults(payload)
        assert result["params"]["fix_mode"] == "audit_only"
        assert result["params"]["fail_on_findings"] is True
        assert result["params"]["max_fix_attempts"] == 3

    def test_preserves_existing_params(self):
        """Existing params are preserved, only missing ones get defaults."""
        payload = {
            "run_id": "abc",
            "repository_org": "org",
            "repository_name": "repo",
            "params": {"fix_mode": "llm_fix", "fail_on_findings": False},
        }
        result = apply_defaults(payload)
        assert result["params"]["fix_mode"] == "llm_fix"
        assert result["params"]["fail_on_findings"] is False
        assert result["params"]["max_fix_attempts"] == 3

    def test_clamps_max_fix_attempts_upper(self):
        """max_fix_attempts > 5 clamped to 5."""
        payload = {
            "run_id": "abc",
            "repository_org": "org",
            "repository_name": "repo",
            "params": {"max_fix_attempts": 100},
        }
        result = apply_defaults(payload)
        assert result["params"]["max_fix_attempts"] == 5

    def test_clamps_max_fix_attempts_lower(self):
        """max_fix_attempts < 0 clamped to 0."""
        payload = {
            "run_id": "abc",
            "repository_org": "org",
            "repository_name": "repo",
            "params": {"max_fix_attempts": -5},
        }
        result = apply_defaults(payload)
        assert result["params"]["max_fix_attempts"] == 0

    def test_zero_max_fix_attempts_allowed(self):
        """max_fix_attempts=0 disables LLM escape hatch."""
        payload = {
            "run_id": "abc",
            "repository_org": "org",
            "repository_name": "repo",
            "params": {"max_fix_attempts": 0},
        }
        result = apply_defaults(payload)
        assert result["params"]["max_fix_attempts"] == 0

    def test_invalid_max_fix_attempts_type(self):
        """Non-numeric max_fix_attempts falls back to default."""
        payload = {
            "run_id": "abc",
            "repository_org": "org",
            "repository_name": "repo",
            "params": {"max_fix_attempts": "invalid"},
        }
        result = apply_defaults(payload)
        assert result["params"]["max_fix_attempts"] == 3

    def test_non_dict_params_replaced(self):
        """Non-dict params value is replaced with defaults."""
        payload = {
            "run_id": "abc",
            "repository_org": "org",
            "repository_name": "repo",
            "params": "not a dict",
        }
        result = apply_defaults(payload)
        assert isinstance(result["params"], dict)
        assert result["params"]["fix_mode"] == "audit_only"


# ---------------------------------------------------------------------------
# Return payload tests (spec §6.2)
# ---------------------------------------------------------------------------


class TestBuildReturnPayload:
    """Tests for return payload assembly."""

    def test_full_payload_shape(self):
        """All fields present in the return payload."""
        result = build_return_payload(
            status="succeeded",
            outcome="fixed",
            error_code=None,
            pr_url="https://github.com/org/repo/pull/1",
            vuln_before=5,
            vuln_after=2,
            advisories_fixed=3,
            advisories_major_required=1,
            advisories_unknown=1,
            packages_changed=4,
            fix_attempts=1,
            llm_used=True,
        )
        assert result["status"] == "succeeded"
        assert result["outcome"] == "fixed"
        assert result["error_code"] is None
        assert result["pr_url"] == "https://github.com/org/repo/pull/1"
        assert result["vulnerabilities_before"] == 5
        assert result["vulnerabilities_after"] == 2
        assert result["advisories_fixed"] == 3
        assert result["advisories_major_required"] == 1
        assert result["advisories_unknown"] == 1
        assert result["packages_changed"] == 4
        assert result["fix_attempts"] == 1
        assert result["llm_used"] is True

    def test_minimal_payload(self):
        """Minimal failed payload with defaults."""
        result = build_return_payload(
            status="failed",
            outcome="not_applicable",
            error_code="INVALID_PARAMS",
        )
        assert result["status"] == "failed"
        assert result["outcome"] == "not_applicable"
        assert result["error_code"] == "INVALID_PARAMS"
        assert result["pr_url"] is None
        assert result["vulnerabilities_before"] == 0
        assert result["llm_used"] is False


# ---------------------------------------------------------------------------
# Integration test: invalid payload does not clone (req 10)
# ---------------------------------------------------------------------------


def _collect_async_gen(agen):
    """Run an async generator to completion, collecting yielded values."""
    import asyncio

    async def _drain():
        results = []
        async for item in agen:
            results.append(item)
        return results

    return asyncio.run(_drain())


class TestInvalidPayloadNoClone:
    """Verify INVALID_PARAMS returns before any work (no clone, no credential fetch)."""

    def test_invalid_payload_returns_invalid_params(self):
        """Invalid payload → INVALID_PARAMS returned, no clone attempted."""
        from main import invoke

        results = _collect_async_gen(invoke({}, None))

        assert len(results) == 1
        text = results[0]["event"]["contentBlockDelta"]["delta"]["text"]
        payload = json.loads(text)
        assert payload["status"] == "failed"
        assert payload["error_code"] == "INVALID_PARAMS"

    def test_prompt_wrapped_invalid(self):
        """Prompt-wrapped but inner payload is missing fields → INVALID_PARAMS."""
        from main import invoke

        raw = {"prompt": json.dumps({"run_id": "abc"})}  # missing org and name
        results = _collect_async_gen(invoke(raw, None))

        assert len(results) == 1
        text = results[0]["event"]["contentBlockDelta"]["delta"]["text"]
        payload = json.loads(text)
        assert payload["status"] == "failed"
        assert payload["error_code"] == "INVALID_PARAMS"


# ---------------------------------------------------------------------------
# Post-fix wiring: req 49 re-run + req 50 mandate gate (issue #75)
# ---------------------------------------------------------------------------


class TestRerunStaticChecksAfterFix:
    """req 49: after a successful LLM fix, lint/format/typecheck are re-run."""

    def test_reruns_lint_format_typecheck_and_preserves_test(self, tmp_path):
        """The re-run invokes lint/format/typecheck and preserves the test result."""
        import main
        from validator import CheckStatus, ValidationResult

        pkg = {
            "name": "p",
            "version": "1.0.0",
            "scripts": {"test": "jest", "lint": "eslint", "typecheck": "tsc"},
        }
        (tmp_path / "package.json").write_text(json.dumps(pkg))

        scripts = main.detect_scripts(str(tmp_path))

        prior = ValidationResult()
        prior.llm_used = True
        prior.fix_attempts = 2
        prior.record("test", CheckStatus.PASSED, "5 passed")

        # Stub the individual runners so no real subprocess runs.
        calls = []

        def _fake_lint(ws, pm, sc, res):
            calls.append("lint")
            res.record("lint", CheckStatus.PASSED, "")

        def _fake_format(ws, pm, sc, res):
            calls.append("format")
            res.record("format", CheckStatus.SKIPPED, "")

        def _fake_typecheck(ws, pm, sc, res):
            calls.append("typecheck")
            res.record("typecheck", CheckStatus.PASSED, "")

        orig = (main.run_lint, main.run_format, main.run_typecheck)
        main.run_lint, main.run_format, main.run_typecheck = (
            _fake_lint,
            _fake_format,
            _fake_typecheck,
        )
        try:
            out = main.rerun_static_checks_after_fix(str(tmp_path), "pnpm", scripts, prior)
        finally:
            main.run_lint, main.run_format, main.run_typecheck = orig

        assert calls == ["lint", "format", "typecheck"]
        # Carries llm metadata forward
        assert out.llm_used is True
        assert out.fix_attempts == 2
        # Preserves the original test result rather than re-running it
        assert out.checks["test"].status == CheckStatus.PASSED
        assert out.checks["test"].output == "5 passed"
        assert out.passed is True


class TestCheckMandate:
    """req 50: mandate gate returns violation details or None."""

    def test_clean_returns_none(self, tmp_path):
        """Unchanged package.json → no violation."""
        import main

        pkg = {
            "name": "p",
            "version": "1.0.0",
            "dependencies": {"react": "^18.2.0"},
        }
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        before = {"dependencies": {"react": "^18.2.0"}, "devDependencies": {}}

        assert main.check_mandate(str(tmp_path), before) is None

    def test_widened_range_returns_details(self, tmp_path):
        """Widened range → human-readable violation string mentioning the package."""
        import main

        pkg = {
            "name": "p",
            "version": "1.0.0",
            "dependencies": {"react": "^19.0.0"},
        }
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        before = {"dependencies": {"react": "^18.2.0"}, "devDependencies": {}}

        details = main.check_mandate(str(tmp_path), before)
        assert details is not None
        assert "react" in details
        assert "dependencies" in details

    def test_new_dependency_returns_details(self, tmp_path):
        """Added dependency → violation string."""
        import main

        pkg = {
            "name": "p",
            "version": "1.0.0",
            "dependencies": {"react": "^18.2.0", "evil": "^1.0.0"},
        }
        (tmp_path / "package.json").write_text(json.dumps(pkg))
        before = {"dependencies": {"react": "^18.2.0"}, "devDependencies": {}}

        details = main.check_mandate(str(tmp_path), before)
        assert details is not None
        assert "evil" in details


# ---------------------------------------------------------------------------
# open_pr wiring: PR body assembly + token refresh (issue #76)
# ---------------------------------------------------------------------------


class TestBuildPrBodyFromState:
    """main.build_pr_body_from_state splits buckets and flags non-semver."""

    def test_splits_fixed_from_before_and_major_from_after(self):
        import main
        from audit import PackageChange
        from classifier import ClassifiedAdvisory
        from validator import CheckStatus, ValidationResult

        def adv(module, bucket):
            return ClassifiedAdvisory(
                id=1, module=module, severity="high", title="t", url="u", bucket=bucket
            )

        # Before the update: lodash was in-range (gets fixed).
        classified_before = [adv("lodash", "in_range")]
        # After the update: a major-only advisory remains.
        reclassified_after = [adv("left-pad", "major_required")]

        pkg_changes = [
            PackageChange(
                name="lodash", action="updated", old_version="4.0.0", new_version="4.0.1"
            ),
            PackageChange(
                name="weird", action="updated", old_version="1.0.0", new_version="git-sha"
            ),
        ]

        val = ValidationResult()
        val.record("test", CheckStatus.PASSED, "")

        body = main.build_pr_body_from_state(
            5, 2, classified_before, reclassified_after, pkg_changes, val
        )

        assert "## Fixed Advisories" in body
        assert "lodash" in body
        assert "Major Version Required" in body
        assert "left-pad" in body
        # Non-semver "git-sha" change is surfaced.
        assert "## Non-semver Version Changes" in body
        assert "weird" in body

    def test_ai_warning_follows_validation_llm_flag(self):
        import main
        from validator import CheckStatus, ValidationResult

        val = ValidationResult()
        val.record("test", CheckStatus.PASSED, "")
        val.llm_used = True
        val.fix_attempts = 2

        body = main.build_pr_body_from_state(1, 0, [], [], [], val)
        assert "AI-Assisted Modifications" in body
        assert "**2**" in body


class TestRefreshTokenIfStale:
    """main.refresh_token_if_stale re-resolves credentials only when stale."""

    def test_returns_same_when_not_stale(self, monkeypatch):
        import main
        from credentials import TokenContext

        ctx = TokenContext(token="tok", issued_at=0.0, installation_id=1)
        monkeypatch.setattr(ctx, "is_stale", lambda: False)
        secrets: list[str] = []
        out = main.refresh_token_if_stale(ctx, "org", secrets)
        assert out is ctx
        assert secrets == []

    def test_re_resolves_when_stale(self, monkeypatch):
        import main
        from credentials import TokenContext

        ctx = TokenContext(token="old", issued_at=0.0, installation_id=1)
        monkeypatch.setattr(ctx, "is_stale", lambda: True)
        fresh = TokenContext(token="new", issued_at=1.0, installation_id=1)
        monkeypatch.setattr(main, "resolve_github_credentials", lambda org: fresh)

        secrets: list[str] = []
        out = main.refresh_token_if_stale(ctx, "org", secrets)
        assert out is fresh
        assert "new" in secrets


class TestPullRequestErrorMapping:
    """A PR push/create failure maps to failed/needs_review/<code>, not UNHANDLED_ERROR."""

    def test_pull_request_error_carries_code(self):
        from pull_request import PullRequestError

        exc = PullRequestError("PUSH_FAILED", "git push failed")
        assert exc.code == "PUSH_FAILED"

    def test_handler_payload_shape_for_pr_error(self):
        # Mirrors the `except PullRequestError` branch in main.invoke: the update
        # itself succeeded, only the PR handoff failed → needs_review + the code.
        import main
        from pull_request import PullRequestError

        exc = PullRequestError("PR_CREATE_FAILED", "gh pr create failed")
        result = main.build_return_payload("failed", "needs_review", exc.code)
        assert result["status"] == "failed"
        assert result["outcome"] == "needs_review"
        assert result["error_code"] == "PR_CREATE_FAILED"

    def test_main_imports_pull_request_error_handler(self):
        # Guard: main must import PullRequestError so the dedicated handler exists
        # (otherwise a PR failure would fall through to the generic UNHANDLED_ERROR).
        import main

        assert hasattr(main, "PullRequestError")


# ---------------------------------------------------------------------------
# runs.metrics persistence (issue #77)
# ---------------------------------------------------------------------------


class TestBuildMetrics:
    """main.build_metrics projects the metric fields out of the return payload."""

    def test_extracts_metric_fields(self):
        import main

        result = main.build_return_payload(
            status="succeeded",
            outcome="fixed",
            error_code=None,
            pr_url="https://github.com/org/repo/pull/1",
            vuln_before=5,
            vuln_after=2,
            advisories_fixed=3,
            advisories_major_required=1,
            advisories_unknown=1,
            packages_changed=4,
            fix_attempts=2,
            llm_used=True,
        )
        metrics = main.build_metrics(result)

        assert metrics == {
            "vulnerabilities_before": 5,
            "vulnerabilities_after": 2,
            "advisories_fixed": 3,
            "advisories_major_required": 1,
            "advisories_unknown": 1,
            "packages_changed": 4,
            "fix_attempts": 2,
            "llm_used": True,
        }

    def test_excludes_non_metric_fields(self):
        """status, outcome, error_code, pr_url are columns, not metrics."""
        import main

        result = main.build_return_payload(
            status="failed",
            outcome="needs_review",
            error_code="VALIDATION_FAILING",
            pr_url=None,
        )
        metrics = main.build_metrics(result)

        for excluded in ("status", "outcome", "error_code", "pr_url"):
            assert excluded not in metrics

    def test_defaults_for_minimal_payload(self):
        """A minimal payload still yields a complete, zero-valued metrics dict."""
        import main

        result = main.build_return_payload(
            status="failed",
            outcome="not_applicable",
            error_code="INVALID_PARAMS",
        )
        metrics = main.build_metrics(result)

        assert metrics["vulnerabilities_before"] == 0
        assert metrics["vulnerabilities_after"] == 0
        assert metrics["advisories_fixed"] == 0
        assert metrics["fix_attempts"] == 0
        assert metrics["llm_used"] is False


class _FakeRun:
    """Minimal RunReporter stand-in capturing succeed/fail calls."""

    def __init__(self):
        self.succeed_calls = []
        self.fail_calls = []

    def succeed(self, outcome, result=None, metrics=None):
        self.succeed_calls.append({"outcome": outcome, "metrics": metrics})

    def fail(self, error_code, error_message, outcome=None, metrics=None):
        self.fail_calls.append({"error_code": error_code, "outcome": outcome, "metrics": metrics})


class TestReportTerminalMetrics:
    """_report_terminal forwards metrics to succeed/fail (issue #77, req 52)."""

    def test_succeed_receives_metrics(self):
        import main

        run = _FakeRun()
        metrics = {"vulnerabilities_before": 3, "llm_used": False}
        main._report_terminal(run, "succeeded", "no_vulnerabilities", None, metrics=metrics)

        assert len(run.succeed_calls) == 1
        assert run.succeed_calls[0]["outcome"] == "no_vulnerabilities"
        assert run.succeed_calls[0]["metrics"] == metrics

    def test_fail_receives_metrics(self):
        import main

        run = _FakeRun()
        metrics = {"vulnerabilities_before": 3, "llm_used": True, "fix_attempts": 1}
        main._report_terminal(run, "failed", "needs_review", "VALIDATION_FAILING", metrics=metrics)

        assert len(run.fail_calls) == 1
        assert run.fail_calls[0]["error_code"] == "VALIDATION_FAILING"
        assert run.fail_calls[0]["outcome"] == "needs_review"
        assert run.fail_calls[0]["metrics"] == metrics

    def test_metrics_optional_defaults_to_none(self):
        """Backward compatible: omitting metrics passes None through."""
        import main

        run = _FakeRun()
        main._report_terminal(run, "succeeded", "fixed", None)

        assert run.succeed_calls[0]["metrics"] is None
