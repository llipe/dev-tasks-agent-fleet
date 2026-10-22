"""
S-204 AC3 — invocation payload unwrap, validation, and defaults.

Covers TC-204-04..10, the Python side of CT-01 (shared params cases with the
panel's Ajv validator) and CT-03 (invocation payload shape). Spec §5.1 / §6.1,
D-21, D-35.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import main
from config import DEFAULT_PARAMS, PARAMS_SCHEMA
from main import InvalidParams, apply_defaults, unwrap_payload, validate_params, validate_payload

CASES_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "params_cases.json"

RUN_ID = "3f2b8c1e-5d4a-4f6b-9a7c-2e1d0b9a8c7f"


_DEFAULT = object()


def _payload(params: object = _DEFAULT, *, absent: bool = False, **overrides: object) -> dict:
    payload: dict = {
        "run_id": RUN_ID,
        "repository_org": "llipe",
        "repository_name": "dev-tasks-agent-fleet",
    }
    if not absent:
        payload["params"] = {"pr_number": 7} if params is _DEFAULT else params
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TC-204-04 — unwrap_payload
# ---------------------------------------------------------------------------


class TestUnwrap:
    def test_unwrapped_payload_passes_through(self):
        p = _payload()
        assert unwrap_payload(p) == p

    def test_single_prompt_wrapper_is_unwrapped(self):
        p = _payload()
        assert unwrap_payload({"prompt": json.dumps(p)}) == p

    def test_double_prompt_wrapper_is_unwrapped(self):
        p = _payload()
        wrapped = {"prompt": json.dumps({"prompt": json.dumps(p)})}
        assert unwrap_payload(wrapped) == p

    def test_prompt_that_is_not_json_is_left_alone(self):
        raw = {"prompt": "review my PR please"}
        assert unwrap_payload(raw) == raw

    def test_prompt_that_parses_to_non_dict_is_left_alone(self):
        raw = {"prompt": "[1, 2]"}
        assert unwrap_payload(raw) == raw

    def test_prompt_beside_other_keys_is_not_a_wrapper(self):
        raw = {"prompt": json.dumps(_payload()), "run_id": RUN_ID}
        assert unwrap_payload(raw) == raw

    def test_non_dict_input_is_returned_unchanged(self):
        assert unwrap_payload(["x"]) == ["x"]  # type: ignore[arg-type]

    def test_pathological_wrapper_chain_terminates(self):
        # Escaping doubles the string per level, so keep the core tiny.
        inner: dict = {}
        for _ in range(main._MAX_UNWRAP_DEPTH + 2):
            inner = {"prompt": json.dumps(inner)}
        out = unwrap_payload(inner)
        assert isinstance(out, dict)
        assert list(out) == ["prompt"]  # bound reached; still wrapped, never loops


# ---------------------------------------------------------------------------
# TC-204-05 — apply_defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_defaults_applied_to_pr_number_only(self):
        assert apply_defaults({"pr_number": 7}) == {
            "pr_number": 7,
            "max_diff_lines": 2000,
            "max_context_tokens": 150000,
            "max_suggestions": 5,
            "run_timeout_seconds": 900,
            "reasoning_effort": "high",
        }

    def test_explicit_values_are_kept(self):
        params = {
            "pr_number": 3,
            "max_diff_lines": 100,
            "max_context_tokens": 20000,
            "max_suggestions": 0,
            "run_timeout_seconds": 120,
            "reasoning_effort": "low",
        }
        assert apply_defaults(params) == params

    def test_input_is_not_mutated(self):
        params = {"pr_number": 7}
        apply_defaults(params)
        assert params == {"pr_number": 7}

    def test_idempotent(self):
        once = apply_defaults({"pr_number": 9, "max_suggestions": 2})
        assert apply_defaults(once) == once

    def test_default_params_constant_matches_schema_defaults(self):
        schema_defaults = {
            k: v["default"] for k, v in PARAMS_SCHEMA["properties"].items() if "default" in v
        }
        assert schema_defaults == DEFAULT_PARAMS
        assert "pr_number" not in DEFAULT_PARAMS


# ---------------------------------------------------------------------------
# TC-204-06 — pr_number
# ---------------------------------------------------------------------------


class TestPrNumber:
    @pytest.mark.parametrize("value", [1, 42, 2**31 - 1])
    def test_positive_integer_accepted(self, value):
        validate_payload(_payload({"pr_number": value}))

    @pytest.mark.parametrize(
        "value",
        [0, -1, "7", 7.0, 1.5, True, False, None, [7], {"n": 7}],
        ids=[
            "zero",
            "negative",
            "string",
            "float7",
            "float1.5",
            "true",
            "false",
            "null",
            "list",
            "dict",
        ],
    )
    def test_invalid_pr_number_rejected(self, value):
        with pytest.raises(InvalidParams) as exc_info:
            validate_payload(_payload({"pr_number": value}))
        assert exc_info.value.field == "params.pr_number"

    def test_missing_pr_number_rejected(self):
        with pytest.raises(InvalidParams) as exc_info:
            validate_payload(_payload({"max_diff_lines": 2000}))
        assert exc_info.value.field == "params.pr_number"


# ---------------------------------------------------------------------------
# TC-204-07 — bounds
# ---------------------------------------------------------------------------

BOUNDS = {
    "max_diff_lines": (100, 10000),
    "max_context_tokens": (20000, 400000),
    "max_suggestions": (0, 20),
    "run_timeout_seconds": (120, 900),
}


class TestBounds:
    @pytest.mark.parametrize("key", list(BOUNDS))
    def test_exact_min_and_max_accepted(self, key):
        lo, hi = BOUNDS[key]
        validate_payload(_payload({"pr_number": 1, key: lo}))
        validate_payload(_payload({"pr_number": 1, key: hi}))

    @pytest.mark.parametrize("key", list(BOUNDS))
    def test_one_below_min_rejected(self, key):
        lo, _ = BOUNDS[key]
        with pytest.raises(InvalidParams) as exc_info:
            validate_payload(_payload({"pr_number": 1, key: lo - 1}))
        assert exc_info.value.field == f"params.{key}"

    @pytest.mark.parametrize("key", list(BOUNDS))
    def test_one_above_max_rejected(self, key):
        _, hi = BOUNDS[key]
        with pytest.raises(InvalidParams) as exc_info:
            validate_payload(_payload({"pr_number": 1, key: hi + 1}))
        assert exc_info.value.field == f"params.{key}"

    @pytest.mark.parametrize("key", list(BOUNDS))
    @pytest.mark.parametrize("value", [True, "500", 500.5, None])
    def test_non_integer_limit_rejected(self, key, value):
        with pytest.raises(InvalidParams):
            validate_payload(_payload({"pr_number": 1, key: value}))

    def test_schema_bounds_match_this_table(self):
        for key, (lo, hi) in BOUNDS.items():
            prop = PARAMS_SCHEMA["properties"][key]
            assert (prop["minimum"], prop["maximum"]) == (lo, hi)


# ---------------------------------------------------------------------------
# TC-204-08 — reasoning_effort
# ---------------------------------------------------------------------------


class TestReasoningEffort:
    @pytest.mark.parametrize("value", ["low", "medium", "high"])
    def test_enum_values_accepted(self, value):
        validate_payload(_payload({"pr_number": 1, "reasoning_effort": value}))

    @pytest.mark.parametrize("value", ["HIGH", "", None, "max", 1, True])
    def test_other_values_rejected(self, value):
        with pytest.raises(InvalidParams) as exc_info:
            validate_payload(_payload({"pr_number": 1, "reasoning_effort": value}))
        assert exc_info.value.field == "params.reasoning_effort"


# ---------------------------------------------------------------------------
# TC-204-09 — params shape
# ---------------------------------------------------------------------------


class TestParamsShape:
    def test_unknown_key_rejected(self):
        with pytest.raises(InvalidParams) as exc_info:
            validate_payload(_payload({"pr_number": 1, "foo": 1}))
        assert exc_info.value.field == "params.foo"

    def test_params_absent_rejected(self):
        with pytest.raises(InvalidParams) as exc_info:
            validate_payload(_payload(absent=True))
        assert exc_info.value.field == "params"

    @pytest.mark.parametrize("value", [[{"pr_number": 1}], '{"pr_number": 1}', None, 1])
    def test_params_not_an_object_rejected(self, value):
        with pytest.raises(InvalidParams) as exc_info:
            validate_payload(_payload(value))
        assert exc_info.value.field == "params"

    def test_validate_params_direct_call(self):
        validate_params({"pr_number": 1})
        with pytest.raises(InvalidParams):
            validate_params({})

    def test_validation_does_not_mutate(self):
        p = _payload({"pr_number": 1, "max_suggestions": 3})
        before = copy.deepcopy(p)
        validate_payload(p)
        assert p == before

    def test_error_message_is_bounded(self):
        with pytest.raises(InvalidParams) as exc_info:
            validate_payload(_payload({"pr_number": 1, "x" * 5000: 1}))
        assert len(str(exc_info.value)) <= 300


# ---------------------------------------------------------------------------
# TC-204-10 / CT-03 — top-level payload fields
# ---------------------------------------------------------------------------


class TestPayloadFields:
    @pytest.mark.parametrize("field", ["run_id", "repository_org", "repository_name"])
    def test_missing_field_rejected_naming_it(self, field):
        p = _payload()
        del p[field]
        with pytest.raises(InvalidParams) as exc_info:
            validate_payload(p)
        assert exc_info.value.field == field
        assert field in str(exc_info.value)

    @pytest.mark.parametrize("field", ["run_id", "repository_org", "repository_name"])
    @pytest.mark.parametrize("value", [5, None, True, ["x"], {"a": 1}, ""])
    def test_non_string_or_empty_field_rejected(self, field, value):
        with pytest.raises(InvalidParams) as exc_info:
            validate_payload(_payload(**{field: value}))
        assert exc_info.value.field == field

    @pytest.mark.parametrize(
        "run_id", ["r-1", "not-a-uuid", f"{RUN_ID}&status=eq.running", RUN_ID + "0"]
    )
    def test_run_id_must_be_a_uuid(self, run_id):
        # run_id is interpolated into a PostgREST filter by the reporter.
        with pytest.raises(InvalidParams) as exc_info:
            validate_payload(_payload(run_id=run_id))
        assert exc_info.value.field == "run_id"

    def test_uppercase_uuid_accepted(self):
        validate_payload(_payload(run_id=RUN_ID.upper()))

    def test_unknown_top_level_key_tolerated(self):
        validate_payload(_payload(trigger="webhook"))

    @pytest.mark.parametrize("value", [None, [], "x", 3])
    def test_payload_not_a_dict_rejected(self, value):
        with pytest.raises(InvalidParams):
            validate_payload(value)  # type: ignore[arg-type]

    def test_wrapped_payload_accepted_after_unwrap(self):
        p = _payload()
        validate_payload(unwrap_payload({"prompt": json.dumps({"prompt": json.dumps(p)})}))

    def test_still_wrapped_payload_is_classified(self):
        assert main.classify_invalid_payload({"prompt": "x"}) == "wrapper_only"
        assert main.classify_invalid_payload({"run_id": RUN_ID}) == "missing_fields"

    def test_invalid_params_is_a_value_error(self):
        assert issubclass(InvalidParams, ValueError)


# ---------------------------------------------------------------------------
# CT-01 — shared case file, Python side
# ---------------------------------------------------------------------------


def _cases() -> list[dict]:
    return json.loads(CASES_FILE.read_text())["cases"]


def test_case_file_has_a_meaningful_spread():
    cases = _cases()
    assert len(cases) >= 40
    assert any(c["valid"] for c in cases)
    assert any(not c["valid"] for c in cases)
    assert len({c["id"] for c in cases}) == len(cases)


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["id"])
def test_ct01_python_validator_matches_expected_verdict(case):
    payload = _payload(case.get("params"), absent=case.get("absent", False))
    if case["valid"]:
        validate_payload(payload)
    else:
        with pytest.raises(InvalidParams):
            validate_payload(payload)
