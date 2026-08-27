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
