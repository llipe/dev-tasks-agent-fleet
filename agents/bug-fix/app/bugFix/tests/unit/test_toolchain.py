"""L1 tests for ``toolchain.py``: stack detection, gate names, Makefile targets
and the repo gate (S-189 AC4, AC5; D-06, D-17, D-18, D-19, D-112).

TC-189-04 (detection table), TC-189-05 (precedence, monorepo root),
TC-189-07 (each missing item named), TC-189-09 (Makefile parsing).

The checks read through a :class:`toolchain.RepoReader`. Here it is
:class:`MapReader`, an in-memory tree, or :class:`toolchain.DirReader` on a
temporary directory; at run time it is ``safe_git.TreeReader`` on the wrapper
clone's base commit.
"""

from __future__ import annotations

import json
import os

import pytest

import toolchain
from toolchain import (
    DEVELOPER_MD,
    DirReader,
    GateMiss,
    Stack,
    ToolchainError,
    check_repo_gate,
    detect_package_manager,
    detect_stack,
    parse_make_targets,
)

DEV = "# developer\n"
GATES = {
    "test": "t",
    "lint": "l",
    "format:check": "f",
    "typecheck": "c",
    "audit": "a",
}
MK_OK = "install:\n\t@true\ntest:\n\t@true\nlint:\n\t@true\nformat-check:\n\t@true\ntypecheck:\n\t@true\naudit:\n\t@true\n"


class MapReader:
    """An in-memory tree: ``{path: text}``."""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    def read_text(self, path: str) -> str | None:
        return self.files.get(path)


def pkg(scripts: dict | None = None, **extra) -> str:
    data: dict = {"name": "x", "version": "1.0.0"}
    if scripts is not None:
        data["scripts"] = scripts
    data.update(extra)
    return json.dumps(data)


def js(scripts=GATES, lock="pnpm-lock.yaml", **extra) -> dict[str, str]:
    files = {DEVELOPER_MD: DEV, "package.json": pkg(scripts, **extra)}
    if lock:
        files[lock] = "lock"
    return files


def py(makefile: str = MK_OK, dev: bool = True) -> dict[str, str]:
    files = {"Makefile": makefile}
    if dev:
        files[DEVELOPER_MD] = DEV
    return files


# ---------------------------------------------------------------------------
# TC-189-04: the detection table
# ---------------------------------------------------------------------------


