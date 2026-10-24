"""
S-210 (#412) — the ``submit_review`` validator and strict JSON parse (spec §6.3).

The model output is untrusted (rule: hostile input). The validator walks the
schema, never the value's own nesting, so its cost is linear in the value's
size whatever its depth. It rejects non-object roots, over-long strings,
``NaN``/``Infinity``, ``bool`` and ``float`` for integers, and a ``$`` that
would let ``"V1\\n"`` through. Error messages name a schema path and a rule,
never the model's text.
"""

from __future__ import annotations

import json
import time

import pytest

from findings_schema import (
    MAX_FINDINGS,
    MAX_REVIEW_JSON_CHARS,
    SUBMIT_REVIEW_SCHEMA,
    SchemaViolation,
    parse_review_json,
    validate_review,
)
from tests.fixtures.bedrock import finding, valid_review
from tests.helpers.perf import perf_bound

SENTINEL = "SENTINEL-DO-NOT-ECHO"


def _violation(value: object) -> SchemaViolation:
    with pytest.raises(SchemaViolation) as exc:
        validate_review(value)
    return exc.value


# --- paths and messages ----------------------------------------------------


@pytest.mark.parametrize(
    ("value", "path", "rule"),
    [
        ([], "$", "type"),
        (None, "$", "type"),
        ("{}", "$", "type"),
        (float("nan"), "$", "type"),
        ({"findings": []}, "$.verifier_checks", "required"),
        ({"findings": [], "verifier_checks": [], "x": 1}, "$", "additional"),
        ({"findings": "x", "verifier_checks": []}, "$.findings", "type"),
        ({"findings": [1], "verifier_checks": []}, "$.findings[0]", "type"),
        (
            {"findings": [finding(), finding(category="x")], "verifier_checks": []},
            "$.findings[1].category",
            "enum",
        ),
        (
            {
                "findings": [],
                "verifier_checks": [{"candidate_id": "V1", "status": "x", "reason": ""}],
            },
            "$.verifier_checks[0].status",
            "enum",
        ),
    ],
)
def test_violation_names_the_schema_path_and_rule(value, path, rule):
    v = _violation(value)
    assert (v.path, v.rule) == (path, rule)
    assert str(v).startswith(f"{path}: ")


def test_required_is_checked_in_schema_order_before_unknown_keys():
    v = _violation({"zzz": 1})
    assert (v.path, v.rule) == ("$.findings", "required")


def test_the_first_violation_in_document_order_wins():
    review = valid_review(3)
    review["findings"][2]["title"] = 5
    review["findings"][1]["rank"] = 0
    assert _violation(review).path == "$.findings[1].rank"


@pytest.mark.parametrize(
    "value",
    [
        {"findings": [], "verifier_checks": [], SENTINEL: 1},
        {"findings": [finding(category=SENTINEL)], "verifier_checks": []},
        {"findings": [{**finding(), SENTINEL: 1}], "verifier_checks": []},
        {"findings": [finding(title=SENTINEL * 100)], "verifier_checks": []},
        {
            "findings": [],
            "verifier_checks": [{"candidate_id": SENTINEL, "status": "confirmed", "reason": ""}],
        },
    ],
)
def test_messages_never_echo_model_text(value):
    v = _violation(value)
    assert SENTINEL not in str(v) and SENTINEL not in v.path
    assert len(str(v)) < 200


def test_non_string_keys_are_unexpected_properties():
    assert _violation({"findings": [], "verifier_checks": [], 1: 2}).rule == "additional"


# --- integers, strings, pattern ---------------------------------------------


@pytest.mark.parametrize("bad", [True, False, 1.0, float("nan"), float("inf"), "1", None, [1]])
def test_integers_reject_bool_float_nan_and_strings(bad):
    v = _violation({"findings": [finding(rank=bad)], "verifier_checks": []})
    assert v.rule == "type"


def test_integers_accept_huge_values():
    validate_review({"findings": [finding(rank=10**40, line_end=10**40)], "verifier_checks": []})


@pytest.mark.parametrize("bad", ["V1\n", "V", "v1", " V1", "V1 ", "V١", "VV1", "V1a"])
def test_candidate_id_pattern_is_anchored_and_ascii(bad):
    checks = [{"candidate_id": bad, "status": "confirmed", "reason": ""}]
    assert _violation({"findings": [], "verifier_checks": checks}).rule == "pattern"


def test_candidate_id_pattern_accepts_v_digits():
    checks = [{"candidate_id": "V0123", "status": "confirmed", "reason": ""}]
    validate_review({"findings": [], "verifier_checks": checks})


@pytest.mark.parametrize(
    ("key", "limit"),
    [("file", 400), ("title", 200), ("failure_scenario", 1500), ("consequence", 500)],
)
def test_max_length_counts_code_points(key, limit):
    validate_review({"findings": [finding(**{key: "漢" * limit})], "verifier_checks": []})
    v = _violation({"findings": [finding(**{key: "漢" * (limit + 1)})], "verifier_checks": []})
    assert v.rule == "maxLength"


def test_max_findings_is_the_schema_max_items():
    assert MAX_FINDINGS == SUBMIT_REVIEW_SCHEMA["properties"]["findings"]["maxItems"] == 40
    validate_review(valid_review(40))
    assert _violation(valid_review(41)).rule == "maxItems"


