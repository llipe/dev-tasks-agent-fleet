"""
Cross-language payload contract test (S-112 / issue #125, SR4, #89 AC3).

Nothing type-checks the panel -> agent boundary: it is JSON emitted by the
panel's ``buildAgentPayload`` (TypeScript), delivered over InvokeAgentRuntime,
and validated here by the agent's ``validate_payload`` (Python). A dropped,
renamed, or nested required field would otherwise fail silently at runtime.

This test pins the *Python side* of the shared fixture
``tests/fixtures/agent-invocation-payload.json`` (repo root). The panel's
``tests/unit/payload.test.ts`` pins the TypeScript side against the SAME file.
So a contract drift on either side fails a test on that side, not in production.

This file MUST NOT modify agent production code — the agent contract
(``_REQUIRED_FIELDS`` in main.py) is authoritative and unchanged. It only
consumes the shared fixture and asserts the existing validator accepts it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from main import _REQUIRED_FIELDS, apply_defaults, unwrap_payload, validate_payload


def _find_repo_root() -> Path:
    """Walk up from this test file to the repository root.

    The shared fixture lives at ``<repo-root>/tests/fixtures/``. The agent's
    pytest rootdir is the agent package dir, several levels below the repo root,
    so we locate the root by its ``.git`` marker rather than hard-coding a
    fragile ``../../..``. The agent package itself also has a
    ``tests/fixtures`` dir, so that must NOT be used as a marker — only the
    top-level ``.git`` (a repo has exactly one) identifies the true root.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    raise RuntimeError("could not locate repository root (.git) from the test file location")


def _load_shared_fixture() -> dict:
    fixture_path = _find_repo_root() / "tests" / "fixtures" / "agent-invocation-payload.json"
    assert fixture_path.is_file(), f"shared contract fixture not found at {fixture_path}"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


class TestSharedPayloadContractFixture:
    """The panel's emitted payload (fixture) is accepted by validate_payload."""

    def test_fixture_has_exactly_the_contract_keys(self) -> None:
        fixture = _load_shared_fixture()
        assert set(fixture.keys()) == {
            "run_id",
            "repository_org",
            "repository_name",
            "base_branch",
            "params",
        }
        # repository_id is a panel-internal id and MUST NOT cross the boundary.
        assert "repository_id" not in fixture

    def test_required_fields_are_nonempty_top_level_strings(self) -> None:
        fixture = _load_shared_fixture()
        for field in _REQUIRED_FIELDS:
            assert field in fixture, f"required field {field!r} missing from fixture"
            assert isinstance(fixture[field], str), f"{field!r} must be a string"
            assert fixture[field], f"{field!r} must be non-empty"

    def test_validate_payload_accepts_the_shared_fixture(self) -> None:
        fixture = _load_shared_fixture()
        # The panel sends the bare inner JSON; the agent unwraps any prompt
        # wrapper first (a no-op here) then validates.
        payload = unwrap_payload(fixture)
        validated = validate_payload(payload)
        assert validated is not None, "agent validate_payload rejected the panel's fixture payload"
        assert validated["run_id"] == fixture["run_id"]
        assert validated["repository_org"] == fixture["repository_org"]
        assert validated["repository_name"] == fixture["repository_name"]

    def test_defaults_apply_cleanly_over_the_fixture_params(self) -> None:
        # apply_defaults must not blow up on the fixture's params shape, and the
        # constrained max_fix_attempts (0..5) survives round-trip.
        fixture = _load_shared_fixture()
        validated = validate_payload(unwrap_payload(fixture))
        assert validated is not None
        with_defaults = apply_defaults(validated)
        assert with_defaults["params"]["fix_mode"] in ("audit_only", "llm_fix")
        assert 0 <= int(with_defaults["params"]["max_fix_attempts"]) <= 5

    @pytest.mark.parametrize("dropped", ["run_id", "repository_org", "repository_name"])
    def test_dropping_a_required_field_fails_validation(self, dropped: str) -> None:
        # Proves the fixture-based contract is falsifiable: remove any required
        # field and the agent rejects it. This is the mechanism that keeps #89
        # closed — a panel-side field rename that dropped one of these would
        # make the panel fixture test AND this test disagree.
        fixture = _load_shared_fixture()
        del fixture[dropped]
        assert validate_payload(fixture) is None

    def test_nesting_a_required_field_fails_validation(self) -> None:
        # A field nested under an extra wrapper (the #89 failure mode) is not a
        # top-level string, so validation rejects it.
        fixture = _load_shared_fixture()
        fixture["run_id"] = {"value": fixture["run_id"]}
        assert validate_payload(fixture) is None
