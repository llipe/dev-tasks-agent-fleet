"""L2 tests for ``checkout.py`` with real ``git`` (S-189 AC1, AC5, AC9;
D-06, D-19, D-62, D-63, D-92, D-110, D-112).

Every test clones a fixture repo (``tests/fixtures/repos``) from a local bare
remote. The wrapper's git runs for real; ``fixer`` spawns (``tar``, ``rm``) go
through :class:`SpawnSpy`, which checks the production ``setpriv`` drop and
then runs them as the current user. GitHub is the in-repo double
(DF-186-02). Install and gates run against :class:`StubSandbox`, or
:class:`LocalSandbox` (real ``npm``/``pnpm``/``make``, offline) where the
test is about what the commands really do.

TC-189-01, -02, -03, -06, -07, -14, -15; edge cases of 10.8.
"""

from __future__ import annotations

import base64
import json
import os
import stat
from pathlib import Path

import pytest

from checkout import (
    CLONE_FAILED,
    EXCLUDE_LINES,
    INSTALL_FAILED,
    CheckoutResult,
    WorkPaths,
    github_url,
    run_checkout,
)
from issues import IssuesClient
from markers import parse_block
from refusal import REPO_GATE_PHRASES
from run_link import RunLink
from scrubber import SecretSet
from tests.component.fake_github import APP_ID, TOKEN, FakeGitHub
from tests.component.repo_fixtures import (
    LocalSandbox,
    SpawnSpy,
    StubSandbox,
    all_files,
    has,
    helper_git,
    make_remote,
    result,
    tree_files,
)

RUN = "0b9a2f4e-1c3d-4e5f-8a6b-7c8d9e0f1a2b"
ISSUE = 12
LINK = RunLink("https://panel.example", RUN)


class FakeRun:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []
        self.terminal: tuple | None = None

    def info(self, msg, **d):
        self.events.append(("info", msg, d))

    def warn(self, msg, **d):
        self.events.append(("warn", msg, d))

    def error(self, msg, **d):
        self.events.append(("error", msg, d))

    def succeed(self, outcome, result=None, metrics=None):
        self.terminal = ("succeeded", outcome, result)

    def fail(self, code, message, outcome=None, **_):
        self.terminal = ("failed", code, message)

    def messages(self) -> list[str]:
        return [m for _, m, _ in self.events]


class Env:
    """One checkout's world: work dirs, the GitHub double, the spawn spy."""

    def __init__(self, tmp_path: Path, fixture: str | None = "js-pnpm-ok", **remote_kw) -> None:
        self.tmp = tmp_path
        self.remote = make_remote(tmp_path, fixture, **remote_kw)
        wrapper = tmp_path / "work" / "wrapper"
        repo = tmp_path / "work" / "repo"
        wrapper.mkdir(parents=True, mode=0o700)
        repo.mkdir(parents=True)
        self.paths = WorkPaths(wrapper_dir=str(wrapper), repo_dir=str(repo))
        self.gh = FakeGitHub()
        self.gh.add_issue(ISSUE)
        self.spy = SpawnSpy()
        self.run = FakeRun()
        self.secrets = SecretSet()
        self.secrets.add("GITHUB_TOKEN", TOKEN)

    @property
    def clone(self) -> Path:
        return Path(self.paths.clone_dir)

    @property
    def work(self) -> Path:
        return Path(self.paths.repo_dir)

    def checkout(
        self, sandbox=None, *, branch="main", token=TOKEN, url=None, sysctl_base=None
    ) -> CheckoutResult:
        issues = IssuesClient("o", "r", TOKEN, session=self.gh)
        return run_checkout(
            run_id=RUN,
            owner="o",
            repo="r",
            base_branch=branch,
            issue_number=ISSUE,
            sandbox=sandbox if sandbox is not None else StubSandbox(),
            issues=issues,
            secrets=self.secrets,
            token=token,
            run=self.run,
            run_link=LINK,
            panel_origin=LINK.origin,
            paths=self.paths,
            tools=self.spy.tools(),
            remote_url=url if url is not None else self.remote.url,
            app_id=APP_ID,
            sysctl_base=sysctl_base,
        )


# ---------------------------------------------------------------------------
# TC-189-01: shallow clone into the wrapper clone; base SHA; info/exclude
# ---------------------------------------------------------------------------


