"""L2 tests for the S-189 fix round (#371, PR #458): the work-tree walk
(QA-189-01, -02), the link-protection preflight, ``.git`` path components and
the clone's ``fsckObjects`` (QA-189-03), and the tar-bomb caps (gap 5).

Real ``git``; ``fixer`` spawns go through :class:`SpawnSpy` as in the other
S-189 component tests.
"""

from __future__ import annotations

import os
import socket
import time
from dataclasses import replace
from pathlib import Path

import pytest

import checkout as checkout_mod
import safe_git
from checkout import CLONE_FAILED
from safe_git import (
    MAX_TAR_BYTES,
    MAX_TAR_ENTRIES,
    GitError,
    TarBombError,
    UnsafeWorkTree,
    check_work_tree,
    link_protection,
)
from tests.component.repo_fixtures import (
    StubSandbox,
    push_hostile_tree,
    result,
    write_blob,
    write_tree,
)
from tests.component.test_checkout import Env, FakeRun
from tests.component.test_git_confinement import World


def _materialized(tmp_path: Path, **kw):
    world = World(tmp_path, **kw)
    git = world.git()
    git.materialize(git.base_sha, str(world.work))
    return world, git


# ---------------------------------------------------------------------------
# QA-189-01 / -02: the lstat walk before every root read of the work tree
# ---------------------------------------------------------------------------


class TestWorkTreeWalk:
    def test_a_clean_materialized_tree_passes(self, tmp_path):
        world, _ = _materialized(tmp_path)
        check_work_tree(str(world.work))

    def test_a_hardlink_between_two_tree_files_is_refused(self, tmp_path):
        world, git = _materialized(tmp_path)
        os.link(world.work / "src" / "app.py", world.work / "copy.py")
        with pytest.raises(UnsafeWorkTree, match="hardlinked"):
            git.capture(str(world.work))

    def test_the_refusal_names_no_path(self, tmp_path):
        """The message is fixed text: a fixer-chosen name never reaches a
        run_event or result.summary."""
        world, git = _materialized(tmp_path)
        secret = tmp_path / "outside.txt"
        secret.write_text("x\n")
        os.link(secret, world.work / "ghp_LEAKY_NAME.txt")
        with pytest.raises(UnsafeWorkTree) as info:
            git.capture(str(world.work))
        assert "ghp_LEAKY_NAME" not in str(info.value)
        assert str(info.value) == "unsafe work tree: 1 hardlinked file(s), 0 special file(s)"

    def test_the_error_is_a_git_error_with_the_clone_failed_code(self):
        assert issubclass(UnsafeWorkTree, GitError)
        assert UnsafeWorkTree.code == CLONE_FAILED

    @pytest.mark.parametrize("where", ["node_modules", "pkg/node_modules", ".venv", "__pycache__"])
    def test_hardlinks_in_excluded_dependency_dirs_are_allowed(self, tmp_path, where):
        """pnpm and uv hardlink from their stores into node_modules/.venv;
        root git never reads those directories (info/exclude, D-83)."""
        world, git = _materialized(tmp_path)
        dep = world.work / where
        dep.mkdir(parents=True)
        store = tmp_path / "store.js"
        store.write_text("module.exports = 1\n")
        os.link(store, dep / "index.js")
        os.mkfifo(dep / "fifo")
        tree = git.capture(str(world.work))
        assert not any(p.startswith(where) for p in git.ls_tree(tree))

    def test_a_fifo_inside_a_nested_dotgit_is_refused(self, tmp_path):
        """git reads a nested repository's HEAD to resolve the gitlink."""
        world, git = _materialized(tmp_path)
        nested = world.work / "vendor" / "lib" / ".git"
        nested.mkdir(parents=True)
        os.mkfifo(nested / "HEAD")
        git.tools = replace(git.tools, timeout=3)
        started = time.monotonic()
        with pytest.raises(UnsafeWorkTree, match="special"):
            git.capture(str(world.work))
        assert time.monotonic() - started < 2

    def test_a_unix_socket_is_refused(self, tmp_path, monkeypatch):
        world, git = _materialized(tmp_path)
        monkeypatch.chdir(world.work)  # AF_UNIX paths are short on macOS
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.bind("sock")
            with pytest.raises(UnsafeWorkTree, match="1 special"):
                git.capture(str(world.work))
        finally:
            s.close()

    @pytest.mark.parametrize(
        ("mode", "nlink", "kind"),
        [
            (0o100644, 1, None),
            (0o100644, 2, "hardlink"),
            (0o040755, 5, None),  # directories always have nlink > 1
            (0o120777, 3, None),  # a symlink is stored as a link, never followed
            (0o010644, 1, "special"),  # FIFO
            (0o140755, 1, "special"),  # socket
            (0o020644, 1, "special"),  # character device
            (0o060644, 1, "special"),  # block device
        ],
    )
    def test_classify_entry(self, mode, nlink, kind):
        assert safe_git.classify_entry(mode, nlink) == kind

    def test_a_symlink_to_a_fifo_outside_is_only_a_link(self, tmp_path):
        world, git = _materialized(tmp_path)
        fifo = tmp_path / "outside-fifo"
        os.mkfifo(fifo)
        os.symlink(fifo, world.work / "link")
        entries = git.ls_tree(git.capture(str(world.work)))
        assert entries["link"][0] == "120000"

    def test_a_base_run_hardlink_ends_the_checkout_clone_failed(self, tmp_path):
        env = Env(tmp_path, "py-make-ok")
        secret = tmp_path / "root-only.txt"
        secret.write_bytes(b"ROOT-ONLY\n")

        def link(call):
            os.link(secret, Path(call.cwd) / "leak.txt")
            return result(0)

        out = env.checkout(StubSandbox(answers={("make", "lint"): link}))
        assert out.status == "failed"
        assert out.error_code == CLONE_FAILED
        assert "unsafe work tree" in out.summary
        assert env.gh.writes() == []

    def test_a_base_run_fifo_ends_the_checkout_fast(self, tmp_path):
        env = Env(tmp_path, "py-make-ok")

        def fifo(call):
            os.mkfifo(Path(call.cwd) / ".gitignore")
            return result(0)

        started = time.monotonic()
        out = env.checkout(StubSandbox(answers={("make", "test"): fifo}))
        assert time.monotonic() - started < 30
        assert out.status == "failed"
        assert out.error_code == CLONE_FAILED
        assert "special file" in out.summary


