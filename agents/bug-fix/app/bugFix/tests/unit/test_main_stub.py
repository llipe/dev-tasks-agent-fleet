"""L1 tests for the minimal entrypoint (TC-180-12, S-180 AC7).

The stub reports ``started`` through ``agent_reporter``, then ends
``succeeded``/``not_applicable`` with the summary "not yet implemented", and
returns a terminal chunk. Supabase is faked at the reporter's HTTP client, so
the real ``RunReporter`` lifecycle is exercised.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import pytest

import agent_reporter
import main
from config import Config, ConfigError
from credentials import CredentialError
from heartbeat import read_terminal_payload

SUPABASE_KEY = "supabase-service-role-sentinel-value"
RUN_ID = "11111111-2222-3333-4444-555555555555"

PAYLOAD = {
    "run_id": RUN_ID,
    "repository_org": "llipe",
    "repository_name": "dev-tasks",
    "base_branch": "main",
    "params": {"issue_number": 7, "trigger_comment_id": 99},
}


class FakeSupabase:
    """Records every write the reporter makes; never touches the network."""

    instances: list[FakeSupabase] = []

    def __init__(self, url: str, key: str) -> None:
        self.url = url
        self.key = key
        self.calls: list[tuple[str, str, Any]] = []
        FakeSupabase.instances.append(self)

    def _request(self, method: str, path: str, payload: Any) -> bool:
        self.calls.append((method, path, payload))
        return True

    def insert(self, table: str, rows: Any) -> bool:
        self.calls.append(("insert", table, rows))
        return True

    def update(self, table: str, filt: str, patch: dict) -> bool:
        self.calls.append(("update", table, patch))
        return True

    def update_expect_rows(self, table: str, filt: str, patch: dict) -> int | None:
        self.calls.append(("update", table, patch))
        return 1

    def run_patches(self) -> list[dict]:
        return [p for (op, table, p) in self.calls if op == "update" and table == "runs"]

    def event_messages(self) -> list[str]:
        msgs: list[str] = []
        for op, table, rows in self.calls:
            if op == "insert" and table == "run_events":
                msgs.extend(r.get("message", "") for r in rows)
        return msgs


CONFIG = Config(
    supabase_url="https://example.supabase.co",
    supabase_key_secret_id="agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY",
    anthropic_key_secret_id="agent-fleet/prod/ANTHROPIC_API_KEY",
    model_id="claude-sonnet-4-6",
    projects_token_secret_id="agent-fleet/prod/GITHUB_PROJECTS_TOKEN",
    board_updates_enabled=True,
    board_disabled_reason=None,
)


def _drain(agen) -> list:
    async def _go():
        return [item async for item in agen]

    return asyncio.run(_go())


def _result(chunks: list) -> dict:
    text = read_terminal_payload(chunks)
    assert text is not None, "no terminal chunk"
    return json.loads(text)


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    FakeSupabase.instances = []
    monkeypatch.setattr(agent_reporter, "_SupabaseClient", FakeSupabase)
    monkeypatch.setattr(main, "load_config", lambda: CONFIG)
    monkeypatch.setattr(main, "fetch_supabase_key", lambda secret_id: SUPABASE_KEY)
    monkeypatch.setattr(main, "install_termination_backstop", lambda get_run, get_secrets: None)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)


class TestHappyStub:
    def test_reports_started_then_not_applicable(self):
        chunks = _drain(main.invoke(dict(PAYLOAD), None))

        assert len(FakeSupabase.instances) == 1
        db = FakeSupabase.instances[0]
        patches = db.run_patches()
        assert patches[0]["status"] == "running"  # started
        assert "started_at" in patches[0]
        final = patches[-1]
        assert final["status"] == "succeeded"
        assert final["outcome"] == "not_applicable"
        assert final["result"] == {"summary": "not yet implemented"}

        result = _result(chunks)
        assert result == {
            "status": "succeeded",
            "outcome": "not_applicable",
            "summary": "not yet implemented",
        }

    def test_reporter_uses_resolved_key_and_url(self):
        _drain(main.invoke(dict(PAYLOAD), None))
        db = FakeSupabase.instances[0]
        assert db.url == CONFIG.supabase_url
        assert db.key == SUPABASE_KEY

    def test_a_started_event_is_logged(self):
        _drain(main.invoke(dict(PAYLOAD), None))
        msgs = FakeSupabase.instances[0].event_messages()
        assert any("bug-fix" in m and "started" in m for m in msgs)

    def test_supabase_key_is_never_exported(self):
        # Spec §12 (1): secrets live in wrapper memory, never in os.environ,
        # so no child process can inherit them.
        _drain(main.invoke(dict(PAYLOAD), None))
        assert SUPABASE_KEY not in os.environ.values()
        assert "SUPABASE_SERVICE_ROLE_KEY" not in os.environ

    def test_prompt_wrapped_payload_is_unwrapped(self):
        chunks = _drain(main.invoke({"prompt": json.dumps(PAYLOAD)}, None))
        assert _result(chunks)["outcome"] == "not_applicable"

    def test_backstop_is_installed(self, monkeypatch):
        seen: dict[str, Any] = {}

        def _install(get_run, get_secrets):
            seen["run"] = get_run
            seen["secrets"] = get_secrets

        monkeypatch.setattr(main, "install_termination_backstop", _install)
        _drain(main.invoke(dict(PAYLOAD), None))
        assert seen["run"]() is not None
        assert SUPABASE_KEY in seen["secrets"]()


class TestFailurePaths:
    def test_config_error_returns_failed_without_values(self, monkeypatch):
        def _bad():
            raise ConfigError("ANTHROPIC_KEY_SECRET_ID", "is not set")

        monkeypatch.setattr(main, "load_config", _bad)
        result = _result(_drain(main.invoke(dict(PAYLOAD), None)))
        assert result["status"] == "failed"
        assert result["error_code"] == "CONFIG_INVALID"
        assert "ANTHROPIC_KEY_SECRET_ID" in result["summary"]
        assert FakeSupabase.instances == []  # no reporter without a key

    @pytest.mark.parametrize(
        "missing", ["SUPABASE_URL", "SUPABASE_KEY_SECRET_ID", "ANTHROPIC_KEY_SECRET_ID", "MODEL_ID"]
    )
    def test_missing_env_var_end_to_end_leaks_no_values(self, monkeypatch, caplog, missing):
        # S-180 edge case (task 1.10): the real load_config against the real
        # env; neither the terminal payload nor the logs carry any env value.
        import config as config_module

        sentinels = {
            "SUPABASE_URL": "https://sentinel-url-7f3a.example",
            "SUPABASE_KEY_SECRET_ID": "sentinel/supabase-7f3a",
            "ANTHROPIC_KEY_SECRET_ID": "sentinel/anthropic-7f3a",
            "PROJECTS_TOKEN_SECRET_ID": "sentinel/projects-7f3a",
            "MODEL_ID": "claude-sonnet-sentinel-7f3a",
            "BOARD_UPDATES_ENABLED": "1",
        }
        for k, v in sentinels.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv(missing)
        monkeypatch.setattr(main, "load_config", config_module.load_config)

        with caplog.at_level("DEBUG"):
            result = _result(_drain(main.invoke(dict(PAYLOAD), None)))

        assert result["error_code"] == "CONFIG_INVALID"
        assert missing in result["summary"]
        emitted = json.dumps(result) + caplog.text
        for name, value in sentinels.items():
            if name != "BOARD_UPDATES_ENABLED":
                assert value not in emitted, f"{name} value leaked"
        assert "Traceback" not in caplog.text

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"run_id": ""},
            {"run_id": 5},
            {"prompt": "not json"},
            {"prompt": json.dumps(["list"])},
            "a string",
        ],
    )
    def test_invalid_payload_returns_failed(self, payload):
        result = _result(_drain(main.invoke(payload, None)))
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_PAYLOAD"
        assert FakeSupabase.instances == []

    def test_credential_error_maps_to_credentials_unavailable(self, monkeypatch):
        def _no_key(secret_id):
            raise CredentialError("SUPABASE_KEY_UNAVAILABLE", "denied")

        monkeypatch.setattr(main, "fetch_supabase_key", _no_key)
        result = _result(_drain(main.invoke(dict(PAYLOAD), None)))
        assert result["status"] == "failed"
        assert result["error_code"] == "CREDENTIALS_UNAVAILABLE"

    def test_unhandled_error_is_reported_scrubbed(self, monkeypatch):
        def _boom(run):
            raise RuntimeError(f"exploded with {SUPABASE_KEY}")

        monkeypatch.setattr(main, "_run_steps", _boom)
        result = _result(_drain(main.invoke(dict(PAYLOAD), None)))
        assert result["status"] == "failed"
        assert result["error_code"] == "UNHANDLED_ERROR"
        assert SUPABASE_KEY not in json.dumps(result)

        db = FakeSupabase.instances[0]
        final = db.run_patches()[-1]
        assert final["status"] == "failed"
        assert final["error_code"] == "UNHANDLED_ERROR"
        assert SUPABASE_KEY not in json.dumps(db.calls)