class TestClone:
    def test_shallow_clone_records_the_base_sha(self, tmp_path):
        env = Env(tmp_path, "js-pnpm-ok", commits=3)
        out = env.checkout()
        assert out.status == "proceed", out.summary
        assert out.base_sha == env.remote.head
        assert (env.clone / ".git" / "shallow").is_file()
        count = helper_git(
            "--git-dir", str(env.clone / ".git"), "rev-list", "--count", "HEAD", cwd=tmp_path
        )
        assert count == "1"
        assert any(env.remote.head[:12] in m for m in env.run.messages())

    def test_the_clone_is_mode_0700(self, tmp_path):
        env = Env(tmp_path)
        env.checkout()
        assert stat.S_IMODE(env.clone.stat().st_mode) == 0o700

    def test_info_exclude_lists_only_the_dependency_dirs(self, tmp_path):
        env = Env(tmp_path)
        env.checkout()
        lines = (env.clone / ".git" / "info" / "exclude").read_text().splitlines()
        assert lines == ["node_modules/", ".venv/", ".pnpm-store/", "__pycache__/"]
        assert tuple(lines) == EXCLUDE_LINES
        assert "dist/" not in lines and "build/" not in lines

    def test_the_wrapper_clone_has_no_worktree_files(self, tmp_path):
        """--no-checkout: the wrapper never writes repo files into its own dir."""
        env = Env(tmp_path)
        env.checkout()
        assert sorted(p.name for p in env.clone.iterdir()) == [".git"]

    def test_clones_the_named_branch(self, tmp_path):
        env = Env(tmp_path, "py-make-ok")
        helper_git("checkout", "-q", "-b", "release", cwd=env.remote.src)
        (env.remote.src / "release.txt").write_text("r\n")
        helper_git("add", "-A", cwd=env.remote.src)
        helper_git("commit", "-q", "-m", "release", cwd=env.remote.src)
        helper_git("push", "-q", str(env.remote.bare), "release", cwd=env.remote.src)
        sha = helper_git("rev-parse", "HEAD", cwd=env.remote.src)
        out = env.checkout(branch="release")
        assert out.base_sha == sha
        assert (env.work / "release.txt").is_file()

    def test_materialized_tree_equals_the_base_tree(self, tmp_path):
        env = Env(tmp_path, "py-make-ok")
        env.checkout()
        assert tree_files(env.work) == tree_files_of_src(env.remote.src)
        assert not (env.work / ".git").exists()

    def test_executable_bit_is_kept(self, tmp_path):
        env = Env(
            tmp_path,
            files={
                ".claude/agents/developer.md": "d",
                "Makefile": MAKEFILE_OK,
                "run.sh": "#!/bin/sh\n",
            },
            fixture=None,
        )
        os.chmod(env.remote.src / "run.sh", 0o755)
        helper_git("add", "-A", cwd=env.remote.src)
        helper_git("commit", "-q", "-m", "x", cwd=env.remote.src)
        helper_git("push", "-q", str(env.remote.bare), "main", cwd=env.remote.src)
        env.checkout()
        assert os.access(env.work / "run.sh", os.X_OK)

    def test_github_url_is_token_free_and_validated(self):
        assert github_url("llipe-org", "my.repo") == "https://github.com/llipe-org/my.repo.git"
        for owner, repo in [("-x", "r"), ("o", "r/../x"), ("o", ".."), ("o w", "r"), ("o", "")]:
            with pytest.raises(ValueError):
                github_url(owner, repo)


MAKEFILE_OK = (
    Path(__file__).resolve().parents[1] / "fixtures" / "repos" / "py-make-ok" / "Makefile"
).read_text()


def tree_files_of_src(src: Path) -> dict[str, bytes]:
    files = tree_files(src)
    return {k: v for k, v in files.items() if not k.startswith(".git" + os.sep)}


# ---------------------------------------------------------------------------
# TC-189-02: no token at rest, no .git in /work/repo
# ---------------------------------------------------------------------------


