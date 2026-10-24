"""L2 tests: the wrapper's git is confined to its own clone (S-189 AC2, AC3;
D-62, D-83, D-110; DF-01, DF-02).

Uid model per D-110: the wrapper runs as root and every ``fixer`` process
starts through the ``setpriv`` drop. Locally the tests run as one user, so
"never runs in the root wrapper's git calls" is shown by canaries: hooks,
``core.fsmonitor``, ``diff.external`` and a filter driver planted in a
``fixer`` repository inside ``/work/repo`` each write a file when run. The
wrapper's git never reads that ``.git``, so no canary appears; a control at
the end proves the plants are live.

TC-189-16 (every wrapper git call is hardened, spawn spy), TC-189-17
(planted hooks and config never run), TC-189-18 (materialize pipes to ``tar``
spawned as ``fixer`` into a fresh dir, byte-equal, no ``.git``), TC-189-20
(``capture()`` includes untracked files, stores symlinks, skips excludes).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from checkout import WorkPaths, run_checkout
from issues import IssuesClient
from safe_git import (
    EXCLUDE_LINES,
    HARDENED_ARGS,
    HARDENED_ENV,
    GitError,
    SafeGit,
    clone,
)
from scrubber import SecretSet
from tests.component.fake_github import APP_ID, TOKEN, FakeGitHub
from tests.component.repo_fixtures import (
    GIT,
    SpawnSpy,
    StubSandbox,
    helper_git,
    make_remote,
    result,
    tree_files,
)

RUN = "0b9a2f4e-1c3d-4e5f-8a6b-7c8d9e0f1a2b"


def _hook(canary: Path, name: str) -> str:
    return f"#!/bin/sh\necho {name} >> '{canary}'\n"


def plant(work: Path, canary_dir: Path) -> list[Path]:
    """Make ``work`` a fixer repository wired to write canaries. Returns the
    canary paths, one per vector."""
    canary_dir.mkdir(exist_ok=True)
    helper_git("init", "-q", cwd=work)
    git_dir = work / ".git"
    canaries: list[Path] = []
    for hook in (
        "post-checkout",
        "pre-commit",
        "pre-auto-gc",
        "post-index-change",
        "reference-transaction",
    ):
        c = canary_dir / f"hook-{hook}"
        p = git_dir / "hooks" / hook
        p.write_text(_hook(c, hook))
        p.chmod(0o755)
        canaries.append(c)
    scripts = {}
    for name in ("fsmonitor", "diffext", "clean", "smudge", "textconv"):
        c = canary_dir / name
        s = canary_dir / f"{name}.sh"
        s.write_text(f"#!/bin/sh\necho {name} >> '{c}'\ncat\n")
        s.chmod(0o755)
        scripts[name] = s
        canaries.append(c)
    with (git_dir / "config").open("a") as f:
        f.write(
            f"[core]\n\tfsmonitor = {scripts['fsmonitor']}\n"
            f"[diff]\n\texternal = {scripts['diffext']}\n"
            f'[filter "x"]\n\tclean = {scripts["clean"]}\n\tsmudge = {scripts["smudge"]}\n'
            f'[diff "x"]\n\ttextconv = {scripts["textconv"]}\n'
        )
    (work / ".gitattributes").write_text("* filter=x diff=x\n")
    return canaries


class World:
    def __init__(self, tmp_path: Path, fixture: str = "py-make-ok", **kw) -> None:
        self.tmp = tmp_path
        self.remote = make_remote(tmp_path, fixture, **kw)
        wrapper = tmp_path / "work" / "wrapper"
        wrapper.mkdir(parents=True, mode=0o700)
        self.work = tmp_path / "work" / "repo"
        self.work.mkdir()
        self.paths = WorkPaths(wrapper_dir=str(wrapper), repo_dir=str(self.work))
        self.clone_dir = Path(self.paths.clone_dir)
        self.spy = SpawnSpy()
        self.secrets = SecretSet()
        self.secrets.add("GITHUB_TOKEN", TOKEN)

    def git(self) -> SafeGit:
        return clone(
            self.remote.url,
            "main",
            str(self.clone_dir),
            tools=self.spy.tools(),
            secrets=self.secrets,
        )

    def checkout(self, sandbox):
        gh = FakeGitHub()
        gh.add_issue(12)
        return run_checkout(
            run_id=RUN,
            owner="o",
            repo="r",
            base_branch="main",
            issue_number=12,
            sandbox=sandbox,
            issues=IssuesClient("o", "r", TOKEN, session=gh),
            secrets=self.secrets,
            token=TOKEN,
            paths=self.paths,
            tools=self.spy.tools(),
            remote_url=self.remote.url,
            app_id=APP_ID,
        )


# ---------------------------------------------------------------------------
# TC-189-16: every wrapper git call is hardened
# ---------------------------------------------------------------------------


def _assert_hardened(world: World) -> None:
    spawns = world.spy.git_spawns()
    assert spawns, "no git call was recorded"
    work = os.path.realpath(world.work)
    git_dir = str(world.clone_dir / ".git")
    for s in spawns:
        argv = s.argv
        assert argv[0] == GIT
        assert s.env is not None, argv
        for key, value in HARDENED_ENV.items():
            assert s.env.get(key) == value, (key, argv)
        assert s.env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert s.env["GIT_CONFIG_GLOBAL"] == "/dev/null"
        assert list(argv[1 : 1 + len(HARDENED_ARGS)]) == list(HARDENED_ARGS), argv
        joined = "\0".join(argv) + "\0" + "\0".join(f"{k}={v}" for k, v in s.env.items())
        assert "core.hooksPath=/dev/null" in argv
        assert "core.fsmonitor=false" in argv
        assert "safe.directory" not in joined
        assert "-C" not in argv
        if s.cwd is not None:
            assert not os.path.realpath(s.cwd).startswith(work), (s.cwd, argv)
        for a in argv:
            if a.startswith("--git-dir="):
                assert a == f"--git-dir={git_dir}", argv
            if a.startswith("--work-tree="):
                assert os.path.realpath(a.split("=", 1)[1]) == work, argv
        # No git call is ever pointed at a .git inside the work tree.
        assert f"{work}{os.sep}.git" not in joined
        assert "GIT_DIR" not in s.env


class TestHardened:
    def test_checkout_capture_and_restore_are_hardened(self, tmp_path):
        world = World(tmp_path)

        def edit(call):
            (Path(call.cwd) / "src" / "app.py").write_text("x\n")
            (Path(call.cwd) / "new.txt").write_text("n\n")
            return result(0)

        out = world.checkout(StubSandbox(answers={("make", "lint"): edit}))
        assert out.status == "proceed", out.summary
        assert out.restored == 2
        _assert_hardened(world)
        # The calls cover the whole path: clone, archive source, capture, diff.
        known = {
            "clone",
            "add",
            "write-tree",
            "diff-tree",
            "read-tree",
            "cat-file",
            "ls-tree",
            "rev-parse",
        }
        names = {a for s in world.spy.git_spawns() for a in s.argv if a in known}
        assert known <= names

    def test_attributes_are_never_read_from_the_work_tree(self, tmp_path):
        world = World(tmp_path)
        world.checkout(StubSandbox())
        for s in world.spy.git_spawns():
            if "clone" in s.argv:
                continue
            assert any(a.startswith("--attr-source=") for a in s.argv), s.argv

    def test_hardening_constants(self):
        assert HARDENED_ARGS[:4] == ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false")
        assert HARDENED_ENV["GIT_CONFIG_NOSYSTEM"] == "1"
        assert HARDENED_ENV["GIT_CONFIG_GLOBAL"] == "/dev/null"
        assert not any("safe.directory" in a for a in HARDENED_ARGS)

    def test_env_is_built_from_scratch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "leak-7f3a")
        monkeypatch.setenv("GIT_DIR", str(tmp_path / "evil"))
        world = World(tmp_path)
        world.git()
        for s in world.spy.git_spawns():
            assert "AWS_SECRET_ACCESS_KEY" not in s.env
            assert "GIT_DIR" not in s.env


# ---------------------------------------------------------------------------
# TC-189-17: planted hooks and config never run
# ---------------------------------------------------------------------------


class TestPlantedRepoNeverRuns:
    def test_through_checkout_restore_and_capture(self, tmp_path):
        world = World(tmp_path)
        canary_dir = tmp_path / "canaries"
        planted: list[Path] = []

        def plant_during_base_gates(call):
            planted.extend(plant(Path(call.cwd), canary_dir))
            (Path(call.cwd) / "src" / "app.py").write_text("changed by a base run\n")
            return result(0)

        out = world.checkout(StubSandbox(answers={("make", "lint"): plant_during_base_gates}))
        assert out.status == "proceed", out.summary
        assert planted
        # Then a capture and a diff on the planted tree, as the validate step will.
        git = out.git
        (world.work / "src" / "app.py").write_text("model edit\n")
        tree = git.capture(str(world.work))
        git.changes(git.base_sha, tree)
        for c in planted:
            assert not c.exists(), f"{c.name} ran in the wrapper's git"

        # Control: the plants are live when git does use that repository.
        helper_git("add", "-A", cwd=world.work)
        assert any(c.exists() for c in planted), "the plants never fire; the test proves nothing"

    def test_restore_leaves_the_fixer_git_dir_alone(self, tmp_path):
        """The restore works on tracked paths only; a fixer `.git` is not
        tracked, so the wrapper neither reads nor deletes it (D-62)."""
        world = World(tmp_path)

        def init(call):
            helper_git("init", "-q", cwd=call.cwd)
            return result(0)

        out = world.checkout(StubSandbox(answers={("make", "lint"): init}))
        assert out.status == "proceed"
        assert (world.work / ".git" / "HEAD").is_file()


# ---------------------------------------------------------------------------
# TC-189-18: materialize as fixer, fresh dir, byte-equal, no .git
# ---------------------------------------------------------------------------


class TestMaterialize:
    def test_tar_runs_as_fixer_into_a_fresh_dir(self, tmp_path):
        world = World(tmp_path)
        git = world.git()
        git.materialize(git.base_sha, str(world.work))
        tars = [s for s in world.spy.fixer_spawns() if Path(s.argv[0]).name == "tar"]
        assert len(tars) == 1
        assert tars[0].kind == "popen"
        assert "-x" in tars[0].argv
        assert str(world.work) in tars[0].argv
        assert tree_files(world.work) == {
            k: v
            for k, v in tree_files(world.remote.src).items()
            if not k.startswith(".git" + os.sep)
        }
        assert not (world.work / ".git").exists()

    def test_a_non_empty_destination_is_refused(self, tmp_path):
        world = World(tmp_path)
        git = world.git()
        (world.work / "x").write_text("x")
        with pytest.raises(GitError, match="not empty"):
            git.materialize(git.base_sha, str(world.work))

    def test_a_symlinked_destination_is_refused(self, tmp_path):
        world = World(tmp_path)
        git = world.git()
        world.work.rmdir()
        target = tmp_path / "elsewhere"
        target.mkdir()
        os.symlink(target, world.work)
        with pytest.raises(GitError):
            git.materialize(git.base_sha, str(world.work))
        assert list(target.iterdir()) == []

    def test_export_attributes_are_not_applied(self, tmp_path):
        """Blobs are streamed raw: export-ignore and export-subst in the
        repo's own .gitattributes can't change the materialized tree."""
        world = World(
            tmp_path,
            "py-make-ok",
            files={
                ".gitattributes": "hidden.txt export-ignore\nsubst.txt export-subst\n",
                "hidden.txt": "h\n",
                "subst.txt": "$Format:%H$\n",
            },
        )
        git = world.git()
        git.materialize(git.base_sha, str(world.work))
        assert (world.work / "hidden.txt").read_text() == "h\n"
        assert (world.work / "subst.txt").read_text() == "$Format:%H$\n"

    def test_symlinks_and_modes_round_trip(self, tmp_path):
        world = World(tmp_path, "py-make-ok")
        src = world.remote.src
        (src / "run.sh").write_text("#!/bin/sh\n")
        (src / "run.sh").chmod(0o755)
        os.symlink("src/app.py", src / "link.py")
        os.symlink("/etc/passwd", src / "abs-link")
        helper_git("add", "-A", cwd=src)
        helper_git("commit", "-q", "-m", "links", cwd=src)
        helper_git("push", "-q", str(world.remote.bare), "main", cwd=src)
        git = world.git()
        git.materialize(git.base_sha, str(world.work))
        assert os.readlink(world.work / "link.py") == "src/app.py"
        assert os.readlink(world.work / "abs-link") == "/etc/passwd"
        assert stat.S_IMODE((world.work / "run.sh").stat().st_mode) & 0o100
        # Capturing the untouched tree gives the base tree back exactly.
        assert git.capture(str(world.work)) == git.tree_of(git.base_sha)

    def test_crlf_and_text_attributes_do_not_change_the_capture(self, tmp_path):
        """Blobs go out raw (no smudge, no eol conversion) and come back raw
        (no clean, no eol conversion): the untouched tree captures as base."""
        world = World(
            tmp_path,
            "py-make-ok",
            files={".gitattributes": "* text eol=crlf\n", "dos.txt": "a\r\nb\r\n"},
        )
        git = world.git()
        git.materialize(git.base_sha, str(world.work))
        blob = git.blob(git.ls_tree(git.base_sha)["dos.txt"][1])
        assert (world.work / "dos.txt").read_bytes() == blob
        assert git.capture(str(world.work)) == git.tree_of(git.base_sha)
        # A CRLF edit is captured byte for byte, not normalized by the attribute.
        (world.work / "dos.txt").write_bytes(b"x\r\ny\r\n")
        tree = git.capture(str(world.work))
        assert git.blob(git.ls_tree(tree)["dos.txt"][1]) == b"x\r\ny\r\n"


# ---------------------------------------------------------------------------
# TC-189-20: capture() includes untracked files, stores symlinks, skips excludes
# ---------------------------------------------------------------------------


class TestCapture:
    def test_untracked_files_are_captured(self, tmp_path):
        world = World(tmp_path)
        git = world.git()
        git.materialize(git.base_sha, str(world.work))
        (world.work / "brand-new.py").write_text("x = 1\n")
        tree = git.capture(str(world.work))
        changes = {c.path: c.status for c in git.changes(git.base_sha, tree)}
        assert changes == {"brand-new.py": "A"}

    def test_symlink_is_stored_as_a_link_without_reading_its_target(self, tmp_path):
        world = World(tmp_path)
        git = world.git()
        git.materialize(git.base_sha, str(world.work))
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP-SECRET-CONTENT\n")
        os.symlink(str(secret), world.work / "leak")
        os.symlink("/nonexistent/target", world.work / "dangling")
        tree = git.capture(str(world.work))
        entries = git.ls_tree(tree)
        mode, sha = entries["leak"]
        assert mode == "120000"
        assert git.blob(sha) == str(secret).encode()
        assert entries["dangling"][0] == "120000"
        for _mode, sha in entries.values():
            assert b"TOP-SECRET-CONTENT" not in git.blob(sha)

    def test_excluded_dependency_dirs_are_skipped(self, tmp_path):
        world = World(tmp_path)
        git = world.git()
        git.materialize(git.base_sha, str(world.work))
        for d in ("node_modules", ".venv", ".pnpm-store", "__pycache__"):
            (world.work / d).mkdir()
            (world.work / d / "f.txt").write_text("x\n")
        (world.work / "dist").mkdir()
        (world.work / "dist" / "out.js").write_text("x\n")
        tree = git.capture(str(world.work))
        paths = {c.path for c in git.changes(git.base_sha, tree)}
        assert paths == {"dist/out.js"}  # dist/ is no longer excluded (D-83)
        assert (
            tuple((world.clone_dir / ".git" / "info" / "exclude").read_text().splitlines())
            == EXCLUDE_LINES
        )

    def test_capture_leaves_the_wrapper_head_at_base(self, tmp_path):
        world = World(tmp_path)
        git = world.git()
        git.materialize(git.base_sha, str(world.work))
        (world.work / "n.txt").write_text("n\n")
        git.capture(str(world.work))
        head = helper_git(
            "--git-dir", str(world.clone_dir / ".git"), "rev-parse", "HEAD", cwd=tmp_path
        )
        assert head == git.base_sha

    def test_nested_repository_is_a_gitlink(self, tmp_path):
        """An embedded repo is recorded, not followed (D-83 rejects it later)."""
        world = World(tmp_path)
        git = world.git()
        git.materialize(git.base_sha, str(world.work))
        nested = world.work / "vendor" / "lib"
        nested.mkdir(parents=True)
        (nested / "a.txt").write_text("a\n")
        helper_git("init", "-q", cwd=nested)
        helper_git("add", "-A", cwd=nested)
        helper_git("commit", "-q", "-m", "n", cwd=nested)
        tree = git.capture(str(world.work))
        entries = git.ls_tree(tree)
        assert entries["vendor/lib"][0] == "160000"
