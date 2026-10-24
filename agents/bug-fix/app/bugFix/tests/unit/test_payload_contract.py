"""L1 payload contract tests (CT-01, CT-02 params part, CT-21; S-184).

The shared fixtures under ``tests/fixtures/contract/`` are the panel → agent
contract. ``params_schema.json`` is the spec §5.2 v2.0 copy, and the panel
L2.5 test (``panel/tests/integration/bug-fix-seed.test.ts``) proves the seed
deep-equals it (CT-06). Here the agent side proves its defaults equal the same
fixture (CT-21), so agent defaults equal seed defaults and a one-sided change
fails a test. Webhook-started runs depend on this because the panel does not
apply defaults (``useDefaults: false``).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

import params
from params import MissingRequiredParam, parse_params

CONTRACT = Path(__file__).resolve().parents[1] / "fixtures" / "contract"
SCHEMA: dict[str, Any] = json.loads((CONTRACT / "params_schema.json").read_text())


def _payload(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((CONTRACT / f"payload.{name}.json").read_text())
    return data


def test_agent_defaults_equal_the_schema_defaults_key_by_key():
    # CT-21
    expected = {k: p["default"] for k, p in SCHEMA["properties"].items() if "default" in p}
    assert dict(params.DEFAULTS) == expected


def test_schema_contract_shape():
    assert SCHEMA["required"] == ["issue_number"]
    assert SCHEMA["additionalProperties"] is False


@pytest.mark.parametrize("name", ["webhook", "manual"])
def test_payload_has_exactly_the_d60_keys(name: str):
    assert set(_payload(name)) == {
        "run_id",
        "repository_org",
        "repository_name",
        "base_branch",
        "params",
    }


def test_webhook_shape_parses_with_seed_defaults():
    # CT-01: webhook shape, no defaults sent.
    p = parse_params(_payload("webhook")["params"])
    assert p.issue_number == 7
    assert p.trigger_comment_id == 123
    for key, value in params.DEFAULTS.items():
        assert getattr(p, key) == value


def test_manual_shape_equals_the_webhook_shape_apart_from_the_comment_id():
    # CT-01: manual shape = issue_number + default_params.
    manual = dataclasses.asdict(parse_params(_payload("manual")["params"]))
    webhook = dataclasses.asdict(parse_params(_payload("webhook")["params"]))
    webhook["trigger_comment_id"] = None
    assert manual == webhook


def test_params_without_issue_number_is_a_typed_error():
    # CT-02 (params part): S-185 maps it to not_applicable invalid_params.
    raw = dict(_payload("webhook")["params"])
    del raw["issue_number"]
    with pytest.raises(MissingRequiredParam) as info:
        parse_params(raw)
    assert info.value.key == "issue_number"