class TestDetection:
    @pytest.mark.parametrize(
        ("files", "stack", "manager"),
        [
            ({"package.json": pkg(packageManager="pnpm@10.11.0")}, Stack.JS, "pnpm"),
            ({"package.json": pkg(packageManager="npm@10.0.0")}, Stack.JS, "npm"),
            ({"package.json": pkg(), "pnpm-lock.yaml": "x"}, Stack.JS, "pnpm"),
            ({"package.json": pkg(), "package-lock.json": "{}"}, Stack.JS, "npm"),
            ({"Makefile": "test:\n"}, Stack.PYTHON, "make"),
        ],
        ids=["packageManager-pnpm", "packageManager-npm", "pnpm-lock", "npm-lock", "makefile"],
    )
    def test_detection_table(self, files, stack, manager):
        reader = MapReader(files)
        assert detect_stack(reader) is stack
        if stack is Stack.JS:
            assert detect_package_manager(reader) == manager
        gate = check_repo_gate(MapReader({**files, DEVELOPER_MD: DEV}))
        assert gate.toolchain is not None
        assert gate.toolchain.manager == manager

    def test_none_is_not_applicable(self):
        reader = MapReader({DEVELOPER_MD: DEV, "README.md": "x"})
        assert detect_stack(reader) is None
        gate = check_repo_gate(reader)
        assert not gate.ok
        assert gate.toolchain is None
        assert gate.first.item == "package.json or Makefile"
        assert "missing package.json or Makefile" in gate.summary

    def test_packagemanager_field_beats_lockfiles(self):
        reader = MapReader({"package.json": pkg(packageManager="npm@10"), "pnpm-lock.yaml": "x"})
        assert detect_package_manager(reader) == "npm"

    def test_pnpm_lockfile_beats_npm_lockfile(self):
        reader = MapReader(
            {"package.json": pkg(), "pnpm-lock.yaml": "x", "package-lock.json": "{}"}
        )
        assert detect_package_manager(reader) == "pnpm"

    @pytest.mark.parametrize("field", ["yarn@4.1.0", "bun@1", "", 7, None])
    def test_unsupported_packagemanager_falls_through_to_lockfiles(self, field):
        reader = MapReader({"package.json": pkg(packageManager=field), "package-lock.json": "{}"})
        assert detect_package_manager(reader) == "npm"

    def test_no_manager_raises_with_code(self):
        with pytest.raises(ToolchainError) as info:
            detect_package_manager(MapReader({"package.json": pkg()}))
        assert info.value.code == "NO_PACKAGE_MANAGER"

    def test_js_without_a_manager_is_a_lockfile_miss(self):
        gate = check_repo_gate(MapReader(js(lock=None)))
        assert not gate.ok
        assert gate.first == GateMiss("lockfile", "lockfile")
        assert "missing lockfile" in gate.summary

    def test_malformed_package_json_has_no_scripts(self):
        files = js()
        files["package.json"] = "{not json"
        gate = check_repo_gate(MapReader(files))
        assert [m.item for m in gate.missing] == ["test", "lint", "format:check", "typecheck"]

    def test_non_object_package_json_has_no_scripts(self):
        files = js()
        files["package.json"] = "[1, 2]"
        assert check_repo_gate(MapReader(files)).first.item == "test"


# ---------------------------------------------------------------------------
# TC-189-05: precedence and the monorepo root
# ---------------------------------------------------------------------------


class TestPrecedence:
    def test_package_json_wins_over_makefile(self):
        """Pinned: a repo with both is JS/TS; the Makefile is not consulted."""
        files = {**js(), "Makefile": MK_OK}
        assert detect_stack(MapReader(files)) is Stack.JS
        gate = check_repo_gate(MapReader(files))
        assert gate.ok
        assert gate.toolchain.stack is Stack.JS

    def test_package_json_wins_even_when_its_scripts_are_missing(self):
        files = {**js(scripts={}), "Makefile": MK_OK}
        gate = check_repo_gate(MapReader(files))
        assert not gate.ok
        assert gate.first.kind == "script"

    def test_monorepo_root_package_json_is_used(self):
        files = {
            **js(),
            "pnpm-workspace.yaml": "packages:\n  - packages/*\n",
            "packages/a/package.json": pkg({"test": "a"}),
        }
        gate = check_repo_gate(MapReader(files))
        assert gate.ok
        assert gate.toolchain.gate_argv("test") == ["pnpm", "run", "test"]
        assert gate.toolchain.install_argv == ["pnpm", "install", "--frozen-lockfile"]

    def test_a_workspace_package_alone_does_not_satisfy_the_root(self):
        files = {
            DEVELOPER_MD: DEV,
            "package.json": pkg({}),
            "pnpm-lock.yaml": "x",
            "packages/a/package.json": pkg(GATES),
        }
        gate = check_repo_gate(MapReader(files))
        assert not gate.ok
        assert gate.first.item == "test"


# ---------------------------------------------------------------------------
# Gate names and argv (D-19, D-63, D-112)
# ---------------------------------------------------------------------------


