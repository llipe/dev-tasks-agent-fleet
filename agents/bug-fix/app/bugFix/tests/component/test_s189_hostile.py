"""L2 hostile-repository tests for the S-189 wrapper git (qa-engineer, S-189
completion gate; D-62, D-63, D-83, D-110).

Two kinds of attacker:

- **the remote** serves trees ``git add`` would never write (``..``, ``.git``,
  a symlink and a directory under one name, setuid modes, newline names),
  built with ``repo_fixtures.push_hostile_tree``;
- **fixer** edits ``/work/repo`` between wrapper calls (nested repositories
  with planted config, symlinked or FIFO ``.gitignore``, hardlinks, a tracked
  directory swapped for a symlink).

Locally every process runs as one user and ``tar`` may be bsdtar, so the
assertions are on what the wrapper reads, writes and stores, not on uids.
QA-189-01 to -03 were pinned with ``xfail(strict=True)``; the S-189 fix round
removed the markers, so the tests must pass.
"""

from __future__ import annotations

import contextlib
import os
import stat
import time
from dataclasses import replace
from pathlib import Path

import pytest

from safe_git import GitError, UnsafeWorkTree
from tests.component.repo_fixtures import (
    StubSandbox,
    helper_git,
    push_hostile_tree,
    result,
    write_blob,
    write_tree,
)
from tests.component.test_git_confinement import World, plant


def _materialized(tmp_path: Path, **kw) -> tuple[World, object]:
    world = World(tmp_path, **kw)
    git = world.git()
    git.materialize(git.base_sha, str(world.work))
    return world, git


def _all_blobs(git, tree: str) -> list[bytes]:
    return [git.blob(sha) for mode, sha in git.ls_tree(tree).values() if mode != "160000"]


# ---------------------------------------------------------------------------
# Hostile trees from the remote
# ---------------------------------------------------------------------------