# ---------------------------------------------------------------------------
# The link-protection preflight (QA-189-01; verified live by #446)
# ---------------------------------------------------------------------------


class TestLinkProtectionPreflight:
    def test_reads_both_sysctls(self, tmp_path):
        (tmp_path / "protected_hardlinks").write_text("1\n")
        (tmp_path / "protected_symlinks").write_text("0\n")
        assert link_protection(str(tmp_path)) == {
            "protected_hardlinks": "1",
            "protected_symlinks": "0",
        }

    def test_a_missing_or_odd_value_is_unavailable(self, tmp_path):
        (tmp_path / "protected_hardlinks").write_text("garbage-that-is-long\n")
        assert link_protection(str(tmp_path)) == {
            "protected_hardlinks": "unavailable",
            "protected_symlinks": "unavailable",
        }

    def test_the_preflight_records_both_values_and_never_fails_on_them(self, tmp_path):
        # S-190: recorded by the run's preflight step (main.py), not checkout.
        proc = tmp_path / "proc-fs"
        proc.mkdir()
        (proc / "protected_hardlinks").write_text("0\n")
        (proc / "protected_symlinks").write_text("0\n")
        run = FakeRun()
        assert checkout_mod.record_link_protection(run, [], str(proc)) == {
            "protected_hardlinks": "0",
            "protected_symlinks": "0",
        }
        events = [e for e in run.events if "fs.protected_hardlinks" in e[1]]
        assert len(events) == 1
        level, msg, data = events[0]
        assert msg == "preflight: fs.protected_hardlinks=0 fs.protected_symlinks=0"
        assert data == {"protected_hardlinks": "0", "protected_symlinks": "0"}
        assert level == "warn"  # 0 is below the expected 1

    def test_expected_values_log_at_info(self, tmp_path):
        proc = tmp_path / "proc-fs"
        proc.mkdir()
        for name in ("protected_hardlinks", "protected_symlinks"):
            (proc / name).write_text("1\n")
        run = FakeRun()
        checkout_mod.record_link_protection(run, [], str(proc))
        events = [e for e in run.events if "fs.protected_hardlinks" in e[1]]
        assert [e[0] for e in events] == ["info"]

    def test_checkout_itself_no_longer_logs_them(self, tmp_path):
        env = Env(tmp_path, "py-make-ok")
        out = env.checkout()
        assert out.status == "proceed", out.summary
        assert not [e for e in env.run.events if "fs.protected_hardlinks" in e[1]]

    def test_checkout_module_uses_the_safe_git_preflight(self):
        assert checkout_mod.link_protection is link_protection