class TestGateNames:
    def test_js_gate_names(self):
        tc = check_repo_gate(MapReader(js())).toolchain
        assert tc.gates == {
            "test": "test",
            "lint": "lint",
            "format": "format:check",
            "typecheck": "typecheck",
        }
        assert tc.audit == "audit"

    def test_python_gate_names(self):
        tc = check_repo_gate(MapReader(py())).toolchain
        assert tc.stack is Stack.PYTHON
        assert tc.gates == {
            "test": "test",
            "lint": "lint",
            "format": "format-check",
            "typecheck": "typecheck",
        }
        assert tc.audit == "audit"

    @pytest.mark.parametrize(
        ("lock", "manager", "install"),
        [
            ("pnpm-lock.yaml", "pnpm", ["pnpm", "install", "--frozen-lockfile"]),
            ("package-lock.json", "npm", ["npm", "ci"]),
        ],
    )
    def test_js_argv_per_manager(self, lock, manager, install):
        tc = check_repo_gate(MapReader(js(lock=lock))).toolchain
        assert tc.manager == manager
        assert tc.install_argv == install
        for logical, name in tc.gates.items():
            assert tc.gate_argv(logical) == [manager, "run", name]
        assert tc.gate_argv("audit") == [manager, "run", "audit"]

    def test_npm_install_is_never_plain_install(self):
        """D-63: `npm install --frozen-lockfile` is not an npm flag; npm ci it is."""
        tc = check_repo_gate(MapReader(js(lock="package-lock.json"))).toolchain
        assert tc.install_argv[:2] == ["npm", "ci"]
        assert "install" not in tc.install_argv

    def test_python_argv(self):
        tc = check_repo_gate(MapReader(py())).toolchain
        assert tc.install_argv == ["make", "install"]
        assert tc.gate_argv("format") == ["make", "format-check"]
        assert tc.gate_argv("audit") == ["make", "audit"]

    def test_missing_audit_is_recorded_not_a_miss(self):
        scripts = {k: v for k, v in GATES.items() if k != "audit"}
        gate = check_repo_gate(MapReader(js(scripts)))
        assert gate.ok
        assert gate.toolchain.audit is None
        with pytest.raises(KeyError):
            gate.toolchain.gate_argv("audit")

    def test_python_missing_audit_is_recorded_not_a_miss(self):
        gate = check_repo_gate(MapReader(py(MK_OK.replace("audit:\n\t@true\n", ""))))
        assert gate.ok
        assert gate.toolchain.audit is None

    def test_unknown_gate_raises(self):
        tc = check_repo_gate(MapReader(js())).toolchain
        with pytest.raises(KeyError):
            tc.gate_argv("deploy")

    @pytest.mark.parametrize("value", ["", 3, None, ["x"]])
    def test_a_script_must_be_a_non_empty_string(self, value):
        scripts = dict(GATES)
        scripts["lint"] = value
        gate = check_repo_gate(MapReader(js(scripts)))
        assert gate.first == GateMiss("lint", "script")

    def test_gate_order_is_test_lint_format_typecheck(self):
        assert toolchain.GATE_ORDER == ("test", "lint", "format", "typecheck")


# ---------------------------------------------------------------------------
# TC-189-07: the repo gate names each missing item (AC5)
# ---------------------------------------------------------------------------