class TestHostileTrees:
    def test_a_dotdot_entry_is_refused_and_nothing_lands_outside(self, tmp_path):
        world = World(tmp_path)

        def dotdot(src):
            sub = write_tree(src, [("100644", b"pwn.txt", write_blob(src, b"escaped\n"))])
            return [("40000", b"..", sub)]

        push_hostile_tree(world.remote, dotdot)
        # The clone's fsckObjects refuses it first (QA-189-03); _safe_rel is
        # the second line (tests/unit/test_safe_git_paths.py).
        with pytest.raises(GitError, match="unsafe path|git clone failed"):
            git = world.git()
            git.materialize(git.base_sha, str(world.work))
        assert not (world.work.parent / "pwn.txt").exists()
        assert list(world.work.iterdir()) == []

    def test_a_symlink_and_a_directory_under_one_name_never_write_outside(self, tmp_path):
        """A tree with ``zlink -> <outside>`` and ``zlink/b.txt``: whatever the
        tar does with it, nothing is written through the link."""
        world = World(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()

        def dup(src):
            link = write_blob(src, str(outside).encode())
            sub = write_tree(src, [("100644", b"b.txt", write_blob(src, b"through\n"))])
            return [("120000", b"zlink", link), ("40000", b"zlink", sub)]

        push_hostile_tree(world.remote, dup)
        with contextlib.suppress(GitError):  # fsckObjects: duplicateEntries
            git = world.git()
            git.materialize(git.base_sha, str(world.work))
        assert list(outside.iterdir()) == []

    def test_setuid_and_group_write_modes_are_never_extracted(self, tmp_path):
        world = World(tmp_path)

        def modes(src):
            b = write_blob(src, b"#!/bin/sh\n")
            return [("104755", b"suid.sh", b), ("102755", b"sgid.sh", b), ("100664", b"g.txt", b)]

        push_hostile_tree(world.remote, modes)
        git = world.git()
        git.materialize(git.base_sha, str(world.work))
        for name in ("suid.sh", "sgid.sh", "g.txt"):
            mode = stat.S_IMODE(os.lstat(world.work / name).st_mode)
            assert not mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX), (name, oct(mode))
            assert not mode & 0o022, (name, oct(mode))

    def test_a_setuid_bit_set_in_the_work_tree_is_not_captured(self, tmp_path):
        world, git = _materialized(tmp_path)
        p = world.work / "src" / "app.py"
        p.chmod(0o4755)
        tree = git.capture(str(world.work))
        assert git.ls_tree(tree)["src/app.py"][0] == "100755"

    def test_newline_and_long_names_round_trip(self, tmp_path):
        world = World(tmp_path)
        long_name = b"x" * 250

        def names(src):
            b = write_blob(src, b"n\n")
            return [("100644", b"new\nline.txt", b), ("100644", long_name, b)]

        push_hostile_tree(world.remote, names)
        git = world.git()
        git.materialize(git.base_sha, str(world.work))
        assert (world.work / "new\nline.txt").read_bytes() == b"n\n"
        assert (world.work / long_name.decode()).is_file()
        # Compared by content: a hand-written tree's object id need not be
        # the canonical one git writes back.
        assert git.changes(git.tree_of(git.base_sha), git.capture(str(world.work))) == []

    def test_case_colliding_paths_round_trip_on_a_case_sensitive_fs(self, tmp_path):
        probe = tmp_path / "CaseProbe"
        probe.write_text("x")
        if (tmp_path / "caseprobe").exists():
            pytest.skip("case-insensitive filesystem (the image's /work is case-sensitive)")
        world = World(tmp_path, files={"README": "upper\n", "readme": "lower\n"})
        git = world.git()
        git.materialize(git.base_sha, str(world.work))
        assert (world.work / "README").read_text() == "upper\n"
        assert (world.work / "readme").read_text() == "lower\n"
        assert git.capture(str(world.work)) == git.tree_of(git.base_sha)

    def test_gitmodules_with_an_ext_url_never_runs_or_fetches(self, tmp_path):
        """A ``.gitmodules`` naming an ``ext::`` command and a gitlink: the
        clone does not recurse, the gitlink is an empty directory, and the
        command never runs anywhere in the checkout."""
        canary = tmp_path / "submodule-ran"
        world = World(
            tmp_path,
            files={
                ".gitmodules": (
                    f'[submodule "lib"]\n\tpath = vendor/lib\n\turl = ext::sh -c touch% {canary}\n'
                )
            },
        )
        src = world.remote.src
        sha = helper_git("rev-parse", "HEAD", cwd=src)
        helper_git("update-index", "--add", "--cacheinfo", f"160000,{sha},vendor/lib", cwd=src)
        helper_git("commit", "-q", "-m", "submodule", cwd=src)
        helper_git("push", "-q", str(world.remote.bare), "main", cwd=src)
        out = world.checkout(StubSandbox())
        assert out.status == "proceed", out.summary
        assert (world.work / "vendor" / "lib").is_dir()
        assert list((world.work / "vendor" / "lib").iterdir()) == []
        assert not canary.exists()

    @pytest.mark.parametrize("name", [b".git", b".GIT"])
    def test_a_dotgit_tree_entry_is_refused(self, tmp_path, name):
        world = World(tmp_path)

        def dotgit(src):
            cfg = write_blob(src, b"[core]\n\tfsmonitor = touch /nonexistent/x\n")
            return [("40000", name, write_tree(src, [("100644", b"config", cfg)]))]

        push_hostile_tree(world.remote, dotgit)
        with contextlib.suppress(GitError):
            git = world.git()
            git.materialize(git.base_sha, str(world.work))
        assert not any(p.name.lower() == ".git" for p in world.work.iterdir())


# ---------------------------------------------------------------------------
# Hostile work-tree content (fixer) read by the root capture
# ---------------------------------------------------------------------------