# ---------------------------------------------------------------------------
# QA-189-03: .git components, and fsckObjects on the clone
# ---------------------------------------------------------------------------


class TestDotGit:
    def test_the_clone_turns_on_fsck_objects(self, tmp_path):
        world = World(tmp_path)
        world.git()
        clone_argv = next(s.argv for s in world.spy.git_spawns() if "clone" in s.argv)
        for key in ("transfer.fsckObjects", "fetch.fsckObjects", "receive.fsckObjects"):
            assert f"{key}=true" in clone_argv, key

    @pytest.mark.parametrize("name", [b".git", b".Git", b"git~1", b".git."])
    def test_a_dotgit_tree_entry_never_lands_even_with_fsck_off(self, tmp_path, monkeypatch, name):
        """_safe_rel is the second line: with fsck turned off the materialize
        still refuses before anything is written."""
        monkeypatch.setattr(
            safe_git,
            "CLONE_FSCK_ARGS",
            ("-c", "transfer.fsckObjects=false", "-c", "fetch.fsckObjects=false"),
        )
        world = World(tmp_path)

        def dotgit(src):
            cfg = write_blob(src, b"[core]\n\tfsmonitor = touch /nonexistent/x\n")
            return [("40000", name, write_tree(src, [("100644", b"config", cfg)]))]

        push_hostile_tree(world.remote, dotgit)
        git = world.git()
        with pytest.raises(GitError, match="unsafe path"):
            git.materialize(git.base_sha, str(world.work))
        assert list(world.work.iterdir()) == []


# ---------------------------------------------------------------------------
# Gap 5: tar-bomb caps in materialize
# ---------------------------------------------------------------------------


class TestTarCaps:
    def test_caps_are_the_documented_values(self):
        assert MAX_TAR_ENTRIES == 100_000
        assert MAX_TAR_BYTES == 2 * 1024**3

    def test_too_many_entries_fail_closed_before_tar_runs(self, tmp_path, monkeypatch):
        world = World(tmp_path)
        git = world.git()
        n = len(git.ls_tree(git.base_sha))
        monkeypatch.setattr(safe_git, "MAX_TAR_ENTRIES", n - 1)
        with pytest.raises(TarBombError, match="entries"):
            git.materialize(git.base_sha, str(world.work))
        assert list(world.work.iterdir()) == []
        assert world.spy.fixer_spawns() == []

    def test_too_many_bytes_fail_closed_before_tar_runs(self, tmp_path, monkeypatch):
        world = World(tmp_path)

        def big(src):
            return [("100644", b"big.bin", write_blob(src, b"x" * 4096))]

        push_hostile_tree(world.remote, big)
        git = world.git()
        monkeypatch.setattr(safe_git, "MAX_TAR_BYTES", 4000)
        with pytest.raises(TarBombError, match="bytes"):
            git.materialize(git.base_sha, str(world.work))
        assert list(world.work.iterdir()) == []

    def test_at_the_cap_is_allowed(self, tmp_path, monkeypatch):
        world = World(tmp_path)
        git = world.git()
        n = len(git.ls_tree(git.base_sha))
        monkeypatch.setattr(safe_git, "MAX_TAR_ENTRIES", n)
        assert git.materialize(git.base_sha, str(world.work)) == n

    def test_a_tar_bomb_at_checkout_is_clone_failed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(safe_git, "MAX_TAR_ENTRIES", 1)
        env = Env(tmp_path, "py-make-ok")
        out = env.checkout()
        assert out.status == "failed"
        assert out.error_code == CLONE_FAILED
        assert "tar cap" in out.summary


