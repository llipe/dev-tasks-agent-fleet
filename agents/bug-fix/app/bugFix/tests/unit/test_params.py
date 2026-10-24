"""L1 tests for the typed params (S-184 AC4; D-82, D-93, D-102).

``parse_params`` turns the payload ``params`` into a frozen ``Params``. It
applies the seed-equal defaults for budgets, caps and status names, and it
enforces the same types and bounds as ``params_schema`` (spec §5.2 v2.0). A
missing ``issue_number`` raises ``MissingRequiredParam``; a type or bounds
violation raises ``InvalidParam``. Both name the key, never the value, and
S-185 turns them into refusal ``invalid_params``.

The bounds are read from the contract fixture (the spec §5.2 copy that the
panel L2.5 test proves equal to the seed), so changing one side alone fails.

Test plan: TC-184-08, -10, -12, -13, -14; TC-184-07 boundary table; 5.9 edges.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

import params
from params import InvalidParam, MissingRequiredParam, Params, ParamsError, parse_params

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "contract" / "params_schema.json"
SCHEMA: dict[str, Any] = json.loads(FIXTURE.read_text())
PROPS: dict[str, dict[str, Any]] = SCHEMA["properties"]

INT_KEYS = [k for k, p in PROPS.items() if p["type"] == "integer"]
STATUS_KEYS = ["status_in_progress", "status_in_review", "status_ready"]
DEFAULTED = [k for k, p in PROPS.items() if "default" in p]
BOUNDED = [k for k in INT_KEYS if "maximum" in PROPS[k]]


def _ok(**extra: Any) -> dict[str, Any]:
    return {"issue_number": 7, **extra}


def _raises(raw: Any, key: str, kind: type[ParamsError] = InvalidParam) -> ParamsError:
    with pytest.raises(kind) as info:
        parse_params(raw)
    assert info.value.key == key
    assert key in str(info.value)
    return info.value


class TestValid:
    def test_issue_number_only_fills_every_default(self):
        # TC-184-08
        p = parse_params({"issue_number": 7})
        assert isinstance(p, Params)
        assert p.issue_number == 7
        assert p.trigger_comment_id is None
        assert p.project is None
        assert (p.max_turns, p.cli_timeout_minutes, p.run_budget_minutes) == (40, 30, 55)
        assert (p.max_code_files, p.max_code_lines) == (10, 400)
        assert (p.status_in_progress, p.status_in_review, p.status_ready) == (
            "In progress",
            "In review",
            "Ready",
        )

    def test_every_key_given(self):
        raw = {
            "issue_number": 12,
            "trigger_comment_id": 2_500_000_000,
            "project": "my-org/1234567",
            "status_in_progress": "Doing",
            "status_in_review": "Review",
            "status_ready": "Todo",
            "max_turns": 5,
            "cli_timeout_minutes": 45,
            "run_budget_minutes": 10,
            "max_code_files": 50,
            "max_code_lines": 2000,
        }
        assert dataclasses.asdict(parse_params(raw)) == raw

    def test_params_is_frozen(self):
        p = parse_params(_ok())
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.max_turns = 99  # type: ignore[misc]

    def test_typed_fields_are_exactly_the_schema_properties(self):
        assert {f.name for f in dataclasses.fields(Params)} == set(PROPS)

    def test_integral_float_is_accepted_like_json_schema_integer(self):
        # JSON Schema `integer` accepts 40.0; the value is normalized to int.
        p = parse_params(_ok(max_turns=40.0))
        assert p.max_turns == 40
        assert type(p.max_turns) is int


class TestDefaults:
    @pytest.mark.parametrize("key", DEFAULTED)
    def test_absent_key_takes_the_seed_default(self, key: str):
        # TC-184-13: every webhook-started run takes this path (useDefaults: false).
        full = {k: PROPS[k]["default"] for k in DEFAULTED}
        full.pop(key)
        p = parse_params(_ok(**full))
        assert getattr(p, key) == PROPS[key]["default"]
        assert getattr(p, key) is not None

    def test_defaults_constant_equals_the_schema_defaults(self):
        assert dict(params.DEFAULTS) == {k: PROPS[k]["default"] for k in DEFAULTED}

    def test_optional_keys_without_default_stay_none(self):
        p = parse_params(_ok())
        assert p.trigger_comment_id is None
        assert p.project is None


class TestRequired:
    def test_missing_issue_number(self):
        # TC-184-10: no default is invented (D-82, D-93).
        err = _raises({}, "issue_number", MissingRequiredParam)
        assert isinstance(err, ParamsError)

    def test_missing_issue_number_with_other_keys(self):
        _raises({"max_turns": 40, "trigger_comment_id": 3}, "issue_number", MissingRequiredParam)

    @pytest.mark.parametrize("raw", [None, [], "7", 7, [("issue_number", 7)]])
    def test_params_not_an_object(self, raw: Any):
        _raises(raw, "params")


class TestIntegerBounds:
    @pytest.mark.parametrize("key", INT_KEYS)
    def test_minimum_is_accepted(self, key: str):
        lo = PROPS[key]["minimum"]
        assert getattr(parse_params(_ok(**{key: lo})), key) == lo

    @pytest.mark.parametrize("key", INT_KEYS)
    def test_one_below_minimum_is_rejected(self, key: str):
        _raises(_ok(**{key: PROPS[key]["minimum"] - 1}), key)

    @pytest.mark.parametrize("key", BOUNDED)
    def test_maximum_is_accepted(self, key: str):
        hi = PROPS[key]["maximum"]
        assert getattr(parse_params(_ok(**{key: hi})), key) == hi

    @pytest.mark.parametrize("key", BOUNDED)
    def test_one_above_maximum_is_rejected(self, key: str):
        _raises(_ok(**{key: PROPS[key]["maximum"] + 1}), key)

    @pytest.mark.parametrize("key", ["issue_number", "trigger_comment_id"])
    def test_unbounded_ids_accept_large_values(self, key: str):
        # TC-184-07: 2**40 (a comment id above 2**31 must survive).
        assert getattr(parse_params(_ok(**{key: 2**40})), key) == 2**40

    @pytest.mark.parametrize("key", INT_KEYS)
    @pytest.mark.parametrize(
        "bad",
        ["40", None, True, False, 40.5, [], {}, float("inf"), float("nan")],
        ids=repr,
    )
    def test_wrong_type_is_rejected(self, key: str, bad: Any):
        _raises(_ok(**{key: bad}), key)


class TestStrings:
    @pytest.mark.parametrize("key", STATUS_KEYS)
    @pytest.mark.parametrize("value", ["x", "a" * 100, "é" * 100, "In progress"], ids=len)
    def test_status_name_within_bounds(self, key: str, value: str):
        # 5.9: a 100-character status name is accepted.
        assert getattr(parse_params(_ok(**{key: value})), key) == value

    @pytest.mark.parametrize("key", STATUS_KEYS)
    @pytest.mark.parametrize("bad", ["", "a" * 101, 7, None, True, ["Ready"]], ids=repr)
    def test_status_name_rejected(self, key: str, bad: Any):
        _raises(_ok(**{key: bad}), key)

    @pytest.mark.parametrize(
        "value", ["llipe/5", "my-org/1234567", "a/1", "A" * 39 + "/9", "x-y-z/10"]
    )
    def test_project_matches_owner_number(self, value: str):
        assert parse_params(_ok(project=value)).project == value

    @pytest.mark.parametrize(
        "bad",
        [
            "llipe/0",
            "llipe",
            "a/b/1",
            "llipe/12345678",
            "under_score/1",
            "x",
            "",
            "A" * 40 + "/1",
            "llipe/5\n",  # `$` must not match before a trailing newline
            " llipe/5",
            "llipe/05",
            5,
            None,
        ],
        ids=repr,
    )
    def test_project_failing_the_pattern(self, bad: Any):
        # 5.9: a project that fails the pattern.
        _raises(_ok(project=bad), "project")


class TestDirectInvokeViolations:
    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("run_budget_minutes", 600),
            ("max_code_files", 0),
            ("max_code_files", 10000),
            ("max_turns", "40"),
            ("max_turns", None),
            ("issue_number", True),
            ("status_ready", ""),
            ("project", "x"),
            ("trigger_comment_id", "123"),  # 5.9: comment id as a string
            ("issue_number", "12"),
            ("issue_number", 0),
        ],
    )
    def test_violation_names_the_key(self, key: str, value: Any):
        # TC-184-14 (D-82, resolves DF-25): never runs with a bound outside §5.2.
        _raises({"issue_number": 7, key: value}, key)

    def test_message_never_contains_the_value(self):
        secretish = "SENTINEL-" + "z" * 120
        err = _raises(_ok(status_ready=secretish), "status_ready")
        assert "SENTINEL" not in str(err)
        assert "SENTINEL" not in repr(err)

    def test_first_violation_in_schema_order_is_reported(self):
        # Deterministic for the reply: keys are checked in schema order.
        _raises({"issue_number": 0, "max_turns": 0}, "issue_number")


class TestUnknownKeys:
    @pytest.mark.parametrize(
        "key",
        [
            "select_labels",
            "claim_remove_labels",
            "claim_add_labels",
            "disposition_add_labels",
            "assignee",
            "foo",
            "repo",
            "__probe",
        ],
    )
    def test_unknown_key_is_ignored_and_never_read(self, key: str):
        # TC-184-12 (FR-3, D-93): a stale payload can't bring label behaviour back.
        p = parse_params(_ok(**{key: ["status: ready"]}))
        assert p == parse_params(_ok())
        assert not hasattr(p, key)
