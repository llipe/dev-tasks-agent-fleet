"""L1 tests for ``agentcore.json`` and secret hygiene (TC-180-03..05; S-180 AC3).

Runtime ``bug_fix`` (Container, PUBLIC, maxLifetime 3600) with the eight env
vars (``PANEL_BASE_URL`` added by S-188, ``FIX_LOOP_ENABLED=0`` by S-190), secret IDs only, and no reference to the cloud model provider anywhere
in the runtime config, ``config.py`` or the Dockerfile (D-50, D-99).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import config

PKG = Path(__file__).resolve().parents[2]
AGENT = PKG.parents[1]
AGENTCORE = AGENT / "agentcore" / "agentcore.json"


def _runtime() -> dict:
    doc = json.loads(AGENTCORE.read_text())
    runtimes = doc["runtimes"]
    assert len(runtimes) == 1
    return runtimes[0]


def _env() -> dict[str, str]:
    return {e["name"]: e["value"] for e in _runtime()["envVars"]}


# S-182 spike window (D-70, D-110): infra-engineer committed ALLOW_PROBE=1 for
# the deployed probe runs, and it stays until the re-probe; task 3.10 removes
# it. While it is there, the "never committed" test is a strict xfail; once it
# is gone the condition is false and the test guards again unchanged.
PROBE_WINDOW = "ALLOW_PROBE" in AGENTCORE.read_text()


class TestRuntime:
    def test_runtime_shape(self):
        rt = _runtime()
        assert rt["name"] == "bug_fix"
        assert rt["build"] == "Container"
        assert rt["networkMode"] == "PUBLIC"
        assert rt["codeLocation"] == "app/bugFix/"
        assert rt["entrypoint"] == "main.py"

    def test_max_lifetime_is_3600_and_matches_config(self):
        life = _runtime()["lifecycleConfiguration"]
        assert life["maxLifetime"] == 3600
        assert life["maxLifetime"] == config.MAX_LIFETIME
        assert life["idleRuntimeSessionTimeout"] == config.IDLE_SESSION_TIMEOUT

    @pytest.mark.parametrize("source", ["migration", "seed.sql"])
    def test_seed_max_runtime_seconds_equals_max_lifetime(self, source: str):
        # TC-184-04 (S-184 AC2, research Q7): the seed's max_runtime_seconds
        # MUST equal maxLifetime, in the migration and in seed.sql.
        repo = AGENT.parents[1]
        if source == "migration":
            found = sorted((repo / "supabase" / "migrations").glob("*_seed_bug_fix_agent.sql"))
            assert len(found) == 1
            sql = found[0].read_text()
        else:
            sql = (repo / "supabase" / "seed.sql").read_text()
        stmt = sql[sql.index("'bug-fix',") :]
        stmt = stmt[: stmt.index("on conflict (slug)")]
        match = re.search(r"\b(\d+),\s*-- max_runtime_seconds", stmt)
        assert match, f"no max_runtime_seconds in the {source} bug-fix row"
        assert int(match.group(1)) == _runtime()["lifecycleConfiguration"]["maxLifetime"]

    def test_env_vars(self):
        env = _env()
        if PROBE_WINDOW:
            assert env.pop("ALLOW_PROBE") == "1"
        assert set(env) == {
            "SUPABASE_URL",
            "SUPABASE_KEY_SECRET_ID",
            "ANTHROPIC_KEY_SECRET_ID",
            "PROJECTS_TOKEN_SECRET_ID",
            "BOARD_UPDATES_ENABLED",
            "MODEL_ID",
            "PANEL_BASE_URL",
            "FIX_LOOP_ENABLED",
        }
        assert env["SUPABASE_URL"].startswith("https://")
        assert env["SUPABASE_KEY_SECRET_ID"] == "agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY"
        assert env["ANTHROPIC_KEY_SECRET_ID"] == "agent-fleet/prod/ANTHROPIC_API_KEY"
        assert env["PROJECTS_TOKEN_SECRET_ID"] == "agent-fleet/prod/GITHUB_PROJECTS_TOKEN"
        assert env["BOARD_UPDATES_ENABLED"] == "1"
        # S-188 (task 9.3): the panel origin that builds the run link.
        assert env["PANEL_BASE_URL"] == "https://dt-agent-fleet-panel.fly.dev"
        # S-190 (task 11.5): Wave A ships with the fix loop off, so a run that
        # wins its claim disposes "fix loop not yet enabled".
        assert env["FIX_LOOP_ENABLED"] == "0"

    def test_the_fix_loop_flag_is_the_last_one_line_entry(self):
        # A minimal add (11.5): one new line, after the S-188 entry.
        names = [e["name"] for e in _runtime()["envVars"]]
        assert names[-2:] == ["PANEL_BASE_URL", "FIX_LOOP_ENABLED"]
        line = '{ "name": "FIX_LOOP_ENABLED", "value": "0" }'
        assert line in AGENTCORE.read_text()

    def test_env_vars_keep_one_entry_per_line(self):
        # The file is edited by hand and by the agentcore CLI: one env entry
        # per line keeps a diff to the entry it changes.
        lines = [ln.strip() for ln in AGENTCORE.read_text().splitlines()]
        for name in _env():
            matches = [ln for ln in lines if f'"name": "{name}"' in ln]
            assert len(matches) == 1, name
            assert matches[0].startswith("{ ") and matches[0].rstrip(",").endswith(" }"), name

    def test_model_id_is_an_anthropic_api_sonnet_id(self):
        model = _env()["MODEL_ID"]
        assert re.fullmatch(r"claude-sonnet-[0-9a-z-]+", model), model
        assert not re.match(r"^(us|eu|apac)\.anthropic\.", model)
        assert not model.startswith("anthropic.")

    def test_env_loads_through_config(self):
        cfg = config.load_config(_env())
        assert cfg.fix_loop_enabled is False
        assert cfg.board_updates_enabled is True
        assert cfg.panel_base_url == "https://dt-agent-fleet-panel.fly.dev"

    @pytest.mark.xfail(
        PROBE_WINDOW,
        reason="S-182 spike window: ALLOW_PROBE=1 is committed until task 3.10 (D-110)",
        strict=True,
    )
    def test_probe_flag_is_never_committed(self):
        # TC-182-13 (D-70): ALLOW_PROBE is set only for the spike, by
        # infra-engineer on the deployed runtime, and unset after (task 3.10).
        assert "ALLOW_PROBE" not in _env()
        assert "ALLOW_PROBE" not in AGENTCORE.read_text()


PROVIDER_FREE = [AGENTCORE, PKG / "config.py", PKG / "Dockerfile"]


@pytest.mark.parametrize("path", PROVIDER_FREE, ids=lambda p: p.name)
def test_no_cloud_model_provider_reference(path: Path) -> None:
    # D-50: the model is served by the Anthropic API, never the cloud provider.
    assert "bedrock" not in path.read_text().lower()


SECRET_SHAPES = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
]

SECRET_FREE = [
    AGENTCORE,
    PKG / "Dockerfile",
    PKG / "managed-settings.json",
    PKG / "srt-settings.json",
    PKG / "config.py",
    AGENT / "README.md",
]


@pytest.mark.parametrize("path", SECRET_FREE, ids=lambda p: p.name)
def test_no_secret_material(path: Path) -> None:
    text = path.read_text()
    for shape in SECRET_SHAPES:
        assert not shape.search(text), f"{path.name} contains secret-shaped text ({shape.pattern})"
