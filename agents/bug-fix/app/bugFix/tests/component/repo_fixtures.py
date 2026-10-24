"""Helpers for the S-189 L2 tests: fixture remotes, sandbox doubles, a spawn spy.

- :func:`make_remote` commits a fixture tree from ``tests/fixtures/repos`` with
  real ``git`` and serves it as a local bare remote (``file://``).
- :class:`StubSandbox` answers ``Sandbox.run`` with scripted results and
  records every call (TC-189-11).
- :class:`LocalSandbox` runs the command for real, as the current user, with
  npm and pnpm forced offline, so install and base-gate runs are real without
  network (TC-189-14, TC-189-15).
- :class:`SpawnSpy` stands in for ``subprocess.run``/``Popen`` in
  ``safe_git``: it records every argv, env and cwd, checks that every
  non-git spawn starts with the production ``setpriv`` drop, then strips that
  prefix and runs the rest as the current user (TC-189-16, TC-189-18).

The test helpers run ``git`` themselves to build fixtures; that is test
scaffolding, not wrapper git, and the static check in
``tests/unit/test_safe_git.py`` scans agent modules only.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from safe_git import GitTools
from sandbox import DEFAULT_PATHS, Mode, Outcome, SandboxResult, fixer_prefix, map_exit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "repos"
GIT = shutil.which("git") or "/usr/bin/git"
TAR = shutil.which("tar") or "/usr/bin/tar"
RM = shutil.which("rm") or "/bin/rm"
PROD_PREFIX: tuple[str, ...] = tuple(fixer_prefix(DEFAULT_PATHS))

_HELPER_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_AUTHOR_NAME": "Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    "GIT_AUTHOR_DATE": "2026-10-24T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-10-24T00:00:00Z",
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "HOME": "/nonexistent",
}


def helper_git(*args: str, cwd: str | Path) -> str:
    """Test scaffolding git (fixture setup only)."""
    return subprocess.run(
        [GIT, *args], cwd=cwd, env=_HELPER_ENV, check=True, capture_output=True, text=True
    ).stdout.strip()


@dataclass
class Remote:
    url: str
    head: str
    src: Path
    bare: Path


def make_remote(
    tmp_path: Path,
    fixture: str | None = None,
    *,
    files: dict[str, str] | None = None,
    branch: str = "main",
    commits: int = 1,
) -> Remote:
    """A bare remote holding ``fixture`` (or ``files``) on ``branch``.

    ``commits > 1`` adds empty commits first, so a shallow clone is observable.
    """
    src = tmp_path / "src"
    if fixture is not None:
        shutil.copytree(FIXTURES / fixture, src)
    else:
        src.mkdir()
    for rel, text in (files or {}).items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    helper_git("init", "-q", "-b", branch, cwd=src)
    for i in range(commits - 1):
        helper_git("commit", "-q", "--allow-empty", "-m", f"history {i}", cwd=src)
    helper_git("add", "-A", cwd=src)
    helper_git("commit", "-q", "--allow-empty", "-m", "fixture", cwd=src)
    head = helper_git("rev-parse", "HEAD", cwd=src)
    bare = tmp_path / "remote.git"
    helper_git("clone", "-q", "--bare", str(src), str(bare), cwd=tmp_path)
    return Remote(url=bare.as_uri(), head=head, src=src, bare=bare)


# ---------------------------------------------------------------------------
# Sandbox doubles
# ---------------------------------------------------------------------------


@dataclass
class SandboxCall:
    argv: tuple[str, ...]
    cwd: str
    timeout: float
    mode: Mode
    anthropic_api_key: str | None


def result(code: int | None = 0, stdout: str = "", stderr: str = "", timed_out: bool = False):
    return SandboxResult(
        outcome=map_exit(code, timed_out),
        exit_code=code,
        timed_out=timed_out,
        stdout=stdout,
        stderr=stderr,
        duration_s=0.01,
    )


@dataclass
class StubSandbox:
    """``Sandbox.run`` double. ``answers`` maps an argv (tuple) to a
    :class:`SandboxResult`, an exception, or a callable taking the call."""

    answers: dict[tuple[str, ...], Any] = field(default_factory=dict)
    default: SandboxResult = field(default_factory=lambda: result(0, "ok\n"))
    calls: list[SandboxCall] = field(default_factory=list)

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str,
        timeout: float,
        mode: Mode = Mode.SCRIPT,
        anthropic_api_key: str | None = None,
        stdin: bytes | None = None,
        max_output: int = 64 * 1024,
    ) -> SandboxResult:
        call = SandboxCall(tuple(argv), cwd, timeout, mode, anthropic_api_key)
        self.calls.append(call)
        answer = self.answers.get(tuple(argv), self.default)
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return answer(call)
        return answer

    def argvs(self) -> list[tuple[str, ...]]:
        return [c.argv for c in self.calls]


@dataclass
class LocalSandbox(StubSandbox):
    """Runs every command for real, as the current user, offline."""

    def run(self, argv, *, cwd, timeout, mode=Mode.SCRIPT, anthropic_api_key=None, **_: Any):
        self.calls.append(SandboxCall(tuple(argv), cwd, timeout, mode, anthropic_api_key))
        # HOME outside the work tree, as /home/fixer is in the image: npm and
        # pnpm write caches and logs there.
        home = tempfile.mkdtemp(prefix="fixer-home-")
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": home,
            "CI": "1",
            "LANG": "C.UTF-8",
            "npm_config_offline": "true",
            "npm_config_update_notifier": "false",
            "npm_config_fund": "false",
            "npm_config_audit": "false",
        }
        try:
            proc = subprocess.run(
                list(argv), cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return result(None, timed_out=True)
        return result(proc.returncode, proc.stdout, proc.stderr)


def has(binary: str) -> bool:
    return shutil.which(binary) is not None


# ---------------------------------------------------------------------------
# The spawn spy for safe_git
# ---------------------------------------------------------------------------


@dataclass
class Spawn:
    kind: str  # "run" or "popen"
    argv: list[str]
    env: dict[str, str] | None
    cwd: str | None
    as_fixer: bool


class SpawnSpy:
    """Records every spawn ``safe_git`` makes, then runs it as the current user.

    A spawn that starts with the production ``setpriv`` prefix is recorded as
    ``as_fixer`` and run without it; anything else must be the git binary
    (the wrapper's own git) or the spy fails the test.
    """

    def __init__(self, prefix: Sequence[str] = PROD_PREFIX) -> None:
        self.prefix = list(prefix)
        self.spawns: list[Spawn] = []

    def _strip(self, kind: str, argv: Sequence[str], kwargs: dict) -> list[str]:
        argv = list(argv)
        as_fixer = argv[: len(self.prefix)] == self.prefix
        if as_fixer:
            argv = argv[len(self.prefix) :]
        else:
            assert argv[0] == GIT, f"a non-git spawn without the setpriv drop: {argv}"
        self.spawns.append(Spawn(kind, list(argv), kwargs.get("env"), kwargs.get("cwd"), as_fixer))
        if as_fixer:
            # As fixer_exec.py does: the env is rebuilt; nothing of the wrapper's.
            kwargs["env"] = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C"}
        return argv

    def run(self, argv: Sequence[str], **kwargs: Any) -> Any:
        return subprocess.run(self._strip("run", argv, kwargs), **kwargs)

    def popen(self, argv: Sequence[str], **kwargs: Any) -> Any:
        return subprocess.Popen(self._strip("popen", argv, kwargs), **kwargs)

    def git_spawns(self) -> list[Spawn]:
        return [s for s in self.spawns if not s.as_fixer]

    def fixer_spawns(self) -> list[Spawn]:
        return [s for s in self.spawns if s.as_fixer]

    def tools(self, **overrides: Any) -> GitTools:
        kwargs: dict[str, Any] = {
            "git": GIT,
            "tar": TAR,
            "rm": RM,
            "fixer_prefix": tuple(self.prefix),
            "run": self.run,
            "popen": self.popen,
        }
        kwargs.update(overrides)
        return GitTools(**kwargs)


def tree_files(root: Path) -> dict[str, bytes]:
    """``{relative path: bytes}`` of every regular file under ``root``."""
    out: dict[str, bytes] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            p = Path(dirpath) / name
            if p.is_symlink():
                continue
            out[str(p.relative_to(root))] = p.read_bytes()
    return out


def all_files(root: Path) -> list[Path]:
    return [Path(d) / f for d, _, fs in os.walk(root) for f in fs]


RunCallable = Callable[..., Any]
__all__ = [
    "FIXTURES",
    "GIT",
    "PROD_PREFIX",
    "LocalSandbox",
    "Outcome",
    "Remote",
    "SpawnSpy",
    "StubSandbox",
    "all_files",
    "has",
    "helper_git",
    "make_remote",
    "result",
    "tree_files",
]
