"""L1 tests for the typed env config (TC-180-13, TC-180-14, D-50, D-99, DF-36).

``load_config`` reads the runtime env into a frozen ``Config``. A missing or
invalid required variable raises ``ConfigError`` naming the variable, and no
env value (sentinel) ever appears in the message, ``repr`` or the traceback.
A missing Projects token secret ID disables the board, never the run (FR-34).
"""

from __future__ import annotations

import traceback

import pytest

import config
from config import REQUIRED_VARS, Config, ConfigError, load_config

SENTINELS = {
    "SUPABASE_URL": "https://sentinel-supabase-url.example",
    "SUPABASE_KEY_SECRET_ID": "sentinel/supabase-secret-id",
    "ANTHROPIC_KEY_SECRET_ID": "sentinel/anthropic-secret-id",
    "PROJECTS_TOKEN_SECRET_ID": "sentinel/projects-secret-id",
    "BOARD_UPDATES_ENABLED": "1",
    "MODEL_ID": "claude-sonnet-4-6-sentinel",
}


def _env(**overrides: str | None) -> dict[str, str]:
    env = dict(SENTINELS)
    for k, v in overrides.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v
    return env


def _no_values_in(text: str, env: dict[str, str]) -> None:
    for name, value in env.items():
        if name == "BOARD_UPDATES_ENABLED":
            continue  # "1"/"0" are too short to be meaningful sentinels
        assert value not in text, f"value of {name} leaked into: {text!r}"


class TestReads:
    def test_reads_every_variable(self):
        cfg = load_config(_env())
        assert isinstance(cfg, Config)
        assert cfg.supabase_url == SENTINELS["SUPABASE_URL"]
        assert cfg.supabase_key_secret_id == SENTINELS["SUPABASE_KEY_SECRET_ID"]
        assert cfg.anthropic_key_secret_id == SENTINELS["ANTHROPIC_KEY_SECRET_ID"]
        assert cfg.projects_token_secret_id == SENTINELS["PROJECTS_TOKEN_SECRET_ID"]
        assert cfg.model_id == SENTINELS["MODEL_ID"]
        assert cfg.board_updates_enabled is True
        assert cfg.board_disabled_reason is None

    def test_config_is_frozen(self):
        cfg = load_config(_env())
        with pytest.raises(AttributeError):
            cfg.model_id = "other"  # type: ignore[misc]

    def test_reads_process_env_by_default(self, monkeypatch):
        for k, v in _env().items():
            monkeypatch.setenv(k, v)
        assert load_config().model_id == SENTINELS["MODEL_ID"]

    def test_values_are_stripped(self):
        cfg = load_config(_env(MODEL_ID="  claude-sonnet-4-6  "))
        assert cfg.model_id == "claude-sonnet-4-6"

    def test_repr_hides_nothing_secret_but_is_safe(self):
        # Secret IDs are not secrets, but the repr must still be printable
        # without raising and must not include a value that is not an ID.
        assert "Config(" in repr(load_config(_env()))

    def test_required_vars_list(self):
        assert set(REQUIRED_VARS) == {
            "SUPABASE_URL",
            "SUPABASE_KEY_SECRET_ID",
            "ANTHROPIC_KEY_SECRET_ID",
            "MODEL_ID",
        }


