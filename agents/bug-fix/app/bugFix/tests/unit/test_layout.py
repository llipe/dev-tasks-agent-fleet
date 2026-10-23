"""L1 layout tests (TC-180-01, TC-180-02; S-180 AC1, AC2).

The agent mirrors the sibling layout, its Makefile exposes the canonical
targets plus ``image``, and every module copied from ``security-analyst``
carries a header naming its source path and source commit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]  # agents/bug-fix/app/bugFix
AGENT = PKG.parents[1]  # agents/bug-fix

COPIED = [
    "agent_reporter.py",
    "heartbeat.py",
    "signal_backstop.py",
    "scrubber.py",
    "credentials.py",
]
SOURCE_DIR = "agents/security-analyst/app/securityAnalyst"


@pytest.mark.parametrize(
    "rel",
    [
        "agentcore/agentcore.json",
        "app/bugFix/main.py",
        "app/bugFix/config.py",
        "app/bugFix/Dockerfile",
        "app/bugFix/Makefile",
        "app/bugFix/pyproject.toml",
        "app/bugFix/managed-settings.json",
        "app/bugFix/scripts/image-smoke.sh",
        "README.md",
        "AGENTS.md",
    ],
)
def test_layout_file_exists(rel: str) -> None:
    assert (AGENT / rel).is_file(), f"missing agents/bug-fix/{rel}"


@pytest.mark.parametrize(
    "target",
    [
        "test",
        "test-unit",
        "test-component",
        "lint",
        "format-check",
        "typecheck",
        "audit",
        "validate",
        "image",
        "image-smoke",
    ],
)
def test_makefile_exposes_target(target: str) -> None:
    makefile = (PKG / "Makefile").read_text()
    assert re.search(rf"^{re.escape(target)}:", makefile, re.MULTILINE), (
        f"Makefile has no `{target}` target"
    )


def test_image_smoke_is_executable() -> None:
    script = PKG / "scripts" / "image-smoke.sh"
    assert script.stat().st_mode & 0o111, "image-smoke.sh must be executable"
    assert script.read_text().startswith("#!")


@pytest.mark.parametrize("name", COPIED)
def test_copied_module_has_source_header(name: str) -> None:
    head = "\n".join((PKG / name).read_text().splitlines()[:15])
    assert f"{SOURCE_DIR}/{name}" in head, f"{name}: header must name its source path"
    assert re.search(r"\b[0-9a-f]{7,40}\b", head), (
        f"{name}: header must name a 7-40 hex source commit"
    )


def test_repo_makefile_includes_this_agent() -> None:
    repo_makefile = (AGENT.parents[1] / "Makefile").read_text()
    assert "agents/bug-fix/app/bugFix" in repo_makefile
