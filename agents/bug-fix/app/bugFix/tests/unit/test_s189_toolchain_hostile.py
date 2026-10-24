"""L1 hostile and edge cases for ``toolchain.py`` (qa-engineer, S-189
completion gate; FR-6, D-63, D-112).

The repo gate reads repo-controlled text as root, so parsing must never
execute anything, and the gate argv must come from the fixed gate names only,
whatever the repository says. QA-189-04 (a ``packageManager`` field without
its lockfile passes the gate) is pinned with ``xfail(strict=True)``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import toolchain
from tests.unit.test_toolchain import GATES, MK_OK, MapReader, js, pkg, py
from toolchain import (
    DEVELOPER_MD,
    INSTALL_ARGV,
    LOCKFILE_ITEM,
    Stack,
    check_repo_gate,
    parse_make_targets,
)

_SPAWNERS = {"subprocess", "os.system", "os.popen", "os.exec", "os.spawn", "pty", "shlex"}


def test_toolchain_imports_nothing_that_can_spawn():
    """Static parsing only (TC-189-09): no process API is even imported."""
    tree = ast.parse(Path(toolchain.__file__).read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            names.add(f"{node.value.id}.{node.attr}")
    assert not {n for n in names if any(n.startswith(s) for s in _SPAWNERS)}


HOSTILE_MAKEFILE = (
    "include /etc/passwd extra.mk\n"
    "-include $(shell touch /tmp/never-included)\n"
    "X != touch /tmp/never-bang\n"
    "Y = $(shell touch /tmp/never-shell)\n"
    "Z = $(Z) recursive $(Z)\n"
    "$(shell touch /tmp/never-target):\n"
    "test;rm -rf /: ; @true\n"
    "lint$(Y): ; @true\n"
    "`touch x`: ; @true\n"
    ".PHONY: install test lint format-check typecheck\n"
    "test: ; @true\n"
)


def test_hostile_makefile_text_yields_only_literal_targets():
    targets = parse_make_targets(HOSTILE_MAKEFILE)
    assert "test" in targets
    assert "install" not in targets  # named only in .PHONY
    assert "lint" not in targets  # only through a variable
    assert not any("$" in t for t in targets)
    # The gate never runs a name from the Makefile: the argv is the fixed name.
    gate = check_repo_gate(MapReader(py(HOSTILE_MAKEFILE)))
    assert {m.item for m in gate.missing} == {"lint", "format-check", "typecheck", "install"}
    assert gate.toolchain is not None
    assert gate.toolchain.gate_argv("test") == ["make", "test"]


@pytest.mark.parametrize(
    "line",
    ["test&: ; @true", "test lint &: ; @true"],
)
def test_grouped_target_syntax_does_not_crash(line):
    parse_make_targets(line + "\n")


def test_huge_makefile_parses_bounded():
    text = "a := b\n" * 100_000 + MK_OK
    assert "install" in parse_make_targets(text)


def test_odd_characters_in_package_scripts_never_reach_the_argv():
    scripts = {**GATES, "test; rm -rf /": "x", "lint && curl evil": "y"}
    gate = check_repo_gate(MapReader(js(scripts)))
    assert gate.ok
    tc = gate.toolchain
    assert tc is not None
    for logical in ("test", "lint", "format", "typecheck", "audit"):
        argv = tc.gate_argv(logical)
        assert argv[:2] == ["pnpm", "run"]
        assert argv[2] in {"test", "lint", "format:check", "typecheck", "audit"}
    assert tc.install_argv == list(INSTALL_ARGV["pnpm"])


def test_both_package_json_and_makefile_use_js_and_ignore_make_install():
    files = {**js(), "Makefile": MK_OK}
    gate = check_repo_gate(MapReader(files))
    assert gate.ok and gate.toolchain is not None
    assert gate.toolchain.stack is Stack.JS
    assert gate.toolchain.install_argv == ["pnpm", "install", "--frozen-lockfile"]


def test_js_without_any_lockfile_or_field_is_a_lockfile_miss():
    gate = check_repo_gate(MapReader(js(lock=None)))
    assert [m.item for m in gate.missing] == [LOCKFILE_ITEM]
    assert gate.toolchain is None


def test_python_without_install_is_the_d112_miss():
    mk = MK_OK.replace("install:\n\t@true\n", "")
    gate = check_repo_gate(MapReader(py(mk)))
    assert [m.describe() for m in gate.missing] == ["missing install target"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-189-04: detect_package_manager returns the `packageManager` field "
        "without checking that the manager's lockfile exists, so a JS repo with "
        "`packageManager` and no (or the other manager's) lockfile passes the repo "
        "gate; the frozen install then fails and the run ends INSTALL_FAILED "
        "(counted by the breaker) instead of refusal repo_gate 'lockfile', the "
        "item refusal.REPO_GATE_ITEMS added for 'no lockfile for a frozen install "
        "(D-63)'. Expected: the lockfile miss whenever the chosen manager's "
        "lockfile is absent."
    ),
)
@pytest.mark.parametrize(
    ("field", "lock"),
    [("pnpm@9.1.0", None), ("npm@10.8.0", None), ("npm@10.8.0", "pnpm-lock.yaml")],
)
def test_package_manager_field_without_its_lockfile_is_a_lockfile_miss(field, lock):
    files = {DEVELOPER_MD: "# d\n", "package.json": pkg(GATES, packageManager=field)}
    if lock:
        files[lock] = "lock"
    gate = check_repo_gate(MapReader(files))
    assert LOCKFILE_ITEM in [m.item for m in gate.missing]
