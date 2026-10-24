"""L2 fault paths of ``safe_git.py`` (S-189; D-62): every failure is a
scrubbed :class:`GitError`, never a raw exception, a hang, or a partial write
through a symlink.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import safe_git
from safe_git import GitError, GitTools, SafeGit, TreeReader, clone
from tests.component.fake_github import TOKEN
from tests.component.repo_fixtures import GIT, SpawnSpy, helper_git, make_remote


@pytest.fixture
def world(tmp_path):
    remote = make_remote(tmp_path, "py-make-ok")
    wrapper = tmp_path / "wrapper"
    wrapper.mkdir(mode=0o700)
    work = tmp_path / "repo"
    work.mkdir()
    spy = SpawnSpy()
    git = clone(remote.url, "main", str(wrapper / "repo"), tools=spy.tools(), token=TOKEN)
    return git, work, remote, spy, tmp_path


class TestRunFaults:
    def test_a_failed_command_is_a_scrubbed_git_error(self, world):
        git, *_ = world
        with pytest.raises(GitError) as info:
            git.rev_parse(f"no-such-ref-{TOKEN}")
        assert "rev-parse" in str(info.value)
        assert TOKEN not in str(info.value)

    def test_a_timeout_is_a_git_error(self, world):
        git, *_ = world

        def slow(*a, **k):
            raise subprocess.TimeoutExpired(a[0], 1)

        git.tools = GitTools(git=GIT, run=slow)
        with pytest.raises(GitError, match="timeout"):
            git.rev_parse("HEAD")

    def test_a_missing_git_binary_is_a_git_error(self, world):
        git, *_ = world
        git.tools = GitTools(git="/nonexistent/git")
        with pytest.raises(GitError):
            git.rev_parse("HEAD")

    def test_a_non_sha_answer_is_refused(self, world):
        git, *_ = world

        class Done:
            returncode = 0
            stdout = b"not-a-sha\n"
            stderr = b""

        git.tools = GitTools(git=GIT, run=lambda *a, **k: Done())
        with pytest.raises(GitError, match="no object id"):
            git.rev_parse("HEAD")
        with pytest.raises(GitError, match="unexpected ls-tree output"):
            git.ls_tree("HEAD")

    @pytest.mark.parametrize("sha", ["", "HEAD", "zz" * 20, "-p"])
    def test_object_ids_are_validated(self, world, sha):
        git, *_ = world
        with pytest.raises(GitError, match="invalid object id"):
            git.blob(sha)
        with pytest.raises(GitError, match="invalid object id"):
            git.blob_size(sha)


class TestDestinations:
    def test_a_missing_destination_is_refused(self, world):
        git, _work, _r, _s, tmp = world
        with pytest.raises(GitError, match="missing"):
            git.materialize(git.base_sha, str(tmp / "nope"))

    def test_a_file_destination_is_refused(self, world):
        git, _work, _r, _s, tmp = world
        (tmp / "file").write_text("x")
        with pytest.raises(GitError, match="plain directory"):
            git.capture(str(tmp / "file"))

    def test_paths_matching_nothing_write_nothing(self, world):
        git, work, _r, spy, _t = world
        assert git.materialize(git.base_sha, str(work), paths=["no/such/file"]) == 0
        assert not any(Path(s.argv[0]).name == "tar" for s in spy.fixer_spawns())

    def test_a_failing_tar_is_a_git_error(self, world):
        git, work, _r, spy, _t = world
        git.tools = spy.tools(tar="/usr/bin/false")
        with pytest.raises(GitError, match="tar -x as fixer"):
            git.materialize(git.base_sha, str(work))

    def test_unsafe_paths_are_never_removed(self, world):
        git, work, *_ = world
        for bad in ("../x", "/etc/passwd", "a/../../b", ""):
            with pytest.raises(GitError, match="unsafe path"):
                git.remove([bad], str(work))

    def test_remove_chunks_long_lists(self, world, monkeypatch):
        git, work, _r, spy, _t = world
        monkeypatch.setattr(safe_git, "RM_CHUNK", 2)
        names = [f"f{i}.txt" for i in range(5)]
        for n in names:
            (work / n).write_text("x")
        git.remove(names, str(work))
        assert not any((work / n).exists() for n in names)
        assert sum(Path(s.argv[0]).name == "rm" for s in spy.fixer_spawns()) == 3


class TestGitlinkAndReader:
    def test_a_gitlink_materializes_as_an_empty_directory(self, tmp_path):
        remote = make_remote(tmp_path, "py-make-ok")
        sha = helper_git("rev-parse", "HEAD", cwd=remote.src)
        helper_git(
            "update-index", "--add", "--cacheinfo", f"160000,{sha},vendor/lib", cwd=remote.src
        )
        helper_git("commit", "-q", "-m", "gitlink", cwd=remote.src)
        helper_git("push", "-q", str(remote.bare), "main", cwd=remote.src)
        (tmp_path / "w").mkdir()
        work = tmp_path / "r"
        work.mkdir()
        spy = SpawnSpy()
        git = clone(remote.url, "main", str(tmp_path / "w" / "repo"), tools=spy.tools())
        git.materialize(git.base_sha, str(work))
        assert (work / "vendor" / "lib").is_dir()
        assert list((work / "vendor" / "lib").iterdir()) == []

    def test_reader_refuses_unsafe_and_oversized(self, world, monkeypatch):
        git, *_ = world
        reader = TreeReader(git, git.base_sha)
        assert reader.read_text("../Makefile") is None
        assert reader.read_text("Makefile") is not None
        monkeypatch.setattr(safe_git, "MAX_BLOB_BYTES", 5)
        assert reader.read_text("Makefile") is None


class TestCloneFaults:
    @pytest.mark.parametrize("url", ["", "-x", "file:///a b", 7])
    def test_invalid_urls(self, tmp_path, url):
        with pytest.raises(GitError, match="invalid remote URL"):
            clone(url, "main", str(tmp_path / "repo"), tools=SpawnSpy().tools())

    def test_missing_parent(self, tmp_path):
        remote = make_remote(tmp_path, "py-make-ok")
        with pytest.raises(GitError):
            clone(remote.url, "main", str(tmp_path / "no" / "repo"), tools=SpawnSpy().tools())

    def test_clone_timeout(self, tmp_path):
        def slow(*a, **k):
            raise subprocess.TimeoutExpired(a[0], 1)

        with pytest.raises(GitError, match="timeout"):
            clone("file:///x", "main", str(tmp_path / "repo"), tools=GitTools(git=GIT, run=slow))

    def test_clone_with_a_missing_binary(self, tmp_path):
        tools = GitTools(git="/nonexistent/git")
        with pytest.raises(GitError, match="git clone failed"):
            clone("file:///x", "main", str(tmp_path / "repo"), tools=tools)

    def test_clone_error_scrubs_the_token(self, tmp_path):
        url = (tmp_path / f"{TOKEN}.git").as_uri()
        with pytest.raises(GitError) as info:
            clone(url, "main", str(tmp_path / "repo"), tools=SpawnSpy().tools(), token=TOKEN)
        assert TOKEN not in str(info.value)

    def test_sha256_clone_uses_the_sha256_empty_tree(self, tmp_path):
        g = SafeGit(str(tmp_path))
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("[extensions]\n\tobjectformat = sha256\n")
        cmd = g.command("status")
        assert f"--attr-source={safe_git.EMPTY_TREE['sha256']}" in cmd
        os.remove(tmp_path / ".git" / "config")
        assert f"--attr-source={safe_git.EMPTY_TREE['sha1']}" in g.command("status")
