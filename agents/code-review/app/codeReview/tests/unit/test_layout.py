"""
S-204 AC1/AC2 — package layout and dependency pins (TC-204-01..03).

The package mirrors the security-analyst sibling (D-20): the shared modules are
copied, not imported across agents, and the dependency set is the sibling's
minus everything this agent does not use (no Strands loop, D-07; no scanners).
"""

from __future__ import annotations

import ast
import importlib
import re
import tomllib
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
SIBLING = PKG.parents[2] / "security-analyst" / "app" / "securityAnalyst"

EXPECTED_FILES = [
    "main.py",
    "config.py",
    "agent_reporter.py",
    "credentials.py",
    "heartbeat.py",
    "signal_backstop.py",
    "scrubber.py",
    "Makefile",
    "Dockerfile",
    ".dockerignore",
    "pyproject.toml",
]

COPIED_MODULES = ["agent_reporter", "credentials", "heartbeat", "signal_backstop", "scrubber"]

EXPECTED_DEPS = {"bedrock-agentcore", "boto3", "requests", "PyJWT", "cryptography"}

FORBIDDEN_DEPS = {"strands-agents", "semgrep", "checkov"}

_REQ = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*==\s*([^\s;]+)")


def _pins(pyproject: Path) -> dict[str, str]:
    data = tomllib.loads(pyproject.read_text())
    out: dict[str, str] = {}
    for spec in data["project"]["dependencies"]:
        m = _REQ.match(spec)
        assert m, f"dependency not pinned with ==: {spec!r}"
        out[m.group(1)] = m.group(2)
    return out


@pytest.mark.parametrize("name", EXPECTED_FILES)
def test_expected_file_exists(name):
    assert (PKG / name).is_file(), f"missing {name}"


@pytest.mark.parametrize("module", ["main", "config", *COPIED_MODULES])
def test_module_imports_cleanly(module):
    importlib.import_module(module)


def test_agent_reporter_is_byte_identical_to_sibling():
    assert (PKG / "agent_reporter.py").read_bytes() == (SIBLING / "agent_reporter.py").read_bytes()


def _public_defs(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {
        n.name
        for n in tree.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and not n.name.startswith("_")
    }


@pytest.mark.parametrize("module", ["heartbeat", "signal_backstop", "scrubber", "credentials"])
def test_copied_module_keeps_sibling_surface(module):
    """D-20: the sibling modules are copied, not imported across agents.

    Only ``agent_reporter.py`` is pinned byte-identical (vendored SDK). The other
    copies may diverge later for this agent's needs, but start with at least the
    sibling's public surface.
    """
    ours = _public_defs(PKG / f"{module}.py")
    assert _public_defs(SIBLING / f"{module}.py") <= ours


def test_dependencies_are_exactly_the_five_sibling_pins():
    ours = _pins(PKG / "pyproject.toml")
    sibling = _pins(SIBLING / "pyproject.toml")
    assert set(ours) == EXPECTED_DEPS
    for name in EXPECTED_DEPS:
        assert ours[name] == sibling[name], f"{name} pinned {ours[name]} != sibling {sibling[name]}"


def test_no_forbidden_dependencies():
    data = tomllib.loads((PKG / "pyproject.toml").read_text())
    all_specs = list(data["project"]["dependencies"])
    for extra in data["project"].get("optional-dependencies", {}).values():
        all_specs.extend(extra)
    names = {re.split(r"[\s=<>~!\[;]", s.strip(), maxsplit=1)[0].lower() for s in all_specs}
    assert names.isdisjoint(FORBIDDEN_DEPS)


def _source_files():
    for path in PKG.rglob("*.py"):
        rel = path.relative_to(PKG)
        if rel.parts[0] in {".venv", "build", "dist"}:
            continue
        yield path


def test_no_strands_import_anywhere():
    offenders = []
    for path in _source_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            else:
                continue
            if any(m == "strands" or m.startswith("strands.") for m in mods):
                offenders.append(str(path.relative_to(PKG)))
    assert offenders == []


@pytest.mark.parametrize(
    "toolchain", ["semgrep", "checkov", "gitleaks", "trivy", "codeql", "rustc", "cargo"]
)
def test_dockerfile_installs_no_scanner_toolchain(toolchain):
    lines = [
        ln
        for ln in (PKG / "Dockerfile").read_text().splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    assert not any(toolchain in ln.lower() for ln in lines), f"Dockerfile mentions {toolchain}"


def test_dockerfile_uses_sibling_base_image_and_entrypoint():
    text = (PKG / "Dockerfile").read_text()
    assert "FROM public.ecr.aws/docker/library/python:3.13-slim" in text
    assert 'CMD ["python", "main.py"]' in text


def test_dockerignore_excludes_tests_and_venv():
    entries = {ln.strip() for ln in (PKG / ".dockerignore").read_text().splitlines()}
    assert "tests/" in entries
    assert ".venv/" in entries