class TestRepoGate:
    def test_js_ok(self):
        gate = check_repo_gate(MapReader(js()))
        assert gate.ok
        assert gate.missing == ()
        assert gate.first is None

    def test_python_ok(self):
        assert check_repo_gate(MapReader(py())).ok

    def test_missing_typecheck_script(self):
        scripts = {k: v for k, v in GATES.items() if k != "typecheck"}
        gate = check_repo_gate(MapReader(js(scripts)))
        assert gate.missing == (GateMiss("typecheck", "script"),)
        assert gate.summary == "repo gate: missing script typecheck"

    def test_missing_developer_md(self):
        gate = check_repo_gate(MapReader(py(dev=False)))
        assert gate.first == GateMiss(DEVELOPER_MD, "file")
        assert gate.summary == "repo gate: missing .claude/agents/developer.md"

    def test_format_underscore_target_is_missing_format_check(self):
        gate = check_repo_gate(MapReader(py(MK_OK.replace("format-check", "format_check"))))
        assert gate.missing == (GateMiss("format-check", "target"),)
        assert gate.summary == "repo gate: missing target format-check"

    def test_js_format_dash_script_is_missing_format_colon_check(self):
        scripts = dict(GATES)
        scripts["format-check"] = scripts.pop("format:check")
        gate = check_repo_gate(MapReader(js(scripts)))
        assert gate.missing == (GateMiss("format:check", "script"),)
        assert gate.summary == "repo gate: missing script format:check"

    def test_package_json_with_no_scripts(self):
        gate = check_repo_gate(MapReader(js(scripts=None)))
        assert [m.item for m in gate.missing] == ["test", "lint", "format:check", "typecheck"]
        assert gate.first == GateMiss("test", "script")

    def test_missing_install_target(self):
        """D-112: a Python repo without `make install` is refused, by this text."""
        gate = check_repo_gate(MapReader(py(MK_OK.replace("install:\n\t@true\n", ""))))
        assert gate.missing == (GateMiss("install", "target"),)
        assert gate.first.describe() == "missing install target"
        assert gate.summary == "repo gate: missing install target"

    def test_every_miss_is_listed_in_order(self):
        gate = check_repo_gate(MapReader(py("lint:\n\t@true\n", dev=False)))
        assert [m.describe() for m in gate.missing] == [
            "missing .claude/agents/developer.md",
            "missing target test",
            "missing target format-check",
            "missing target typecheck",
            "missing install target",
        ]
        assert gate.first.item == DEVELOPER_MD

    def test_every_miss_item_is_in_the_refusal_closed_set(self):
        """Every item the gate can name renders in a `repo_gate` reply (D-104)."""
        from refusal import REPO_GATE_ITEMS

        for item in toolchain.MISS_ITEMS:
            assert item in REPO_GATE_ITEMS, item

    def test_developer_md_must_be_a_readable_file(self):
        files = js()
        del files[DEVELOPER_MD]
        files[".claude/agents/developer.MD"] = DEV  # case matters
        assert check_repo_gate(MapReader(files)).first.item == DEVELOPER_MD

    def test_gatemiss_describe_kinds(self):
        assert GateMiss("lint", "script").describe() == "missing script lint"
        assert GateMiss("lint", "target").describe() == "missing target lint"
        assert GateMiss(DEVELOPER_MD, "file").describe() == f"missing {DEVELOPER_MD}"
        assert GateMiss("lockfile", "lockfile").describe() == (
            "missing lockfile (pnpm-lock.yaml or package-lock.json)"
        )
        assert GateMiss("package.json or Makefile", "manifest").describe() == (
            "missing package.json or Makefile"
        )


# ---------------------------------------------------------------------------
# TC-189-09: Makefile target parsing
# ---------------------------------------------------------------------------