class TestNoTokenAtRest:
    def test_work_tree_has_no_git_dir_and_no_token(self, tmp_path):
        env = Env(tmp_path)
        out = env.checkout()
        assert out.status == "proceed"
        assert not (env.work / ".git").exists()
        for p in all_files(env.work):
            assert TOKEN.encode() not in p.read_bytes(), p

    def test_wrapper_clone_holds_no_token(self, tmp_path):
        env = Env(tmp_path)
        env.checkout()
        b64 = base64.b64encode(f"x-access-token:{TOKEN}".encode())
        for p in all_files(env.clone / ".git"):
            data = p.read_bytes()
            assert TOKEN.encode() not in data, p
            assert b64 not in data, p
        config = (env.clone / ".git" / "config").read_text()
        assert env.remote.url in config
        assert "extraheader" not in config.lower()

    def test_token_travels_only_in_the_clone_env_scoped_to_github(self, tmp_path):
        env = Env(tmp_path)
        env.checkout()
        clone_spawns = [s for s in env.spy.git_spawns() if "clone" in s.argv]
        assert len(clone_spawns) == 1
        spawn = clone_spawns[0]
        assert TOKEN not in " ".join(spawn.argv)
        assert spawn.env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
        assert TOKEN not in spawn.env["GIT_CONFIG_VALUE_0"]  # base64, not raw
        decoded = base64.b64decode(spawn.env["GIT_CONFIG_VALUE_0"].split()[-1]).decode()
        assert decoded == f"x-access-token:{TOKEN}"
        assert "-c" in spawn.argv and "http.followRedirects=false" in spawn.argv
        # No other git call carries the token.
        for s in env.spy.git_spawns():
            if s is not spawn:
                assert TOKEN not in json.dumps(s.env or {})

    def test_no_token_means_no_auth_header(self, tmp_path):
        env = Env(tmp_path)
        env.checkout(token=None)
        spawn = next(s for s in env.spy.git_spawns() if "clone" in s.argv)
        assert "GIT_CONFIG_KEY_0" not in (spawn.env or {})


# ---------------------------------------------------------------------------
# TC-189-03 and 10.8: a clone failure
# ---------------------------------------------------------------------------


class TestCloneFailure:
    def test_unknown_branch_is_clone_failed_with_no_issue_write(self, tmp_path):
        env = Env(tmp_path)
        out = env.checkout(branch="does-not-exist")
        assert out.status == "failed"
        assert out.error_code == CLONE_FAILED == "CLONE_FAILED"
        assert env.gh.writes() == []
        out.report(env.run)
        assert env.run.terminal[0:2] == ("failed", "CLONE_FAILED")

    def test_unreachable_remote_message_is_scrubbed(self, tmp_path):
        env = Env(tmp_path)
        bad = (tmp_path / f"missing-{TOKEN}.git").as_uri()
        out = env.checkout(url=bad)
        assert out.error_code == "CLONE_FAILED"
        assert TOKEN not in out.summary
        assert TOKEN not in json.dumps(env.run.events)
        assert env.gh.writes() == []

    @pytest.mark.parametrize("branch", ["-u", "--upload-pack=touch x", "a..b", "a b", "", "x\n"])
    def test_hostile_branch_names_never_reach_git(self, tmp_path, branch):
        env = Env(tmp_path)
        out = env.checkout(branch=branch)
        assert out.error_code == "CLONE_FAILED"
        assert not any("clone" in s.argv for s in env.spy.git_spawns())

    def test_existing_clone_dir_is_refused(self, tmp_path):
        env = Env(tmp_path)
        env.clone.mkdir()
        out = env.checkout()
        assert out.error_code == "CLONE_FAILED"

    def test_non_empty_work_dir_is_refused(self, tmp_path):
        env = Env(tmp_path)
        (env.work / "stale.txt").write_text("x")
        out = env.checkout()
        assert out.error_code == "CLONE_FAILED"
        assert "not empty" in out.summary


# ---------------------------------------------------------------------------
# TC-189-06, TC-189-07: the repo gate, a refusal before the claim
# ---------------------------------------------------------------------------