# ---------------------------------------------------------------------------
# QA-189-04, DF-189-05, DF-189-08 through the real TreeReader and the reply
# ---------------------------------------------------------------------------

_DEV = {".claude/agents/developer.md": "# developer\n"}
_SCRIPTS = '{"name":"x","version":"1.0.0","scripts":{"test":"t","lint":"l","format:check":"f","typecheck":"c"}%s}'
_MK = "install:\n\t@true\ntest:\n\t@true\nlint:\n\t@true\nformat-check:\n\t@true\ntypecheck:\n\t@true\n"


class TestRepoGateFixRound:
    def _refused(self, env):
        out = env.checkout()
        assert out.status == "refused", out.summary
        writes = env.gh.writes()
        assert len(writes) == 1
        return out, writes[0].json["body"]

    def test_a_yarn_repo_is_refused_as_an_unsupported_manager(self, tmp_path):
        files = {**_DEV, "package.json": _SCRIPTS % "", "yarn.lock": "# yarn\n"}
        env = Env(tmp_path, None, files=files)
        out, body = self._refused(env)
        assert "yarn and bun are not supported" in body
        assert "lockfile" not in body
        assert "supported package manager (pnpm or npm)" in out.summary

    def test_a_pnpm_field_without_pnpm_lock_is_refused_before_install(self, tmp_path):
        files = {
            **_DEV,
            "package.json": _SCRIPTS % ',"packageManager":"pnpm@10.11.0"',
            "package-lock.json": "{}",
        }
        env = Env(tmp_path, None, files=files)
        sb = StubSandbox()
        out = env.checkout(sb)
        assert out.status == "refused"
        assert sb.calls == []  # never INSTALL_FAILED (breaker), always the refusal
        assert "`pnpm-lock.yaml` for pnpm" in env.gh.writes()[0].json["body"]

    def test_a_lockfile_over_the_read_cap_still_counts(self, tmp_path):
        """Presence, not content: a 2 MiB pnpm-lock.yaml is a lockfile."""
        big = "lockfileVersion: '9.0'\n" + "# pad\n" * (2 * 1024 * 1024 // 6)
        env = Env(tmp_path, "js-pnpm-ok", files={"pnpm-lock.yaml": big})
        out = env.checkout()
        assert out.status == "proceed", out.summary

    def test_python_without_install_replies_missing_install_target(self, tmp_path):
        env = Env(tmp_path, "py-no-install")
        _, body = self._refused(env)
        assert "this repository is missing install target (the Makefile target `install`)" in body

    def test_a_gnumakefile_beside_a_makefile_is_the_one_judged(self, tmp_path):
        files = {**_DEV, "Makefile": _MK, "GNUmakefile": "test:\n\t@true\n"}
        env = Env(tmp_path, None, files=files)
        out, _ = self._refused(env)
        assert out.repo_gate is not None
        assert {m.item for m in out.repo_gate.missing} == {
            "lint",
            "format-check",
            "typecheck",
            "install",
        }

    def test_a_gnumakefile_alone_passes(self, tmp_path):
        env = Env(tmp_path, None, files={**_DEV, "GNUmakefile": _MK})
        out = env.checkout()
        assert out.status == "proceed", out.summary

    def test_tree_reader_exists_sees_symlinks_and_big_blobs(self, tmp_path):
        world = World(tmp_path, files={"big.txt": "x" * (2 * 1024 * 1024)})
        os.symlink("Makefile", world.remote.src / "GNUmakefile")
        from tests.component.repo_fixtures import helper_git

        helper_git("add", "-A", cwd=world.remote.src)
        helper_git("commit", "-q", "-m", "l", cwd=world.remote.src)
        helper_git("push", "-q", str(world.remote.bare), "main", cwd=world.remote.src)
        git = world.git()
        reader = git.reader(git.base_sha)
        assert reader.exists("GNUmakefile") and reader.read_text("GNUmakefile") is None
        assert reader.exists("big.txt") and reader.read_text("big.txt") is None
        assert not reader.exists("makefile")
        assert not reader.exists(".git")
