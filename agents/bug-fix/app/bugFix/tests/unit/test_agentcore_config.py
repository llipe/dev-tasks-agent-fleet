"""L1 tests for ``agentcore.json`` and secret hygiene (TC-180-03..05; S-180 AC3).

Runtime ``bug_fix`` (Container, PUBLIC, maxLifetime 3600) with the six env
vars, secret IDs only, and no reference to the cloud model provider anywhere
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

    def test_env_vars(self):
        env = _env()
        assert set(env) == {
            "SUPABASE_URL",
            "SUPABASE_KEY_SECRET_ID",
            "ANTHROPIC_KEY_SECRET_ID",
            "PROJECTS_TOKEN_SECRET_ID",
            "BOARD_UPDATES_ENABLED",
            "MODEL_ID",
        }
        assert env["SUPABASE_URL"].startswith("https://")
        assert env["SUPABASE_KEY_SECRET_ID"] == "agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY"
        assert env["ANTHROPIC_KEY_SECRET_ID"] == "agent-fleet/prod/ANTHROPIC_API_KEY"
        assert env["PROJECTS_TOKEN_SECRET_ID"] == "agent-fleet/prod/GITHUB_PROJECTS_TOKEN"
        assert env["BOARD_UPDATES_ENABLED"] == "1"

    def test_model_id_is_an_anthropic_api_sonnet_id(self):
        model = _env()["MODEL_ID"]
        assert re.fullmatch(r"claude-sonnet-[0-9a-z-]+", model), model
        assert not re.match(r"^(us|eu|apac)\.anthropic\.", model)
        assert not model.startswith("anthropic.")

    def test_env_loads_through_config(self):
        cfg = config.load_config(_env())
        assert cfg.board_updates_enabled is True


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
    PKG / "config.py",
    AGENT / "README.md",
]


@pytest.mark.parametrize("path", SECRET_FREE, ids=lambda p: p.name)
def test_no_secret_material(path: Path) -> None:
    text = path.read_text()
    for shape in SECRET_SHAPES:
        assert not shape.search(text), f"{path.name} contains secret-shaped text ({shape.pattern})"