class TestRepoGate:
    @pytest.mark.parametrize("fixture", ["js-pnpm-ok", "js-npm-ok", "py-make-ok", "js-monorepo"])
    def test_ok_fixtures_pass(self, tmp_path, fixture):
        env = Env(tmp_path, fixture)
        out = env.checkout()
        assert out.status == "proceed", out.summary
        assert out.toolchain is not None
        assert env.gh.writes() == []
        assert any("repo gate passed" in m for m in env.run.messages())

    @pytest.mark.parametrize(
        ("fixture", "item", "described"),
        [
            ("js-missing-typecheck", "typecheck", "missing script typecheck"),
            (
                "py-no-developer-md",
                ".claude/agents/developer.md",
                "missing .claude/agents/developer.md",
            ),
            ("py-format-underscore", "format-check", "missing target format-check"),
            ("js-format-dash", "format:check", "missing script format:check"),
            ("js-no-scripts", "test", "missing script test"),
            ("py-no-install", "install", "missing install target"),
            ("none", "package.json or Makefile", "missing package.json or Makefile"),
            (
                "js-node-unsupported",
                "supported Node.js version",
                "missing supported Node.js version",
            ),
        ],
    )
    def test_a_missing_item_is_refusal_repo_gate_naming_it(
        self, tmp_path, fixture, item, described
    ):
        env = Env(tmp_path, fixture)
        sb = StubSandbox()
        out = env.checkout(sb)
        assert out.status == "refused"
        assert out.refusal is not None
        assert out.refusal.reason == "repo_gate"
        assert described in out.summary
        # Exactly one GitHub write: the marked reply, naming the item (TC-189-08 shape).
        writes = env.gh.writes()
        assert len(writes) == 1
        assert writes[0].method == "POST"
        assert writes[0].path.endswith(f"/issues/{ISSUE}/comments")
        body = writes[0].json["body"]
        block = parse_block(body)
        assert [(m.kind, m.run_id, m.reason) for m in block] == [("refusal", RUN, "repo_gate")]
        assert REPO_GATE_PHRASES[item] in body  # DF-189-05: the fixed phrase
        assert LINK in body
        # No reaction, no install, no gates: nothing ran in the sandbox.
        assert not any("reactions" in w.path for w in writes)
        assert sb.calls == []
        out.report(env.run)
        assert env.run.terminal[0:2] == ("succeeded", "not_applicable")
        assert env.run.terminal[2]["reason"] == "repo_gate"
        assert described in env.run.terminal[2]["summary"]

    def test_a_failed_reply_keeps_not_applicable(self, tmp_path):
        env = Env(tmp_path, "js-missing-typecheck")
        env.gh.faults["comments_post"] = [500]
        out = env.checkout()
        assert out.status == "refused"
        assert out.refusal.reply == "failed"

    def test_repo_gate_reads_the_base_commit_not_the_work_tree(self, tmp_path):
        """A file the work tree gains later can't change the verdict: the
        gate reads the wrapper clone's base commit (trusted data)."""
        env = Env(tmp_path, "py-no-developer-md")
        out = env.checkout()
        assert out.status == "refused"

    def test_symlinked_developer_md_does_not_count(self, tmp_path):
        env = Env(tmp_path, "py-no-developer-md")
        (env.remote.src / ".claude" / "agents").mkdir(parents=True)
        os.symlink("../../Makefile", env.remote.src / ".claude" / "agents" / "developer.md")
        helper_git("add", "-A", cwd=env.remote.src)
        helper_git("commit", "-q", "-m", "link", cwd=env.remote.src)
        helper_git("push", "-q", str(env.remote.bare), "main", cwd=env.remote.src)
        out = env.checkout()
        assert out.status == "refused"
        assert "developer.md" in out.summary


# ---------------------------------------------------------------------------
# Install (TC-189-14, 10.8) and base gates
# ---------------------------------------------------------------------------