class TestMakeTargets:
    def test_plain_targets(self):
        assert parse_make_targets("test:\n\tpytest\nlint: deps\n\truff .\n") >= {"test", "lint"}

    def test_comment_only_target_does_not_count(self):
        assert "test" not in parse_make_targets("# test:\n#\ttest: x\n")

    def test_inline_comment_after_a_target_still_counts(self):
        assert "test" in parse_make_targets("test: ## run the tests\n\tpytest\n")

    def test_phony_only_does_not_count(self):
        targets = parse_make_targets(".PHONY: test lint\n")
        assert "test" not in targets
        assert "lint" not in targets

    def test_double_colon_counts(self):
        assert "test" in parse_make_targets("test::\n\tpytest\n")

    def test_several_targets_on_one_line(self):
        assert {"lint", "typecheck"} <= parse_make_targets("lint typecheck: deps\n\ttrue\n")

    def test_recipe_lines_are_not_targets(self):
        assert "test" not in parse_make_targets("all:\n\ttest: x\n")

    @pytest.mark.parametrize(
        "line",
        [
            "test := x",
            "test ::= x",
            "test :::= x",
            "test ?= x",
            "test = x",
            "test += x",
            "test != x",
        ],
    )
    def test_variable_assignments_are_not_targets(self, line):
        assert "test" not in parse_make_targets(line + "\n")

    def test_target_specific_variable_counts_as_target(self):
        """`test: VAR := x` defines a rule for `test` (a target-specific variable)."""
        assert "test" in parse_make_targets("test: PYTEST_ARGS := -q\n")

    def test_pattern_and_variable_targets_do_not_count(self):
        targets = parse_make_targets("%-check:\n\ttrue\n$(NAME):\n\ttrue\n")
        assert "format-check" not in targets
        assert not any("$" in t or "%" in t for t in targets)

    def test_line_continuation(self):
        assert {"lint", "test"} <= parse_make_targets("lint \\\n  test: deps\n\ttrue\n")

    def test_include_is_not_followed(self):
        """Pinned: a target defined only in an included file does not count.
        The wrapper never evaluates the Makefile (that would run repo code)."""
        targets = parse_make_targets("include rules.mk\n-include more.mk\n")
        assert targets == frozenset()

    def test_format_underscore_is_not_format_dash(self):
        targets = parse_make_targets("format_check:\n\ttrue\n")
        assert "format_check" in targets
        assert "format-check" not in targets

    def test_crlf_makefile(self):
        assert "test" in parse_make_targets("test:\r\n\tpytest\r\n")

    def test_prerequisites_of_a_special_target_do_not_count(self):
        assert "test" not in parse_make_targets(".SUFFIXES: test\n")
        assert "test" not in parse_make_targets("all: test\n")

    def test_define_block_is_skipped(self):
        text = "define RECIPE\ntest:\n\ttrue\nendef\n"
        assert "test" not in parse_make_targets(text)


# ---------------------------------------------------------------------------
# DirReader: regular files only, no symlink anywhere on the path
# ---------------------------------------------------------------------------


class TestDirReader:
    def test_reads_a_regular_file(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        assert DirReader(str(tmp_path)).read_text("package.json") == "{}"

    def test_missing_file_is_none(self, tmp_path):
        assert DirReader(str(tmp_path)).read_text("nope") is None

    def test_symlink_is_none(self, tmp_path):
        (tmp_path / "real.json").write_text("{}")
        os.symlink(tmp_path / "real.json", tmp_path / "package.json")
        assert DirReader(str(tmp_path)).read_text("package.json") is None

    def test_symlinked_parent_is_none(self, tmp_path):
        (tmp_path / "real" / "agents").mkdir(parents=True)
        (tmp_path / "real" / "agents" / "developer.md").write_text(DEV)
        os.symlink(tmp_path / "real", tmp_path / ".claude")
        assert DirReader(str(tmp_path)).read_text(DEVELOPER_MD) is None

    def test_directory_is_none(self, tmp_path):
        (tmp_path / "Makefile").mkdir()
        assert DirReader(str(tmp_path)).read_text("Makefile") is None

    @pytest.mark.parametrize("path", ["../x", "/etc/passwd", "a/../../x", ""])
    def test_paths_outside_the_root_are_refused(self, tmp_path, path):
        assert DirReader(str(tmp_path)).read_text(path) is None

    def test_oversized_file_is_none(self, tmp_path):
        (tmp_path / "package.json").write_bytes(b"x" * (toolchain.MAX_FILE_BYTES + 1))
        assert DirReader(str(tmp_path)).read_text("package.json") is None

    def test_repo_gate_on_a_directory(self, tmp_path):
        (tmp_path / ".claude" / "agents").mkdir(parents=True)
        (tmp_path / DEVELOPER_MD).write_text(DEV)
        (tmp_path / "Makefile").write_text(MK_OK)
        assert check_repo_gate(DirReader(str(tmp_path))).ok
