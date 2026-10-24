"""L1 cross-side contract: the shared params corpus (S-184; CT-03, CT-04, D-82).

``tests/fixtures/contract/params_cases.json`` is a single accept/reject corpus
that both validators run: the panel's Ajv (``panel/tests/unit/
bug-fix-params-schema.test.ts``) and this package's ``parse_params``. Each side
already pins its bounds to ``params_schema.json``. This corpus also pins their
*semantics* (integral floats, astral-plane string length, ``$`` before a
trailing newline, non-ASCII digits) to one shared list of inputs, so a
divergence between Ajv and Python shows up as a failing case on one side.

Unknown keys are the one deliberate asymmetry. The panel rejects them
(``additionalProperties: false``), and the agent ignores them and never reads
them (FR-3, D-93).

It also checks that no error message echoes a param value, for every key and
every error path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from params import InvalidParam, MissingRequiredParam, ParamsError, parse_params

CONTRACT = Path(__file__).resolve().parents[1] / "fixtures" / "contract"
CORPUS: dict[str, Any] = json.loads((CONTRACT / "params_cases.json").read_text())
CASES: list[dict[str, Any]] = CORPUS["cases"]
PROPS: dict[str, dict[str, Any]] = json.loads((CONTRACT / "params_schema.json").read_text())[
    "properties"
]


def test_corpus_names_only_schema_keys_and_covers_every_key():
    failing = {c["key"] for c in CASES if not c["valid"]}
    assert failing <= set(PROPS)
    assert failing == set(PROPS), f"no rejection case for {set(PROPS) - failing}"
    assert len({c["name"] for c in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_agent_agrees_with_the_shared_corpus(case: dict[str, Any]):
    raw = case["params"]
    if case["valid"]:
        p = parse_params(raw)
        for key, value in raw.items():
            assert getattr(p, key) == value
        return
    kind = MissingRequiredParam if "issue_number" not in raw else InvalidParam
    with pytest.raises(kind) as info:
        parse_params(raw)
    assert info.value.key == case["key"]


@pytest.mark.parametrize("key", CORPUS["unknown_keys"])
def test_unknown_key_from_the_corpus_is_ignored(key: str):
    assert parse_params({"issue_number": 7, key: "SENTINEL"}) == parse_params({"issue_number": 7})


SENTINEL = "SENTINEL-VALUE-" + "q" * 120


def _sentinel_inputs() -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for key in PROPS:
        out.append((key, SENTINEL))  # wrong type for ints; too long or bad pattern for strings
        out.append((key, [SENTINEL]))
        out.append((key, {"v": SENTINEL}))
    return out


@pytest.mark.parametrize(("key", "value"), _sentinel_inputs(), ids=lambda v: str(v)[:24])
def test_no_error_message_echoes_the_value(key: str, value: Any):
    raw = {"issue_number": 7, key: value}
    with pytest.raises(ParamsError) as info:
        parse_params(raw)
    err = info.value
    assert err.key == key
    for text in (str(err), repr(err), err.reason, str(err.args)):
        assert "SENTINEL" not in text


@pytest.mark.parametrize("key", [k for k, p in PROPS.items() if p["type"] == "integer"])
def test_bounds_message_names_the_bound_not_the_value(key: str):
    # An out-of-range integer: the message may name the bound, never the value.
    value = 987_654_321_987 if "maximum" in PROPS[key] else -987_654_321_987
    with pytest.raises(InvalidParam) as info:
        parse_params({"issue_number": 7, key: value})
    assert "987654321987" not in str(info.value)
    assert "987654321987" not in repr(info.value)