class TestInstall:
    @pytest.mark.parametrize(
        ("fixture", "argv"),
        [
            ("js-pnpm-ok", ("pnpm", "install", "--frozen-lockfile")),
            ("js-npm-ok", ("npm", "ci")),
            ("py-make-ok", ("make", "install")),
        ],
    )
    def test_install_argv_per_manager(self, tmp_path, fixture, argv):
        env = Env(tmp_path, fixture)
        sb = StubSandbox()
        out = env.checkout(sb)
        assert out.status == "proceed", out.summary
        assert sb.argvs()[0] == argv
        assert sb.calls[0].cwd == str(env.work)
        assert sb.calls[0].anthropic_api_key is None

    def test_install_and_gates_run_on_the_repos_node(self, tmp_path):
        """The failing run: ``engines.node: ">=24.21.0 <25"`` on a Node 26
        default. Install and every gate get the shipped Node 24."""
        from node import NODE_VERSIONS

        env = Env(tmp_path, "js-node-24")
        sb = StubSandbox()
        out = env.checkout(sb)
        assert out.status == "proceed", out.summary
        assert out.toolchain.node_version == NODE_VERSIONS[1]
        assert sb.calls and {c.node for c in sb.calls} == {NODE_VERSIONS[1]}
        assert any(f"node {NODE_VERSIONS[1]}" in m for m in env.run.messages())

    def test_python_install_and_gates_get_no_node(self, tmp_path):
        env = Env(tmp_path, "py-make-ok")
        sb = StubSandbox()
        out = env.checkout(sb)
        assert out.status == "proceed", out.summary
        assert sb.calls and {c.node for c in sb.calls} == {None}

    def test_install_failure_is_install_failed_with_no_issue_write(self, tmp_path):
        env = Env(tmp_path, "js-npm-ok")
        sb = StubSandbox(answers={("npm", "ci"): result(1, "", f"npm error {TOKEN}\n")})
        out = env.checkout(sb)
        assert out.status == "failed"
        assert out.error_code == INSTALL_FAILED == "INSTALL_FAILED"
        assert TOKEN not in out.summary
        assert env.gh.writes() == []
        assert sb.argvs() == [("npm", "ci")]  # no gate runs after a failed install

    def test_install_timeout_is_install_failed(self, tmp_path):
        env = Env(tmp_path, "py-make-ok")
        sb = StubSandbox(answers={("make", "install"): result(None, timed_out=True)})
        out = env.checkout(sb)
        assert out.error_code == "INSTALL_FAILED"
        assert "timeout" in out.summary

    def test_unavailable_sandbox_is_install_failed(self, tmp_path):
        from sandbox import SandboxUnavailable

        env = Env(tmp_path, "py-make-ok")
        sb = StubSandbox(
            answers={("make", "install"): SandboxUnavailable("srt is missing: /usr/bin/srt")}
        )
        out = env.checkout(sb)
        assert out.error_code == "INSTALL_FAILED"
        assert "srt is missing" in out.summary

    @pytest.mark.skipif(not has("npm"), reason="npm not on PATH")
    def test_real_npm_ci_installs(self, tmp_path):
        env = Env(tmp_path, "js-npm-ok")
        out = env.checkout(LocalSandbox())
        assert out.status == "proceed", out.summary
        assert out.base_gates.blocking_passed

    @pytest.mark.skipif(not has("pnpm"), reason="pnpm not on PATH")
    def test_real_pnpm_frozen_install(self, tmp_path):
        env = Env(tmp_path, "js-pnpm-ok")
        out = env.checkout(LocalSandbox())
        assert out.status == "proceed", out.summary

    @pytest.mark.skipif(not has("npm"), reason="npm not on PATH")
    def test_out_of_sync_lockfile_is_install_failed_and_unchanged(self, tmp_path):
        """TC-189-14: `npm ci` refuses; the lockfile is byte-identical."""
        env = Env(tmp_path, "js-npm-out-of-sync")
        before = (env.remote.src / "package-lock.json").read_bytes()
        sb = LocalSandbox()
        out = env.checkout(sb)
        assert out.status == "failed"
        assert out.error_code == "INSTALL_FAILED"
        assert sb.argvs() == [("npm", "ci")]
        assert (env.work / "package-lock.json").read_bytes() == before
        assert env.gh.writes() == []


class TestBaseGates:
    def test_base_gates_run_after_install_and_never_block(self, tmp_path):
        env = Env(tmp_path, "py-make-ok")
        sb = StubSandbox(answers={("make", "test"): result(2, "1 failed\n")})
        out = env.checkout(sb)
        assert out.status == "proceed"
        assert sb.argvs() == [
            ("make", "install"),
            ("make", "test"),
            ("make", "lint"),
            ("make", "format-check"),
            ("make", "typecheck"),
            ("make", "audit"),
        ]
        assert out.base_gates is not None
        assert out.base_gates.phase == "base"
        assert not out.base_gates.blocking_passed
        assert any(e[2].get("gate") == "test" and e[2].get("pass") is False for e in env.run.events)


# ---------------------------------------------------------------------------
# TC-189-15: base runs that edit the tree are undone before the CLI (D-63)
# ---------------------------------------------------------------------------


def _autofix(call):
    """What js-autofix-lint's `lint` does, without npm."""
    root = Path(call.cwd)
    (root / "src" / "add.js").write_text("export const rewritten = 1;\n")
    (root / "untracked.txt").write_text("new\n")
    (root / "node_modules" / "x").mkdir(parents=True, exist_ok=True)
    (root / "node_modules" / "x" / "keep.txt").write_text("keep\n")
    return result(0, "fixed 1 file\n")


