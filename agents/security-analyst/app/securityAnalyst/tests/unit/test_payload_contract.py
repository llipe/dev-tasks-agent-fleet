"""
Unit tests for main.py's payload unwrap/validate/apply_defaults contract
(spec S6.1, PRD AC28).

Identical unwrap/validate shape to the sibling agent (`main.py:74-186`
pattern) — tolerant of `prompt`-wrapping up to `_MAX_UNWRAP_DEPTH = 16`,
`_REQUIRED_FIELDS = {"run_id", "repository_org", "repository_name"}` — plus
this agent's own additions: `scanners` list validation and the `min_severity`
enum (PRD S7.4b / D31, req 64).
"""

from __future__ import annotations

import json

import pytest

from main import (
    InvalidParamsError,
    apply_defaults,
    unwrap_payload,
    validate_payload,
)

_VALID_PAYLOAD = {
    "run_id": "11111111-1111-1111-1111-111111111111",
    "repository_org": "my-org",
    "repository_name": "checkout-api",
}


# ---------------------------------------------------------------------------
# unwrap_payload
# ---------------------------------------------------------------------------


class TestUnwrapPayload:
    def test_passthrough_when_not_wrapped(self):
        assert unwrap_payload(dict(_VALID_PAYLOAD)) == _VALID_PAYLOAD

    def test_single_prompt_wrap_is_unwrapped(self):
        wrapped = {"prompt": json.dumps(_VALID_PAYLOAD)}
        assert unwrap_payload(wrapped) == _VALID_PAYLOAD

    def test_double_prompt_wrap_is_unwrapped(self):
        # agentcore CLI >= 0.28.0 double-wrap shape.
        inner = json.dumps(_VALID_PAYLOAD)
        once = json.dumps({"prompt": inner})
        double = {"prompt": once}
        assert unwrap_payload(double) == _VALID_PAYLOAD

    def test_payload_with_sibling_keys_is_not_unwrapped(self):
        # A dict with `prompt` plus sibling keys is not a lone-wrapper.
        payload = {"prompt": "ignored", "run_id": "x"}
        assert unwrap_payload(payload) == payload

    def test_non_json_prompt_string_returns_unchanged(self):
        payload = {"prompt": "not json"}
        assert unwrap_payload(payload) == payload

    def test_prompt_wrapping_a_non_dict_returns_unchanged(self):
        payload = {"prompt": json.dumps([1, 2, 3])}
        assert unwrap_payload(payload) == payload

    def test_unwrap_depth_is_bounded(self):
        # A pathological lone-prompt chain must terminate, not hang.
        current = json.dumps(_VALID_PAYLOAD)
        for _ in range(20):
            current = json.dumps({"prompt": current})
        result = unwrap_payload(json.loads(current))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# validate_payload
# ---------------------------------------------------------------------------


class TestValidatePayload:
    def test_valid_payload_passes(self):
        validate_payload(dict(_VALID_PAYLOAD))  # must not raise

    def test_missing_run_id_raises(self):
        payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "run_id"}
        with pytest.raises(InvalidParamsError):
            validate_payload(payload)

    def test_missing_repository_org_raises(self):
        payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "repository_org"}
        with pytest.raises(InvalidParamsError):
            validate_payload(payload)

    def test_missing_repository_name_raises(self):
        payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "repository_name"}
        with pytest.raises(InvalidParamsError):
            validate_payload(payload)

    def test_unknown_mode_raises(self):
        payload = {**_VALID_PAYLOAD, "params": {"mode": "not_a_mode"}}
        with pytest.raises(InvalidParamsError):
            validate_payload(payload)

    def test_valid_modes_pass(self):
        for mode in ("audit_only", "fix"):
            validate_payload({**_VALID_PAYLOAD, "params": {"mode": mode}})

    def test_empty_scanners_list_raises(self):
        payload = {**_VALID_PAYLOAD, "params": {"scanners": []}}
        with pytest.raises(InvalidParamsError):
            validate_payload(payload)

    def test_unknown_scanner_raises(self):
        payload = {**_VALID_PAYLOAD, "params": {"scanners": ["semgrep", "not_a_scanner"]}}
        with pytest.raises(InvalidParamsError):
            validate_payload(payload)

    def test_all_five_valid_scanners_pass(self):
        payload = {
            **_VALID_PAYLOAD,
            "params": {"scanners": ["semgrep", "gitleaks", "trivy", "checkov", "codeql"]},
        }
        validate_payload(payload)

    def test_unknown_min_severity_raises(self):
        payload = {**_VALID_PAYLOAD, "params": {"min_severity": "extreme"}}
        with pytest.raises(InvalidParamsError):
            validate_payload(payload)

    def test_valid_min_severities_pass(self):
        for sev in ("low", "medium", "high", "critical"):
            validate_payload({**_VALID_PAYLOAD, "params": {"min_severity": sev}})

    def test_missing_params_uses_defaults_and_passes(self):
        validate_payload(dict(_VALID_PAYLOAD))  # no `params` key at all


# ---------------------------------------------------------------------------
# apply_defaults
# ---------------------------------------------------------------------------


class TestApplyDefaults:
    def test_defaults_applied_when_params_absent(self):
        result = apply_defaults({})
        assert result["mode"] == "audit_only"
        assert result["fail_on_findings"] is True
        assert result["min_severity"] == "low"
        assert result["max_fix_attempts"] == 3
        assert result["scanners"] == sorted(["semgrep", "gitleaks", "trivy", "checkov", "codeql"])

    def test_explicit_values_are_preserved(self):
        params = {
            "mode": "fix",
            "fail_on_findings": False,
            "min_severity": "high",
            "max_fix_attempts": 2,
            "scanners": ["semgrep"],
        }
        result = apply_defaults(params)
        assert result == params

    def test_max_fix_attempts_clamped_to_ceiling(self):
        result = apply_defaults({"max_fix_attempts": 99})
        assert result["max_fix_attempts"] == 5

    def test_max_fix_attempts_clamped_to_floor(self):
        result = apply_defaults({"max_fix_attempts": -3})
        assert result["max_fix_attempts"] == 0

    def test_min_severity_default_is_additive(self):
        # req 64: min_severity default must not disturb other explicit params.
        result = apply_defaults({"mode": "fix"})
        assert result["mode"] == "fix"
        assert result["min_severity"] == "low"