class TestBoardFlag:
    @pytest.mark.parametrize(("raw", "enabled"), [("1", True), ("0", False)])
    def test_flag_values(self, raw, enabled):
        cfg = load_config(_env(BOARD_UPDATES_ENABLED=raw))
        assert cfg.board_updates_enabled is enabled
        assert (cfg.board_disabled_reason is None) is enabled

    def test_flag_off_reason(self):
        assert load_config(_env(BOARD_UPDATES_ENABLED="0")).board_disabled_reason == "flag_off"

    def test_flag_unset_disables_board(self):
        cfg = load_config(_env(BOARD_UPDATES_ENABLED=None))
        assert cfg.board_updates_enabled is False
        assert cfg.board_disabled_reason == "flag_off"

    @pytest.mark.parametrize("raw", ["true", "yes", "2", "on", "1 1", "-1", "enabled-sentinel-xyz"])
    def test_invalid_flag_is_typed_error(self, raw):
        with pytest.raises(ConfigError) as info:
            load_config(_env(BOARD_UPDATES_ENABLED=raw))
        assert info.value.variable == "BOARD_UPDATES_ENABLED"
        # Never echo the raw value (short values like "2" can't be checked
        # meaningfully, so the long sentinel carries this assertion).
        assert "enabled-sentinel-xyz" not in str(info.value)
        assert "enabled-sentinel-xyz" not in repr(info.value)

    def test_missing_projects_token_id_disables_board_not_run(self):
        # DF-36 recommendation, FR-34: best effort, never a ConfigError.
        cfg = load_config(_env(PROJECTS_TOKEN_SECRET_ID=None))
        assert cfg.projects_token_secret_id is None
        assert cfg.board_updates_enabled is False
        assert cfg.board_disabled_reason == "no_token_secret_id"

    def test_blank_projects_token_id_disables_board(self):
        cfg = load_config(_env(PROJECTS_TOKEN_SECRET_ID="   "))
        assert cfg.board_disabled_reason == "no_token_secret_id"


class TestMissingRequired:
    @pytest.mark.parametrize("name", ["MODEL_ID", "SUPABASE_URL", "SUPABASE_KEY_SECRET_ID", "ANTHROPIC_KEY_SECRET_ID"])
    def test_missing_var_raises_typed_error_naming_it(self, name):
        env = _env(**{name: None})
        with pytest.raises(ConfigError) as info:
            load_config(env)
        err = info.value
        assert err.variable == name
        assert name in str(err)
        _no_values_in(str(err), env)
        _no_values_in(repr(err), env)
        tb = "".join(traceback.format_exception(err))
        _no_values_in(tb, env)

    @pytest.mark.parametrize("name", ["MODEL_ID", "SUPABASE_URL", "SUPABASE_KEY_SECRET_ID", "ANTHROPIC_KEY_SECRET_ID"])
    def test_blank_var_counts_as_missing(self, name):
        with pytest.raises(ConfigError) as info:
            load_config(_env(**{name: "   "}))
        assert info.value.variable == name

    def test_config_error_is_value_error_subclass(self):
        assert issubclass(ConfigError, ValueError)

    def test_first_missing_in_declared_order(self):
        with pytest.raises(ConfigError) as info:
            load_config({})
        assert info.value.variable == REQUIRED_VARS[0]

    def test_error_chain_carries_no_values(self):
        # ``raise ... from None``: no KeyError context holding the env mapping.
        with pytest.raises(ConfigError) as info:
            load_config(_env(MODEL_ID=None))
        assert info.value.__cause__ is None
        assert info.value.__suppress_context__ is True


class TestModelId:
    @pytest.mark.parametrize(
        "model_id",
        [
            "us.anthropic.claude-sonnet-4-6",
            "eu.anthropic.claude-sonnet-4-6",
            "apac.anthropic.claude-sonnet-4-6",
            "anthropic.claude-3-5-sonnet-20240620-v1:0",
        ],
    )
    def test_provider_profile_ids_are_rejected(self, model_id):
        # D-50: the CLI talks to the Anthropic API, so a cloud inference
        # profile id is a config fault, reported without echoing the value.
        with pytest.raises(ConfigError) as info:
            load_config(_env(MODEL_ID=model_id))
        assert info.value.variable == "MODEL_ID"
        assert model_id not in str(info.value)

    def test_plain_sonnet_id_is_accepted(self):
        assert load_config(_env(MODEL_ID="claude-sonnet-4-6")).model_id == "claude-sonnet-4-6"


class TestClocks:
    def test_max_lifetime_matches_agentcore(self):
        # The seed's max_runtime_seconds (S-184) must equal this (research Q7).
        assert config.MAX_LIFETIME == 3600

    def test_heartbeat_well_below_idle(self):
        assert 0 < config.HEARTBEAT_INTERVAL <= config.IDLE_SESSION_TIMEOUT / 2
        assert config.IDLE_SESSION_TIMEOUT <= config.MAX_LIFETIME