class TestRestoreBase:
    def test_tracked_rewrite_and_untracked_file_are_restored(self, tmp_path):
        env = Env(tmp_path, "js-autofix-lint")
        sb = StubSandbox(answers={("npm", "run", "lint"): _autofix})
        out = env.checkout(sb)
        assert out.status == "proceed", out.summary
        assert (env.work / "src" / "add.js").read_text() == (
            env.remote.src / "src" / "add.js"
        ).read_text()
        assert not (env.work / "untracked.txt").exists()
        # Ignored by info/exclude: left as it is.
        assert (env.work / "node_modules" / "x" / "keep.txt").read_text() == "keep\n"
        assert out.restored == 2
        assert "base runs modified 2 tracked files; restored" in env.run.messages()
        # The restore ran as fixer: rm and tar behind the setpriv drop.
        fixer = env.spy.fixer_spawns()
        assert any(Path(s.argv[0]).name == "rm" for s in fixer)
        assert sum(Path(s.argv[0]).name == "tar" for s in fixer) >= 2

    def test_a_clean_base_run_restores_nothing(self, tmp_path):
        env = Env(tmp_path, "js-npm-ok")
        out = env.checkout(StubSandbox())
        assert out.restored == 0
        assert not any("restored" in m and "modified" in m for m in env.run.messages())

    def test_a_deleted_tracked_file_is_restored(self, tmp_path):
        env = Env(tmp_path, "py-make-ok")

        def delete(call):
            (Path(call.cwd) / "src" / "app.py").unlink()
            return result(0)

        out = env.checkout(StubSandbox(answers={("make", "lint"): delete}))
        assert out.status == "proceed"
        assert (env.work / "src" / "app.py").read_text() == (
            env.remote.src / "src" / "app.py"
        ).read_text()
        assert out.restored == 1

    def test_a_file_replaced_by_a_symlink_is_restored(self, tmp_path):
        env = Env(tmp_path, "py-make-ok")

        def swap(call):
            p = Path(call.cwd) / "src" / "app.py"
            p.unlink()
            os.symlink("/etc/passwd", p)
            return result(0)

        out = env.checkout(StubSandbox(answers={("make", "typecheck"): swap}))
        assert out.status == "proceed", out.summary
        p = env.work / "src" / "app.py"
        assert not p.is_symlink()
        assert p.read_text() == (env.remote.src / "src" / "app.py").read_text()

    def test_a_gitignore_edit_that_hides_a_new_file_is_still_undone(self, tmp_path):
        env = Env(tmp_path, "py-make-ok")

        def hide(call):
            root = Path(call.cwd)
            (root / ".gitignore").write_text("secret.txt\n")
            (root / "secret.txt").write_text("x\n")
            return result(0)

        out = env.checkout(StubSandbox(answers={("make", "lint"): hide}))
        assert out.status == "proceed", out.summary
        assert not (env.work / ".gitignore").exists()
        assert not (env.work / "secret.txt").exists()

    def test_same_size_same_mtime_edit_is_still_seen(self, tmp_path):
        """The capture re-hashes every file: a stat-preserving edit is caught."""
        env = Env(tmp_path, "py-make-ok")

        def sneaky(call):
            p = Path(call.cwd) / "src" / "app.py"
            st = p.stat()
            data = p.read_bytes()
            p.write_bytes(data.replace(b"a + b", b"a - b"))
            os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
            return result(0)

        out = env.checkout(StubSandbox(answers={("make", "lint"): sneaky}))
        assert out.restored == 1
        assert b"a + b" in (env.work / "src" / "app.py").read_bytes()

    @pytest.mark.skipif(not has("npm"), reason="npm not on PATH")
    def test_real_autofix_lint_through_npm(self, tmp_path):
        env = Env(tmp_path, "js-autofix-lint")
        out = env.checkout(LocalSandbox())
        assert out.status == "proceed", out.summary
        assert out.restored == 2
        assert not (env.work / "untracked.txt").exists()
        assert (env.work / "node_modules" / "x" / "keep.txt").exists()

    def test_restore_that_cannot_converge_is_clone_failed(self, tmp_path, monkeypatch):
        import checkout

        env = Env(tmp_path, "py-make-ok")

        def dirty(call):
            (Path(call.cwd) / "src" / "app.py").write_text("dirty\n")
            return result(0)

        monkeypatch.setattr(checkout, "_restore_paths", lambda *a, **k: None)
        out = env.checkout(StubSandbox(answers={("make", "lint"): dirty}))
        assert out.status == "failed"
        assert out.error_code == "CLONE_FAILED"
        assert "restore" in out.summary
