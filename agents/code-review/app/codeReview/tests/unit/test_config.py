"""
S-204 AC4 — clock invariant and environment settings (TC-204-12, TC-204-13; D-32, D-29).

Invariant (spec §8.9, ADR-006)::

    run_timeout_seconds <= IDLE_SESSION_TIMEOUT (900) <= MAX_LIFETIME (1800)
                        <= REAPER_THRESHOLD_SECONDS (MAX_LIFETIME + grace)
    0 < HEARTBEAT_INTERVAL <= IDLE_SESSION_TIMEOUT / 2
    DEADLINE_RESERVE_SECONDS < run_timeout_seconds
"""

from __future__ import annotations

import dataclasses

import pytest

import config
from config import (
    DEADLINE_RESERVE_SECONDS,
    GRACE_SECONDS,
    HEARTBEAT_INTERVAL,
    IDLE_SESSION_TIMEOUT,
    MAX_LIFETIME,
    PARAMS_SCHEMA,
    REAPER_THRESHOLD_SECONDS,
    RUN_TIMEOUT_MAX_SECONDS,
    ClockConsistencyError,
    ConfigError,
    Settings,
    assert_clock_invariant,
    load_settings,
)

# ---------------------------------------------------------------------------
# TC-204-12 — clock invariant
# ---------------------------------------------------------------------------


class TestShippedClocks:
    def test_shipped_configuration_is_consistent(self):
        assert_clock_invariant()

    def test_shipped_values_match_spec_8_9(self):
        assert RUN_TIMEOUT_MAX_SECONDS == 900
        assert IDLE_SESSION_TIMEOUT == 900
        assert MAX_LIFETIME == 1800
        assert HEARTBEAT_INTERVAL == 120
        assert DEADLINE_RESERVE_SECONDS == 60
        assert GRACE_SECONDS == 120
        assert REAPER_THRESHOLD_SECONDS == MAX_LIFETIME + GRACE_SECONDS

    def test_run_timeout_cap_comes_from_the_params_schema(self):
        assert PARAMS_SCHEMA["properties"]["run_timeout_seconds"]["maximum"] == (
            RUN_TIMEOUT_MAX_SECONDS
        )


class TestInvariantPasses:
    @pytest.mark.parametrize("run_timeout", [120, 600, 899, 900])
    def test_every_allowed_run_timeout_passes(self, run_timeout):
        assert_clock_invariant(run_timeout_seconds=run_timeout)

    def test_boundary_equalities_pass(self):
        # run == idle, idle == lifetime, lifetime == reaper are all allowed.
        assert_clock_invariant(
            run_timeout_seconds=900,
            idle_session_timeout=900,
            max_lifetime=900,
            reaper_threshold_seconds=900,
            heartbeat_interval=450,
        )


class TestInvariantFails:
    def test_run_timeout_above_idle_fails(self):
        with pytest.raises(ClockConsistencyError, match=r"run_timeout_seconds \(901\)"):
            assert_clock_invariant(run_timeout_seconds=901)

    def test_idle_above_lifetime_fails(self):
        with pytest.raises(ClockConsistencyError, match=r"IDLE_SESSION_TIMEOUT \(1801\)"):
            assert_clock_invariant(idle_session_timeout=1801)

    def test_lifetime_above_reaper_fails(self):
        with pytest.raises(ClockConsistencyError, match=r"MAX_LIFETIME \(1800\)"):
            assert_clock_invariant(reaper_threshold_seconds=1799)

    @pytest.mark.parametrize("hb", [0, -1])
    def test_non_positive_heartbeat_fails(self, hb):
        with pytest.raises(ClockConsistencyError, match="HEARTBEAT_INTERVAL"):
            assert_clock_invariant(heartbeat_interval=hb)

    def test_heartbeat_above_half_idle_fails(self):
        with pytest.raises(ClockConsistencyError, match="HEARTBEAT_INTERVAL"):
            assert_clock_invariant(heartbeat_interval=451)

    def test_run_timeout_not_above_reserve_fails(self):
        with pytest.raises(ClockConsistencyError, match="DEADLINE_RESERVE_SECONDS"):
            assert_clock_invariant(run_timeout_seconds=60)

    def test_error_is_a_value_error(self):
        assert issubclass(ClockConsistencyError, ValueError)


# ---------------------------------------------------------------------------
# TC-204-13 — environment settings
# ---------------------------------------------------------------------------

REQUIRED = ["SUPABASE_URL", "SUPABASE_KEY_SECRET_ID", "MODEL_ID", "PANEL_BASE_URL"]