# --- hostile sizes and shapes ------------------------------------------------


def _timed(fn) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def test_a_huge_string_is_rejected_quickly():
    value = {"findings": [finding(title="t" * 20_000_000)], "verifier_checks": []}
    assert _timed(lambda: _violation(value)) < perf_bound(0.5)


def test_a_huge_findings_list_is_rejected_by_max_items_before_its_items():
    value = {"findings": [object()] * 5_000_000, "verifier_checks": []}
    assert _timed(lambda: _violation(value)) < perf_bound(0.1)


def test_deep_nesting_in_a_scalar_field_is_rejected_without_recursion():
    deep: list = []
    for _ in range(200_000):
        deep = [deep]
    value = {"findings": [finding(title=deep)], "verifier_checks": []}
    assert _violation(value).rule == "type"


def test_many_verifier_checks_validate_in_linear_time():
    checks = [
        {"candidate_id": f"V{k}", "status": "confirmed", "reason": ""} for k in range(200_000)
    ]
    assert _timed(
        lambda: validate_review({"findings": [], "verifier_checks": checks})
    ) < perf_bound(2.0)


# --- strict JSON (fallback mode, DF-21 pinned) -------------------------------


def test_parse_accepts_one_object_with_surrounding_whitespace():
    assert parse_review_json("\n  " + json.dumps(valid_review()) + " \n") == valid_review()


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "```json\n{}\n```",
        "Sure! {}",
        "{} trailing",
        "{}{}",
        '{"a": NaN}',
        '{"a": Infinity}',
        '{"a": -Infinity}',
        "[" * 100_000 + "]" * 100_000,
        '{"rank": 1' + "0" * 5000 + "}",
        "{'single': 'quotes'}",
        '{"a": 1,}',
    ],
    ids=[
        "empty",
        "blank",
        "fenced",
        "leading-prose",
        "trailing-prose",
        "two-objects",
        "nan",
        "infinity",
        "neg-infinity",
        "deep",
        "huge-int",
        "single-quotes",
        "trailing-comma",
    ],
)
def test_parse_rejects_everything_but_exactly_one_json_value(text):
    with pytest.raises(SchemaViolation) as exc:
        parse_review_json(text)
    assert exc.value.rule == "json"
    assert exc.value.path == "$"


def test_parse_rejects_over_long_text_without_parsing():
    text = " " * (MAX_REVIEW_JSON_CHARS + 1)
    with pytest.raises(SchemaViolation) as exc:
        parse_review_json(text)
    assert exc.value.rule == "json"


def test_parse_errors_never_echo_the_text():
    with pytest.raises(SchemaViolation) as exc:
        parse_review_json(f"{SENTINEL} {{}}")
    assert SENTINEL not in str(exc.value)


def test_parse_returns_non_objects_for_the_validator_to_reject():
    assert parse_review_json("[1, 2]") == [1, 2]
    assert _violation(parse_review_json("[1, 2]")).rule == "type"


# --- the interpreter itself ---------------------------------------------------


def test_an_escaped_final_dollar_is_a_literal():
    from findings_schema import _pattern

    assert _pattern(r"^a\$").search("a$") is not None
    assert _pattern("^a$").search("a\n") is None


@pytest.mark.parametrize("schema", [{"type": "object", "oneOf": []}, {"type": "number"}])
def test_an_unsupported_schema_keyword_or_type_is_a_defect(schema):
    from findings_schema import SchemaError, _check

    with pytest.raises(SchemaError) as exc:
        _check({}, schema, "$")
    assert exc.value.code == "INTERNAL_ERROR"


def test_open_objects_and_untyped_arrays_are_supported():
    from findings_schema import _check

    _check({"a": 1, "b": 2}, {"type": "object", "properties": {"a": {"type": "integer"}}}, "$")
    _check([1, "x"], {"type": "array"}, "$")
    _check({}, {"type": "object", "properties": {"a": {"type": "integer"}}}, "$")


def test_parse_rejects_deep_nesting_before_the_json_parser_runs(monkeypatch):
    # Python 3.14's json parses 100k-deep arrays without RecursionError, so the
    # depth check must not rely on it.
    import findings_schema

    def _no_parse(*_a, **_k):
        raise AssertionError("json.loads must not run on over-deep input")

    monkeypatch.setattr(findings_schema.json, "loads", _no_parse)
    deep = "[" * (findings_schema.MAX_REVIEW_JSON_DEPTH + 1) + "]" * (
        findings_schema.MAX_REVIEW_JSON_DEPTH + 1
    )
    with pytest.raises(SchemaViolation) as exc:
        parse_review_json(deep)
    assert exc.value.rule == "json"


def test_parse_depth_ignores_brackets_inside_strings():
    import findings_schema

    text = '{"findings": [], "verifier_checks": [], "note": "' + "[{" * 500 + '\\"]}"}'
    assert findings_schema._nesting_depth(text) == 2
    assert parse_review_json(text)["findings"] == []


def test_parse_accepts_nesting_at_the_depth_limit():
    import findings_schema

    depth = findings_schema.MAX_REVIEW_JSON_DEPTH
    assert parse_review_json("[" * depth + "]" * depth) is not None
