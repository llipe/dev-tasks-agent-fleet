"""L1 tests for ``safe_git.py`` (S-189 AC2; D-62; TC-189-16 static half).

- A static check: no agent module but ``safe_git.py`` spawns ``git``.
- The pure helpers: branch-name validation, the clone's auth env, the raw
  ``diff-tree`` parser, and the git command shape.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest

import safe_git
from safe_git import (
    HARDENED_ARGS,
    HARDENED_ENV,
    Change,
    GitError,
    GitTools,
    auth_env,
    git_env,
    parse_raw_diff,
    validate_branch,
)

PKG = Path(__file__).resolve().parents[2]

# Modules allowed to name the git binary:
# - safe_git.py: the wrapper's only git runner (D-62);
# - probe_inner.py: runs as fixer *inside* the sandbox (S-182 probe helper),
#   on a scratch repository of its own; it is never wrapper git.
GIT_ALLOWED = {"safe_git.py", "probe_inner.py"}
# An argv element or call argument ("git", / "git"] / "git")), or any absolute
# git path. A dict key such as {"git": ...} is not a spawn.
_GIT_SPAWN = re.compile(r"""["']git["']\s*[,\])]|["'](?:/usr/local/bin/|/usr/bin/|/bin/)git["']""")


@pytest.mark.parametrize(
    "path",
    sorted(p for p in PKG.glob("*.py") if p.name not in GIT_ALLOWED),
    ids=lambda p: p.name,
)
def test_no_git_subprocess_outside_safe_git(path: Path) -> None:
    text = path.read_text()
    assert not _GIT_SPAWN.search(text), f"{path.name} names the git binary; use safe_git.py"
    assert "GIT_DIR" not in text, f"{path.name} sets GIT_DIR; use safe_git.py"


@pytest.mark.parametrize(
    "line",
    ['subprocess.run(["git", "status"])', "cmd = ['git']", 'which("git")', 'GIT = "/usr/bin/git"'],
)
def test_the_pattern_catches_spawn_shapes(line: str) -> None:
    assert _GIT_SPAWN.search(line)


def test_the_scan_finds_the_module_set() -> None:
    names = {p.name for p in PKG.glob("*.py")}
    assert {"safe_git.py", "checkout.py", "gates.py", "toolchain.py"} <= names


def test_safe_git_never_sets_safe_directory() -> None:
    text = (PKG / "safe_git.py").read_text()
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    # Mentioned only in the docstring, never as a config value.
    assert "safe.directory=" not in code


class TestCommandShape:
    def test_env_is_hardened_and_minimal(self):
        env = git_env()
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert set(env) == set(HARDENED_ENV)

    def test_extra_env_is_merged(self):
        env = git_env({"GIT_CONFIG_COUNT": "1"})
        assert env["GIT_CONFIG_COUNT"] == "1"
        assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"

    def test_hardened_args_lead_every_command(self):
        git = safe_git.SafeGit("/work/wrapper/repo", tools=GitTools(git="/usr/bin/git"))
        cmd = git.command("status", work_tree="/work/repo")
        assert cmd[0] == "/usr/bin/git"
        assert tuple(cmd[1 : 1 + len(HARDENED_ARGS)]) == HARDENED_ARGS
        assert "--git-dir=/work/wrapper/repo/.git" in cmd
        assert "--work-tree=/work/repo" in cmd
        assert cmd[-1] == "status"

    def test_default_tools_are_the_image_paths(self):
        tools = GitTools()
        assert tools.git == "/usr/bin/git"
        assert tools.tar == "/usr/bin/tar"
        assert tools.rm == "/usr/bin/rm"
        assert tools.fixer_prefix[0] == "/usr/bin/setpriv"
        assert "--reuid=10002" in tools.fixer_prefix
        assert tools.fixer_prefix[-1] == "/app/fixer_exec.py"


class TestBranch:
    @pytest.mark.parametrize("name", ["main", "release/1.2", "feature_x-y", "v1.0"])
    def test_ordinary_names_pass(self, name):
        assert validate_branch(name) == name

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "-x",
            "--upload-pack=x",
            "a..b",
            "a b",
            "a\nb",
            "a~1",
            "a^",
            "a:b",
            "a?",
            "a*",
            "a[",
            "a\\b",
            "/a",
            "a/",
            "a//b",
            "a.lock",
            "a/.b",
            ".a",
            "a@{1}",
            "@",
            "x" * 300,
            7,
            None,
        ],
    )
    def test_hostile_or_invalid_names_raise(self, name):
        with pytest.raises(GitError):
            validate_branch(name)


class TestAuth:
    def test_auth_env_is_a_github_scoped_extraheader(self):
        env = auth_env("ghs_" + "T" * 36)
        assert env["GIT_CONFIG_COUNT"] == "1"
        assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
        value = env["GIT_CONFIG_VALUE_0"]
        assert value.startswith("AUTHORIZATION: basic ")
        assert base64.b64decode(value.split()[-1]).decode() == "x-access-token:ghs_" + "T" * 36

    def test_no_token_no_env(self):
        assert auth_env(None) == {}
        assert auth_env("") == {}


class TestRawDiff:
    def test_parses_statuses_and_paths(self):
        raw = (
            ":100644 100644 aaaa bbbb M\0src/a.py\0"
            ":000000 100644 0000 cccc A\0new file.txt\0"
            ":100644 000000 dddd 0000 D\0gone.txt\0"
            ":100644 120000 eeee ffff T\0swap\0"
        )
        assert parse_raw_diff(raw) == [
            Change("M", "src/a.py", "100644", "100644"),
            Change("A", "new file.txt", "000000", "100644"),
            Change("D", "gone.txt", "100644", "000000"),
            Change("T", "swap", "100644", "120000"),
        ]

    def test_empty(self):
        assert parse_raw_diff("") == []

    def test_malformed_raises(self):
        with pytest.raises(GitError):
            parse_raw_diff(":100644 100644 aaaa\0x\0")
        with pytest.raises(GitError):
            parse_raw_diff(":100644 100644 aaaa bbbb M\0")

    def test_change_tracked_in_base(self):
        assert Change("M", "a", "100644", "100644").in_base
        assert not Change("A", "a", "000000", "100644").in_base
        assert Change("D", "a", "100644", "000000").in_base