def _env(**overrides: str) -> dict[str, str]:
    env = {
        "SUPABASE_URL": "https://sentinel-supabase.example",
        "SUPABASE_KEY_SECRET_ID": "sentinel-secret-id-7f3a",
        "MODEL_ID": "sentinel-model-id-91c2",
        "PANEL_BASE_URL": "https://sentinel-panel.example",
    }
    env.update(overrides)
    return env


class TestLoadSettings:
    def test_reads_required_vars(self):
        s = load_settings(_env())
        assert isinstance(s, Settings)
        assert s.supabase_url == "https://sentinel-supabase.example"
        assert s.supabase_key_secret_id == "sentinel-secret-id-7f3a"
        assert s.model_id == "sentinel-model-id-91c2"
        assert s.panel_base_url == "https://sentinel-panel.example"

    def test_retired_price_vars_are_not_read(self):
        """TC-216-45 (D-87): ``PRICE_*`` are retired; garbage there is ignored."""
        s = load_settings(_env(PRICE_INPUT_PER_MTOK="abc-sentinel", PRICE_OUTPUT_PER_MTOK="nan"))
        assert not hasattr(s, "price_input_per_mtok")
        assert not hasattr(s, "price_output_per_mtok")
        assert {f.name for f in dataclasses.fields(Settings)}.isdisjoint(
            {"price_input_per_mtok", "price_output_per_mtok"}
        )

    def test_anthropic_key_secret_id_defaults(self):
        """TC-216-46 (D-88): the key's secret ID, default when unset or blank."""
        assert load_settings(_env()).anthropic_api_key_secret_id == (
            "agent-fleet/prod/ANTHROPIC_API_KEY"
        )
        assert load_settings(
            _env(ANTHROPIC_API_KEY_SECRET_ID="  ")
        ).anthropic_api_key_secret_id == ("agent-fleet/prod/ANTHROPIC_API_KEY")

    def test_anthropic_key_secret_id_is_read(self):
        s = load_settings(_env(ANTHROPIC_API_KEY_SECRET_ID="agent-fleet/dev/ANTHROPIC_API_KEY"))
        assert s.anthropic_api_key_secret_id == "agent-fleet/dev/ANTHROPIC_API_KEY"

    def test_the_api_key_itself_is_never_a_setting(self):
        """D-88: settings hold the secret ID only, never ``ANTHROPIC_API_KEY``."""
        s = load_settings(_env(ANTHROPIC_API_KEY="sk-ant-api03-sentinel"))
        assert "sk-ant-api03-sentinel" not in repr(s)

    def test_price_table_is_the_d87_constant(self):
        assert config.MODEL_PRICES == {"claude-sonnet-5-5": (2.0, 10.0)}

    def test_panel_base_url_trailing_slash_is_stripped(self):
        s = load_settings(_env(PANEL_BASE_URL="https://panel.example/"))
        assert s.panel_base_url == "https://panel.example"

    def test_run_url_joins_panel_base_and_run_id(self):
        s = load_settings(_env(PANEL_BASE_URL="https://panel.example/"))
        assert s.run_url("abc") == "https://panel.example/runs/abc"

    @pytest.mark.parametrize("var", REQUIRED)
    def test_missing_required_var_names_it(self, var):
        env = _env()
        del env[var]
        with pytest.raises(ConfigError) as exc_info:
            load_settings(env)
        assert exc_info.value.var == var
        assert var in str(exc_info.value)

    @pytest.mark.parametrize("var", REQUIRED)
    def test_blank_required_var_is_missing(self, var):
        with pytest.raises(ConfigError) as exc_info:
            load_settings(_env(**{var: "   "}))
        assert exc_info.value.var == var

    @pytest.mark.parametrize("var", REQUIRED)
    def test_error_message_leaks_no_other_values(self, var):
        env = _env()
        del env[var]
        with pytest.raises(ConfigError) as exc_info:
            load_settings(env)
        text = str(exc_info.value) + repr(exc_info.value)
        assert "sentinel" not in text

    def test_defaults_to_process_environment(self, monkeypatch):
        for k, v in _env().items():
            monkeypatch.setenv(k, v)
        assert load_settings().model_id == "sentinel-model-id-91c2"

    def test_config_error_is_a_value_error(self):
        assert issubclass(ConfigError, ValueError)


def test_module_constants_used_by_copied_credentials_exist():
    # credentials.py (copied from the sibling) imports these names.
    assert isinstance(config.SUPABASE_URL, str)
    assert isinstance(config.SUPABASE_KEY_SECRET_ID, str)
    assert isinstance(config.TOKEN_STALE_THRESHOLD_MINUTES, float)