class TestHostileWorkTree:
    def test_a_nested_repo_with_planted_config_never_runs(self, tmp_path):
        """A nested repository is read as a gitlink; its hooks, fsmonitor,
        filters, ``core.sshCommand``, ``include.path`` and ``includeIf`` never
        run in the wrapper's capture or diff."""
        world, git = _materialized(tmp_path)
        nested = world.work / "vendor" / "lib"
        nested.mkdir(parents=True)
        (nested / "a.txt").write_text("a\n")
        helper_git("init", "-q", cwd=nested)
        helper_git("add", "-A", cwd=nested)
        helper_git("commit", "-q", "-m", "n", cwd=nested)
        canary_dir = tmp_path / "canaries"
        canaries = plant(nested, canary_dir)
        inc = tmp_path / "included.cfg"
        inc.write_text(f"[core]\n\tfsmonitor = touch {canary_dir / 'inc-fsmonitor'}\n")
        with (nested / ".git" / "config").open("a") as f:
            f.write(
                f"[core]\n\tsshCommand = touch {canary_dir / 'ssh'}\n"
                f"[include]\n\tpath = {inc}\n"
                f'[includeIf "gitdir:/"]\n\tpath = {inc}\n'
            )
        canaries += [canary_dir / "inc-fsmonitor", canary_dir / "ssh"]
        tree = git.capture(str(world.work))
        git.changes(git.base_sha, tree)
        assert git.ls_tree(tree)["vendor/lib"][0] == "160000"
        for c in canaries:
            assert not c.exists(), f"{c.name} ran in the wrapper's git"

    def test_a_gitfile_pointing_at_the_wrapper_clone_is_only_a_gitlink(self, tmp_path):
        world, git = _materialized(tmp_path)
        sub = world.work / "sub"
        sub.mkdir()
        (sub / ".git").write_text(f"gitdir: {world.clone_dir / '.git'}\n")
        (sub / "f.txt").write_text("x\n")
        tree = git.capture(str(world.work))
        entries = git.ls_tree(tree)
        assert entries["sub"][0] == "160000"
        assert not any(p.startswith("sub/") for p in entries)

    def test_a_symlinked_gitignore_is_not_followed(self, tmp_path):
        """If root git followed it, the outside ``*`` would hide new.txt."""
        world, git = _materialized(tmp_path)
        outside = tmp_path / "outside-ignore"
        outside.write_text("*\n")
        os.symlink(outside, world.work / ".gitignore")
        (world.work / "new.txt").write_text("n\n")
        entries = git.ls_tree(git.capture(str(world.work)))
        assert "new.txt" in entries
        assert entries[".gitignore"][0] == "120000"

    def test_a_fifo_file_is_refused_fast_not_read(self, tmp_path):
        """QA-189-02: the lstat walk refuses a FIFO before root git reads the
        tree (it used to be skipped by ``add``; now nothing reads it at all)."""
        world, git = _materialized(tmp_path)
        git.tools = replace(git.tools, timeout=10)
        os.mkfifo(world.work / "pipe")
        started = time.monotonic()
        with pytest.raises(UnsafeWorkTree):
            git.capture(str(world.work))
        assert time.monotonic() - started < 5

    @pytest.mark.parametrize("where", [".gitignore", "src/.gitignore"])
    def test_a_fifo_gitignore_does_not_stall_the_capture(self, tmp_path, where):
        world, git = _materialized(tmp_path)
        git.tools = replace(git.tools, timeout=3)
        os.mkfifo(world.work / where)
        started = time.monotonic()
        with contextlib.suppress(GitError):
            git.capture(str(world.work))
        assert time.monotonic() - started < 2

    def test_a_hardlink_to_a_file_outside_the_tree_is_not_captured(self, tmp_path):
        world, git = _materialized(tmp_path)
        secret = tmp_path / "root-only.txt"
        secret.write_bytes(b"ROOT-ONLY-HARDLINK-CANARY\n")
        os.link(secret, world.work / "leak.txt")
        try:
            tree = git.capture(str(world.work))
        except GitError:
            return
        assert all(b"ROOT-ONLY-HARDLINK-CANARY" not in b for b in _all_blobs(git, tree))


# ---------------------------------------------------------------------------
# restore_base against symlink swaps
# ---------------------------------------------------------------------------


class TestRestoreSymlinkSwaps:
    def test_a_tracked_dir_swapped_for_a_link_outside_is_restored_without_writing_through(
        self, tmp_path
    ):
        world = World(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "app.py").write_text("OUTSIDE\n")

        def swap(call):
            src = Path(call.cwd) / "src"
            for p in src.iterdir():
                p.unlink()
            src.rmdir()
            os.symlink(outside, src)
            return result(0)

        out = world.checkout(StubSandbox(answers={("make", "lint"): swap}))
        assert out.status == "proceed", out.summary
        assert not (world.work / "src").is_symlink()
        assert (world.work / "src" / "app.py").read_text() == (
            world.remote.src / "src" / "app.py"
        ).read_text()
        assert sorted(p.name for p in outside.iterdir()) == ["app.py"]
        assert (outside / "app.py").read_text() == "OUTSIDE\n"

    def test_a_link_chain_out_of_the_tree_is_restored_and_never_followed(self, tmp_path):
        world = World(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()

        def chain(call):
            root = Path(call.cwd)
            os.symlink(outside, root / "hop2")
            os.symlink("hop2", root / "hop1")
            (root / "src" / "app.py").unlink()
            os.symlink("../hop1/app.py", root / "src" / "app.py")
            return result(0)

        out = world.checkout(StubSandbox(answers={("make", "typecheck"): chain}))
        assert out.status == "proceed", out.summary
        assert not (world.work / "hop1").exists()
        assert not (world.work / "hop2").exists()
        assert not (world.work / "src" / "app.py").is_symlink()
        assert list(outside.iterdir()) == []
