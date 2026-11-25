"""
S-204 AC1/AC2 — package layout and dependency pins (TC-204-01..03); S-216 AC10
(TC-216-51, TC-216-52): the Bedrock review path is gone and ``anthropic`` is pinned.

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

SIBLING_DEPS = {"bedrock-agentcore", "boto3", "requests", "PyJWT", "cryptography"}
EXPECTED_DEPS = {*SIBLING_DEPS, "anthropic"}  # D-80

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


def test_dependencies_are_the_five_sibling_pins_plus_anthropic():
    """TC-216-52 (port of TC-204-02): six exact pins; five at the sibling's versions."""
    ours = _pins(PKG / "pyproject.toml")
    sibling = _pins(SIBLING / "pyproject.toml")
    assert set(ours) == EXPECTED_DEPS
    for name in SIBLING_DEPS:
        assert ours[name] == sibling[name], f"{name} pinned {ours[name]} != sibling {sibling[name]}"
    assert re.fullmatch(r"\d+\.\d+\.\d+", ours["anthropic"])


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


# ---------------------------------------------------------------------------
# S-216 AC10 — no Bedrock review path (TC-216-51)
# ---------------------------------------------------------------------------

REMOVED = [
    "bedrock_adapter.py",
    "tests/unit/test_bedrock_adapter.py",
    "tests/unit/test_bedrock_hostile.py",
    "tests/unit/test_properties_bedrock.py",
    "tests/helpers/bedrock_run.py",
]

# The context-selection call keeps its Bedrock client until S-217 (#481), which
# deletes these and empties this set. ``tests/fixtures/bedrock.py`` serves the
# selection tests until then.
SELECTION_RESIDUAL = {"legacy_bedrock.py", "context/selection.py", "pipeline.py"}


@pytest.mark.parametrize("name", REMOVED)
def test_bedrock_review_files_are_gone(name):
    assert not (PKG / name).exists()


def _model_sources():
    for path in _source_files():
        rel = path.relative_to(PKG).as_posix()
        if rel.startswith("tests/"):
            continue
        yield rel, path.read_text()


def test_no_bedrock_review_code_outside_the_selection_residual():
    offenders = []
    for rel, text in _model_sources():
        if rel in SELECTION_RESIDUAL:
            continue
        for needle in (
            "bedrock-runtime",
            "converse(",
            "BedrockAdapterError",
            "BEDROCK_",
            "bedrock_adapter",
        ):
            if needle in text:
                offenders.append((rel, needle))
    assert offenders == []


def test_legacy_bedrock_is_imported_only_by_the_selection_path():
    importers = []
    for rel, text in _model_sources():
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "legacy_bedrock":
                importers.append(rel)
    assert sorted(set(importers)) == ["context/selection.py", "pipeline.py"]


def test_boto3_is_imported_only_for_secrets_and_the_selection_residual():
    """``boto3`` reads Secrets Manager in ``credentials.py``; the selection's Bedrock
    client is the S-217 residual. No model code imports botocore's ``ClientError``."""
    importers = set()
    for rel, text in _model_sources():
        tree = ast.parse(text)
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            if any(m.split(".")[0] in {"boto3", "botocore"} for m in mods):
                importers.add(rel)
    assert importers == {"credentials.py", "legacy_bedrock.py", "context/selection.py"}
