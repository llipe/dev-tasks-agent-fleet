"""L1 tests for ``sandbox.py`` and ``fixer_exec.py`` (S-182 tasks 3.1, 3.17; TC-182-01..05; D-51, D-110).

The wrapper runs as root (D-110: AgentCore sets ``no_new_privs``, so setuid
``sudo`` can't run). ``sandbox.py`` starts every ``fixer`` process through
``setpriv --reuid=10002 --regid=10002 --clear-groups --inh-caps=-all
--no-new-privs -- python3 -I fixer_exec.py <runtime> ...``:

- the env handed to the spawn is built from an **allow-list** and never from
  ``os.environ``; ``setpriv`` passes it through unchanged, so it is the only
  env source;
- ``fixer_exec.py`` rebuilds the final environment from the same allow-list
  (defence in depth) and refuses to exec while still root;
- the runtime is the sandbox: ``srt`` (the sandbox runtime) for scripts, or the
  Claude Code CLI, which enforces its own sandbox from the managed policy;
- a wall-clock timeout sends SIGTERM, then after 15 s sweeps every ``fixer``
  process and sends SIGKILL; zombies are reaped.

Processes are faked here (injected ``popen``, clock and sleep). The real-process
behaviour is in ``tests/component/test_sandbox_proc.py``.
"""

from __future__ import annotations

import signal
from pathlib import Path
from typing import Any

import pytest

import fixer_exec
import sandbox
from sandbox import (
    EXIT_CODE_TABLE,
    Mode,
    Outcome,
    Sandbox,
    SandboxPaths,
    SandboxUnavailable,
    build_env,
    map_exit,
)

KEY = "sk-ant-api03-sentinel-key-value-0123456789abcdef"

POLLUTION = {
    "AWS_ACCESS_KEY_ID": "AKIASENTINEL",
    "AWS_SECRET_ACCESS_KEY": "aws-secret-sentinel",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI": "http://169.254.170.23/v1/credentials",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "/v2/credentials/x",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN": "container-token-sentinel",
    "SUPABASE_URL": "https://sentinel.supabase.co",
    "SUPABASE_KEY_SECRET_ID": "agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY",
    "GITHUB_TOKEN": "ghs_" + "a" * 36,
    "GH_TOKEN": "gho_" + "b" * 36,
    "GITHUB_PROJECTS_TOKEN": "ghp_" + "c" * 36,
    "PROJECTS_TOKEN_SECRET_ID": "agent-fleet/prod/GITHUB_PROJECTS_TOKEN",
    "SENTINEL_RANDOM_7F3A": "random-sentinel-7f3a",
}

EXPECTED_NAMES = {"ANTHROPIC_API_KEY", "PATH", "HOME", "LANG", "CI"}


@pytest.fixture
def paths(tmp_path: Path) -> SandboxPaths:
    """Every binary exists and is executable (an empty script)."""

    def _exe(name: str) -> str:
        p = tmp_path / name
        p.write_text("#!/bin/sh\n")
        p.chmod(0o755)
        return str(p)

    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1\tlocalhost\n")
    return SandboxPaths(
        hosts=str(hosts),
        setpriv=_exe("setpriv"),
        python=_exe("python3"),
        fixer_exec=_exe("fixer_exec.py"),
        node=_exe("node"),
        srt=_exe("srt"),
        srt_settings=_exe("srt-settings.json"),
        claude=_exe("claude"),
        kill=_exe("kill"),
        pkill=_exe("pkill"),
    )


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeProc:
    """A child whose lifetime is scripted in fake-clock seconds."""

    def __init__(
        self,
        clock: FakeClock,
        *,
        exits_at: float | None,
        code: int = 0,
        ignores_sigterm: bool = False,
    ) -> None:
        self.clock = clock
        self.start = clock.now
        self.exits_at = exits_at
        self.code = code
        self.ignores_sigterm = ignores_sigterm
        self.pid = 4242
        self.returncode: int | None = None
        self.signals: list[tuple[float, int]] = []

    def poll(self) -> int | None:
        if (
            self.returncode is None
            and self.exits_at is not None
            and (self.clock.now - self.start >= self.exits_at)
        ):
            self.returncode = self.code
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.poll() is None:
            raise AssertionError("wait() on a live fake process would block")
        assert self.returncode is not None
        return self.returncode

    def deliver(self, sig: int) -> None:
        self.signals.append((self.clock.now - self.start, sig))
        if sig == signal.SIGKILL or (sig == signal.SIGTERM and not self.ignores_sigterm):
            self.returncode = -sig


class Recorder:
    """Injected popen: records the call and returns a scripted FakeProc."""

    def __init__(self, proc: FakeProc) -> None:
        self.proc = proc
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> FakeProc:
        self.calls.append((list(cmd), kwargs))
        return self.proc


def _sandbox(paths: SandboxPaths, proc: FakeProc, clock: FakeClock, events: list[str]):
    rec = Recorder(proc)

    def _kill(pid: int, sig: int) -> None:
        assert pid == proc.pid
        events.append(f"signal:{sig}")
        proc.deliver(sig)

    sb = Sandbox(
        paths,
        popen=rec,
        clock=clock,
        sleep=clock.sleep,
        kill=_kill,
        sweeper=lambda: events.append("sweep"),
        reaper=lambda: events.append("reap"),
    )
    return sb, rec


# ---------------------------------------------------------------------------
# TC-182-01: allow-list env
# ---------------------------------------------------------------------------


class TestAllowListEnv:
    def test_build_env_is_exactly_the_allow_list(self, monkeypatch):
        for k, v in POLLUTION.items():
            monkeypatch.setenv(k, v)
        env = build_env(KEY)
        assert set(env) == EXPECTED_NAMES
        assert env["ANTHROPIC_API_KEY"] == KEY
        assert env["HOME"] == "/home/fixer"
        assert env["CI"] == "1"
        assert env["LANG"]
        assert env["PATH"] == sandbox.FIXER_PATH

    def test_build_env_ignores_parent_values_for_allowed_names(self, monkeypatch):
        # Even an allow-listed name is never copied from the parent: PATH and
        # HOME are fixed, so a wrapper-side PATH can't leak a wrapper dir.
        monkeypatch.setenv("PATH", "/home/wrapper/bin:/usr/bin")
        monkeypatch.setenv("HOME", "/home/wrapper")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "parent-key-sentinel")
        env = build_env(None)
        assert env["PATH"] == sandbox.FIXER_PATH
        assert env["HOME"] == "/home/fixer"
        assert "ANTHROPIC_API_KEY" not in env  # no key given -> none passed

    def test_spawn_receives_exactly_the_allow_list(self, monkeypatch, paths):
        for k, v in POLLUTION.items():
            monkeypatch.setenv(k, v)
        clock = FakeClock()
        events: list[str] = []
        sb, rec = _sandbox(paths, FakeProc(clock, exits_at=0.0), clock, events)
        sb.run(["true"], cwd="/work/repo", timeout=60, anthropic_api_key=KEY)

        ((_cmd, kwargs),) = rec.calls
        env = kwargs["env"]
        assert set(env) == EXPECTED_NAMES
        for value in POLLUTION.values():
            assert value not in env.values()
            assert value not in " ".join(_cmd)

    def test_no_aws_or_container_variable_ever_passes(self, monkeypatch, paths):
        for k, v in POLLUTION.items():
            monkeypatch.setenv(k, v)
        clock = FakeClock()
        sb, rec = _sandbox(paths, FakeProc(clock, exits_at=0.0), clock, [])
        sb.run(["true"], cwd="/work/repo", timeout=60, anthropic_api_key=KEY)
        env = rec.calls[0][1]["env"]
        assert not [k for k in env if k.startswith(("AWS_", "SUPABASE_", "GITHUB", "GH_"))]

    def test_secret_never_in_argv(self, paths):
        clock = FakeClock()
        sb, rec = _sandbox(paths, FakeProc(clock, exits_at=0.0), clock, [])
        sb.run(["true"], cwd="/work/repo", timeout=60, anthropic_api_key=KEY)
        cmd = rec.calls[0][0]
        assert KEY not in " ".join(cmd)

    def test_no_name_based_env_passing_in_argv(self, paths):
        # setpriv has no env options: the Popen env is the only source.
        clock = FakeClock()
        sb, rec = _sandbox(paths, FakeProc(clock, exits_at=0.0), clock, [])
        sb.run(["true"], cwd="/work/repo", timeout=60, anthropic_api_key=KEY)
        cmd = rec.calls[0][0]
        assert not [a for a in cmd if a.startswith("--preserve-env")]
        assert "-E" not in cmd
        assert not [a for a in cmd if a.endswith("sudo")]

    def test_key_absent_when_none(self, paths):
        clock = FakeClock()
        sb, rec = _sandbox(paths, FakeProc(clock, exits_at=0.0), clock, [])
        sb.run(["true"], cwd="/work/repo", timeout=60)
        assert "ANTHROPIC_API_KEY" not in rec.calls[0][1]["env"]


class TestFixerExecEnv:
    """``fixer_exec.py`` runs as fixer after setpriv and rebuilds the env."""

    def test_rebuilds_from_allow_list_dropping_anything_else(self):
        incoming = {
            "ANTHROPIC_API_KEY": KEY,
            "LANG": "C.UTF-8",
            "CI": "1",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": "/home/fixer",
            "SUDO_USER": "wrapper",
            "SUDO_UID": "10001",
            "SUDO_GID": "10001",
            "SUDO_COMMAND": "/usr/local/bin/python3 -I /app/fixer_exec.py ...",
            "SUDO_HOME": "/home/wrapper",
            "USER": "fixer",
            "LOGNAME": "fixer",
            "SHELL": "/bin/bash",
            "MAIL": "/var/mail/fixer",
            "TERM": "xterm",
            **POLLUTION,
        }
        env = fixer_exec.build_env(incoming)
        assert set(env) == EXPECTED_NAMES
        assert env["PATH"] == fixer_exec.FIXER_PATH == sandbox.FIXER_PATH
        assert env["HOME"] == "/home/fixer"
        assert env["ANTHROPIC_API_KEY"] == KEY

    def test_without_key_the_env_has_four_names(self):
        env = fixer_exec.build_env({"LANG": "C.UTF-8", "CI": "1", **POLLUTION})
        assert set(env) == {"PATH", "HOME", "LANG", "CI"}

    def test_main_execs_with_rebuilt_env(self, monkeypatch):
        seen: dict[str, Any] = {}
        monkeypatch.setattr(fixer_exec.os, "getuid", lambda: 10002)
        monkeypatch.setattr(fixer_exec.os, "geteuid", lambda: 10002)

        def _exec(path, args, env):
            seen.update(path=path, args=args, env=env)

        monkeypatch.setattr(fixer_exec.os, "execvpe", _exec)
        monkeypatch.setattr(fixer_exec.os, "environ", {"CI": "1", **POLLUTION})
        fixer_exec.main(["fixer_exec.py", "/usr/bin/srt", "--settings", "x", "--", "true"])
        assert seen["path"] == "/usr/bin/srt"
        assert seen["args"] == ["/usr/bin/srt", "--settings", "x", "--", "true"]
        assert set(seen["env"]) == {"PATH", "HOME", "CI", "LANG"}

    def test_main_without_command_exits_2(self):
        with pytest.raises(SystemExit) as exc:
            fixer_exec.main(["fixer_exec.py"])
        assert exc.value.code == 2

    @pytest.mark.parametrize(("uid", "euid"), [(0, 0), (10002, 0), (0, 10002)])
    def test_refuses_to_exec_as_root(self, monkeypatch, uid, euid):
        # If the setpriv drop did not happen, nothing runs as root (D-110).
        execs: list[Any] = []
        monkeypatch.setattr(fixer_exec.os, "getuid", lambda: uid)
        monkeypatch.setattr(fixer_exec.os, "geteuid", lambda: euid)
        monkeypatch.setattr(fixer_exec.os, "execvpe", lambda *a: execs.append(a))
        with pytest.raises(SystemExit) as exc:
            fixer_exec.main(["fixer_exec.py", "/usr/bin/true"])
        assert exc.value.code == fixer_exec.EXIT_STILL_ROOT
        assert execs == []

    def test_allow_lists_agree(self):
        assert set(fixer_exec.ALLOWED) == EXPECTED_NAMES == set(sandbox.ALLOWED_ENV)


class TestNodePath:
    """The repo's Node major goes first on PATH, from a closed set only."""

    def test_node_path_puts_the_major_bin_first(self):
        assert sandbox.node_path("24.22.2") == "/opt/node/24/bin:" + sandbox.FIXER_PATH

    def test_node_path_refuses_an_unshipped_version(self):
        with pytest.raises(ValueError):
            sandbox.node_path("18.20.0")

    def test_allowed_paths_are_the_base_plus_one_per_shipped_version(self):
        import node

        assert (
            sandbox.FIXER_PATH,
            *(sandbox.node_path(v) for v in node.NODE_VERSIONS),
        ) == sandbox.ALLOWED_PATHS

    def test_build_env_with_node(self):
        env = build_env(None, node="22.23.4")
        assert env["PATH"] == "/opt/node/22/bin:" + sandbox.FIXER_PATH
        assert set(env) == {"PATH", "HOME", "LANG", "CI"}

    def test_build_env_refuses_an_unshipped_node(self):
        with pytest.raises(ValueError):
            build_env(None, node="/tmp/evil")

    def test_run_passes_the_node_path(self, paths):
        clock = FakeClock()
        sb, rec = _sandbox(paths, FakeProc(clock, exits_at=0.0), clock, [])
        sb.run(["true"], cwd="/work/repo", timeout=60, node="24.22.2")
        assert rec.calls[0][1]["env"]["PATH"] == "/opt/node/24/bin:" + sandbox.FIXER_PATH

    def test_run_without_node_keeps_the_base_path(self, paths):
        clock = FakeClock()
        sb, rec = _sandbox(paths, FakeProc(clock, exits_at=0.0), clock, [])
        sb.run(["true"], cwd="/work/repo", timeout=60)
        assert rec.calls[0][1]["env"]["PATH"] == sandbox.FIXER_PATH

    def test_run_with_an_unshipped_node_spawns_nothing(self, paths):
        clock = FakeClock()
        sb, rec = _sandbox(paths, FakeProc(clock, exits_at=0.0), clock, [])
        with pytest.raises(ValueError):
            sb.run(["true"], cwd="/work/repo", timeout=60, node="99.0.0")
        assert rec.calls == []

    def test_fixer_exec_allowed_paths_equal_the_wrappers(self):
        assert fixer_exec.ALLOWED_PATHS == sandbox.ALLOWED_PATHS

    @pytest.mark.parametrize("path", sandbox.ALLOWED_PATHS)
    def test_fixer_exec_keeps_an_allowed_path(self, path):
        assert fixer_exec.build_env({"PATH": path})["PATH"] == path

    @pytest.mark.parametrize(
        "path",
        [
            "/tmp/bin:/usr/local/bin:/usr/bin:/bin",
            "/opt/node/24/bin:/tmp:/usr/local/bin:/usr/bin:/bin",
            "/opt/node/18/bin:/usr/local/bin:/usr/bin:/bin",
            "/opt/node/24/bin",
            "",
        ],
    )
    def test_fixer_exec_resets_any_other_path(self, path):
        assert fixer_exec.build_env({"PATH": path})["PATH"] == fixer_exec.FIXER_PATH


# ---------------------------------------------------------------------------
# TC-182-02: uid switch and sandbox wrapper
# ---------------------------------------------------------------------------


class TestCommandShape:
    SETPRIV_FLAGS = [
        "--reuid=10002",
        "--regid=10002",
        "--clear-groups",
        "--inh-caps=-all",
        "--no-new-privs",
    ]

    def test_setpriv_flags_are_exactly_d110(self):
        assert list(sandbox.SETPRIV_FLAGS) == self.SETPRIV_FLAGS
        assert sandbox.FIXER_UID == 10002

    def test_script_mode_drops_to_fixer_and_wraps_in_srt(self, paths):
        cmd = Sandbox(paths).build_command(Mode.SCRIPT, ["npm", "test"])
        assert cmd[:7] == [paths.setpriv, *self.SETPRIV_FLAGS, "--"]
        assert cmd[7:10] == [paths.python, "-I", paths.fixer_exec]
        rest = cmd[10:]
        assert rest[:4] == [paths.node, paths.srt, "--settings", paths.srt_settings]
        assert rest[4] == "--"
        assert rest[5:] == ["npm", "test"]

    def test_srt_runs_on_the_image_default_node_not_the_repos(self, paths):
        # #471: PATH may put a repo's Node first; srt and its proxy stay on
        # the default Node the S-182 confinement checks ran on.
        assert sandbox.DEFAULT_PATHS.node == "/usr/bin/node"
        cmd = Sandbox(paths).build_command(Mode.SCRIPT, ["true"])
        assert cmd[cmd.index(paths.srt) - 1] == paths.node

    def test_cli_mode_runs_only_the_claude_binary(self, paths):
        cmd = Sandbox(paths).build_command(Mode.CLI, [paths.claude, "-p"])
        assert cmd[:7] == [paths.setpriv, *self.SETPRIV_FLAGS, "--"]
        assert cmd[7:11] == [paths.python, "-I", paths.fixer_exec, paths.claude]

    def test_fixer_prefix(self, paths):
        assert sandbox.fixer_prefix(paths) == [
            paths.setpriv,
            *self.SETPRIV_FLAGS,
            "--",
            paths.python,
            "-I",
            paths.fixer_exec,
        ]

    @pytest.mark.parametrize("argv0", ["bash", "/bin/sh", "claude-but-not", "/tmp/claude"])
    def test_cli_mode_refuses_any_other_binary(self, paths, argv0):
        with pytest.raises(ValueError):
            Sandbox(paths).build_command(Mode.CLI, [argv0, "-c", "id"])

    def test_empty_argv_refused(self, paths):
        with pytest.raises(ValueError):
            Sandbox(paths).build_command(Mode.SCRIPT, [])

    @pytest.mark.parametrize("mode", list(Mode))
    def test_no_bare_exec_is_ever_built(self, paths, mode):
        argv = [paths.claude, "-p"] if mode is Mode.CLI else ["true"]
        cmd = Sandbox(paths).build_command(mode, argv)
        assert cmd[0] == paths.setpriv
        assert "--reuid=10002" in cmd and "--no-new-privs" in cmd
        runtime = cmd[cmd.index("--") + 4]
        assert runtime in (paths.node, paths.claude)

    def test_popen_runs_in_new_session_with_cwd_and_closed_fds(self, paths):
        clock = FakeClock()
        sb, rec = _sandbox(paths, FakeProc(clock, exits_at=0.0), clock, [])
        sb.run(["true"], cwd="/work/repo", timeout=60)
        kwargs = rec.calls[0][1]
        assert kwargs["cwd"] == "/work/repo"
        assert kwargs["start_new_session"] is True
        assert kwargs["close_fds"] is True


# ---------------------------------------------------------------------------
# TC-182-03: timeout -> SIGTERM -> +15 s -> sweep + SIGKILL; exit-code table
# ---------------------------------------------------------------------------


class TestTimeout:
    def test_default_kill_grace_is_15_seconds(self):
        assert sandbox.KILL_GRACE_SECONDS == 15.0

    def test_normal_exit_no_signal(self, paths):
        clock = FakeClock()
        events: list[str] = []
        proc = FakeProc(clock, exits_at=5.0, code=0)
        sb, _ = _sandbox(paths, proc, clock, events)
        res = sb.run(["true"], cwd="/w", timeout=60)
        assert res.outcome is Outcome.OK and res.exit_code == 0 and not res.timed_out
        assert proc.signals == []
        assert events == ["sweep", "reap"]  # post-run sweep always runs (D-62)

    def test_timeout_sends_sigterm_at_deadline(self, paths):
        clock = FakeClock()
        events: list[str] = []
        proc = FakeProc(clock, exits_at=None)
        sb, _ = _sandbox(paths, proc, clock, events)
        res = sb.run(["sleep", "999"], cwd="/w", timeout=30)
        assert res.timed_out is True
        assert res.outcome is Outcome.TIMEOUT
        ((at, sig),) = proc.signals
        assert sig == signal.SIGTERM
        assert 30.0 <= at < 31.0
        assert events == [f"signal:{int(signal.SIGTERM)}", "sweep", "reap"]

    def test_sigterm_ignored_gets_sweep_and_sigkill_after_15s(self, paths):
        clock = FakeClock()
        events: list[str] = []
        proc = FakeProc(clock, exits_at=None, ignores_sigterm=True)
        sb, _ = _sandbox(paths, proc, clock, events)
        res = sb.run(["sleep", "999"], cwd="/w", timeout=30)
        assert res.outcome is Outcome.TIMEOUT
        sigs = [s for _, s in proc.signals]
        assert sigs == [signal.SIGTERM, signal.SIGKILL]
        term_at, kill_at = (t for t, _ in proc.signals)
        assert 15.0 <= kill_at - term_at < 16.0
        # The fixer sweep runs before the SIGKILL, so a grandchild that left the
        # child's session is stopped too.
        assert events == [
            f"signal:{int(signal.SIGTERM)}",
            "sweep",
            f"signal:{int(signal.SIGKILL)}",
            "sweep",
            "reap",
        ]

    def test_timeout_distinct_from_nonzero_exit(self, paths):
        clock = FakeClock()
        sb, _ = _sandbox(paths, FakeProc(clock, exits_at=1.0, code=1), clock, [])
        failed = sb.run(["false"], cwd="/w", timeout=30)
        assert failed.outcome is Outcome.FAILED and not failed.timed_out

        clock2 = FakeClock()
        sb2, _ = _sandbox(paths, FakeProc(clock2, exits_at=None), clock2, [])
        timed = sb2.run(["sleep", "1"], cwd="/w", timeout=1)
        assert timed.outcome is Outcome.TIMEOUT and timed.timed_out
        assert failed.outcome != timed.outcome

    def test_signal_to_gone_process_is_ignored(self, paths):
        clock = FakeClock()
        proc = FakeProc(clock, exits_at=None)

        def _gone(pid, sig):
            proc.returncode = -9
            raise ProcessLookupError

        sb = Sandbox(
            paths,
            popen=Recorder(proc),
            clock=clock,
            sleep=clock.sleep,
            kill=_gone,
            sweeper=lambda: None,
            reaper=lambda: None,
        )
        assert sb.run(["x"], cwd="/w", timeout=1).timed_out

    def test_signal_permission_error_is_ignored(self, paths):
        clock = FakeClock()
        proc = FakeProc(clock, exits_at=None)

        def _denied(pid, sig):
            if sig == signal.SIGKILL:
                proc.returncode = -9
            raise PermissionError

        sb = Sandbox(
            paths,
            popen=Recorder(proc),
            clock=clock,
            sleep=clock.sleep,
            kill=_denied,
            sweeper=lambda: None,
            reaper=lambda: None,
        )
        res = sb.run(["x"], cwd="/w", timeout=1)
        assert res.outcome is Outcome.TIMEOUT

    @pytest.mark.parametrize("bad", [0, -1])
    def test_timeout_must_be_positive(self, paths, bad):
        with pytest.raises(ValueError):
            Sandbox(paths).run(["true"], cwd="/w", timeout=bad)


class TestExitCodeTable:
    def test_table(self):
        assert EXIT_CODE_TABLE == {
            0: Outcome.OK,
            126: Outcome.NOT_EXECUTABLE,
            127: Outcome.NOT_FOUND,
        }

    @pytest.mark.parametrize(
        ("code", "timed_out", "expected"),
        [
            (0, False, Outcome.OK),
            (1, False, Outcome.FAILED),
            (2, False, Outcome.FAILED),
            (126, False, Outcome.NOT_EXECUTABLE),
            (127, False, Outcome.NOT_FOUND),
            (-9, False, Outcome.SIGNALED),
            (-15, False, Outcome.SIGNALED),
            (137, False, Outcome.SIGNALED),
            (143, False, Outcome.SIGNALED),
            (0, True, Outcome.TIMEOUT),
            (1, True, Outcome.TIMEOUT),
            (-9, True, Outcome.TIMEOUT),
        ],
    )
    def test_map_exit(self, code, timed_out, expected):
        assert map_exit(code, timed_out) is expected

    def test_result_ok_property(self, paths):
        clock = FakeClock()
        sb, _ = _sandbox(paths, FakeProc(clock, exits_at=0.0), clock, [])
        assert sb.run(["true"], cwd="/w", timeout=5).ok is True


# ---------------------------------------------------------------------------
# TC-182-04: a missing sandbox binary raises SandboxUnavailable
# ---------------------------------------------------------------------------


class TestUnavailable:
    @pytest.mark.parametrize("field", ["setpriv", "python", "fixer_exec", "srt", "srt_settings"])
    def test_missing_script_dependency(self, paths, field, tmp_path):
        broken = paths._replace(**{field: str(tmp_path / "missing" / field)})
        with pytest.raises(SandboxUnavailable) as exc:
            Sandbox(broken).run(["true"], cwd="/w", timeout=5)
        assert field in str(exc.value) or "missing" in str(exc.value)
        assert not isinstance(exc.value, FileNotFoundError)

    def test_missing_claude_in_cli_mode(self, paths, tmp_path):
        broken = paths._replace(claude=str(tmp_path / "nope" / "claude"))
        with pytest.raises(SandboxUnavailable):
            Sandbox(broken).run([broken.claude, "-p"], mode=Mode.CLI, cwd="/w", timeout=5)

    @pytest.mark.parametrize("mode", list(Mode))
    def test_missing_setpriv_names_it(self, paths, tmp_path, mode):
        broken = paths._replace(setpriv=str(tmp_path / "nope" / "setpriv"))
        with pytest.raises(SandboxUnavailable) as exc:
            Sandbox(broken).check_available(mode)
        assert "setpriv" in str(exc.value)

    def test_missing_default_node_in_script_mode_names_it(self, paths, tmp_path):
        broken = paths._replace(node=str(tmp_path / "nope" / "node"))
        with pytest.raises(SandboxUnavailable) as exc:
            Sandbox(broken).check_available(Mode.SCRIPT)
        assert "node" in str(exc.value)
        Sandbox(broken).check_available(Mode.CLI)  # the CLI runs on PATH's Node

    def test_cli_mode_does_not_need_srt(self, paths, tmp_path):
        no_srt = paths._replace(srt=str(tmp_path / "nope" / "srt"))
        Sandbox(no_srt).check_available(Mode.CLI)  # no raise

    def test_not_executable_is_unavailable(self, paths):
        Path(paths.srt).chmod(0o644)
        with pytest.raises(SandboxUnavailable):
            Sandbox(paths).check_available(Mode.SCRIPT)

    def test_popen_file_not_found_is_translated(self, paths):
        def _boom(cmd, **kw):
            raise FileNotFoundError(2, "No such file", cmd[0])

        with pytest.raises(SandboxUnavailable):
            Sandbox(paths, popen=_boom, sweeper=lambda: None, reaper=lambda: None).run(
                ["true"], cwd="/w", timeout=5
            )

    def test_is_a_sandbox_error(self):
        assert issubclass(SandboxUnavailable, sandbox.SandboxError)


# ---------------------------------------------------------------------------
# TC-182-05 (unit part): sweep and reap always run, also when popen output fails
# ---------------------------------------------------------------------------


class TestSweepAndReap:
    def test_default_sweeper_kills_every_fixer_process(self, paths):
        calls: list[list[str]] = []
        envs: list[dict[str, str]] = []

        def _run(cmd, **kw):
            calls.append(cmd)
            envs.append(kw["env"])

            class R:
                returncode = 0

            return R()

        Sandbox(paths, run=_run).sweep()
        # Pass 1, as fixer: kill(-1) signals every fixer process in one kernel
        # pass (no fork race). Pass 2, as root: pkill by uid catches anything
        # pass 1 could not reach.
        assert calls == [
            [paths.setpriv, *TestCommandShape.SETPRIV_FLAGS, "--", paths.kill, "-9", "--", "-1"],
            [paths.pkill, "-KILL", "-u", "10002"],
        ]
        for env in envs:
            assert set(env) == {"PATH", "HOME", "LANG", "CI"}

    def test_second_sweep_pass_runs_when_the_first_fails(self, paths):
        calls: list[list[str]] = []

        def _run(cmd, **kw):
            calls.append(cmd)
            if cmd[0] == paths.setpriv:
                raise OSError("setpriv gone")

            class R:
                returncode = 1

            return R()

        Sandbox(paths, run=_run).sweep()
        assert [c[0] for c in calls] == [paths.setpriv, paths.pkill]

    def test_sweep_failure_is_swallowed(self, paths):
        def _run(cmd, **kw):
            raise OSError("setpriv gone")

        Sandbox(paths, run=_run).sweep()  # no raise

    def test_reap_collects_zombies_until_none(self, monkeypatch):
        results = iter([(101, 0), (102, 9), (0, 0)])
        monkeypatch.setattr(sandbox.os, "waitpid", lambda pid, flags: next(results))
        assert sandbox.reap_zombies() == [101, 102]

    def test_reap_without_children(self, monkeypatch):
        def _none(pid, flags):
            raise ChildProcessError

        monkeypatch.setattr(sandbox.os, "waitpid", _none)
        assert sandbox.reap_zombies() == []

    def test_output_is_captured_and_capped(self, paths):
        clock = FakeClock()
        proc = FakeProc(clock, exits_at=0.0)

        def _popen(cmd, **kw):
            kw["stdout"].write(b"x" * 100 + b"END")
            kw["stderr"].write(b"err-tail")
            return proc

        sb = Sandbox(
            paths,
            popen=_popen,
            clock=clock,
            sleep=clock.sleep,
            sweeper=lambda: None,
            reaper=lambda: None,
        )
        res = sb.run(["true"], cwd="/w", timeout=5, max_output=10)
        assert res.stdout == "xxxxxxxEND"
        assert res.stderr == "err-tail"

    def test_stdin_bytes_are_passed_as_a_file(self, paths):
        clock = FakeClock()
        seen: dict[str, bytes] = {}

        def _popen(cmd, **kw):
            seen["stdin"] = kw["stdin"].read()
            return FakeProc(clock, exits_at=0.0)

        Sandbox(
            paths,
            popen=_popen,
            clock=clock,
            sleep=clock.sleep,
            sweeper=lambda: None,
            reaper=lambda: None,
        ).run(["cat"], cwd="/w", timeout=5, stdin=b"prompt text")
        assert seen["stdin"] == b"prompt text"

    def test_sweep_and_reap_run_even_if_waiting_raises(self, paths):
        clock = FakeClock()
        events: list[str] = []

        class Exploding(FakeProc):
            def poll(self):
                raise RuntimeError("poll failed")

        sb, _ = _sandbox(paths, Exploding(clock, exits_at=0.0), clock, events)
        with pytest.raises(RuntimeError):
            sb.run(["true"], cwd="/w", timeout=5)
        assert events[-2:] == ["sweep", "reap"]


# ---------------------------------------------------------------------------
# S-182 fix round 3: srt's proxy host must resolve inside the sandbox
# ---------------------------------------------------------------------------

NSS_OK = "passwd: files\nhosts:          files myhostname dns\nnetworks: files\n"


@pytest.fixture
def nss(tmp_path: Path) -> dict[str, Any]:
    """An empty, read-only hosts file (as on AgentCore), an nsswitch.conf with
    ``myhostname`` before ``dns``, and a lib dir holding the NSS module."""
    hosts = tmp_path / "etc-hosts"
    hosts.write_text("")
    hosts.chmod(0o444)
    nsswitch = tmp_path / "nsswitch.conf"
    nsswitch.write_text(NSS_OK)
    libdir = tmp_path / "lib"
    libdir.mkdir()
    (libdir / sandbox.NSS_MYHOSTNAME_LIB).write_text("")
    return {
        "hosts_path": str(hosts),
        "nsswitch_path": str(nsswitch),
        "lib_dirs": (str(tmp_path / "missing-lib"), str(libdir)),
    }


class TestLocalhostResolution:
    """Re-probes 2b and 2c: inside srt's network namespace there is no DNS, and
    srt (and the CLI's own Bash sandbox) point every proxy variable at
    ``localhost``. AgentCore's ``/etc/hosts`` is empty **and read-only**, so the
    wrapper can't add an entry (fix round 2 failed closed on 2c). The image
    resolves ``localhost`` through NSS (``libnss-myhostname``); before every
    run the wrapper only *checks* that one of the two routes is in place, and
    never writes ``/etc/hosts``."""

    @pytest.mark.parametrize(
        "text",
        [
            "127.0.0.1\tlocalhost\n",
            "127.0.0.1 localhost localhost.localdomain\n",
            "::1 localhost ip6-localhost\n",
            "# comment\n10.0.0.5 box\n127.0.0.1   localhost # trailing\n",
        ],
    )
    def test_loopback_entry_in_hosts_is_via_hosts(self, tmp_path, text):
        hosts = tmp_path / "hosts"
        hosts.write_text(text)
        got = sandbox.check_localhost_resolution(
            str(hosts), str(tmp_path / "no-nsswitch"), lib_dirs=()
        )
        assert got == "hosts"
        assert hosts.read_text() == text

    def test_empty_read_only_hosts_with_nss_is_via_nss(self, nss):
        assert sandbox.check_localhost_resolution(**nss) == "nss"
        assert Path(nss["hosts_path"]).read_text() == ""

    @pytest.mark.parametrize(
        "text",
        [
            "# 127.0.0.1 localhost\n",
            "127.0.0.1 localhost.localdomain\n",
            "10.0.0.5 localhost\n",
            "169.254.1.1 box",
        ],
    )
    def test_hosts_without_a_loopback_mapping_falls_back_to_nss(self, nss, text):
        hosts = Path(nss["hosts_path"])
        hosts.chmod(0o644)
        hosts.write_text(text)
        assert sandbox.check_localhost_resolution(**nss) == "nss"
        assert hosts.read_text() == text

    def test_malformed_hosts_line_is_skipped(self, nss):
        hosts = Path(nss["hosts_path"])
        hosts.chmod(0o644)
        hosts.write_text("not-an-ip localhost\n")
        assert sandbox.check_localhost_resolution(**nss) == "nss"

    def test_unreadable_hosts_is_reported_with_the_nss_reason(self, nss, tmp_path):
        # A directory: open() fails with an OSError that isn't FileNotFoundError.
        nss["hosts_path"] = str(tmp_path)
        assert sandbox.check_localhost_resolution(**nss) == "nss"
        Path(nss["nsswitch_path"]).write_text("hosts: files dns\n")
        with pytest.raises(SandboxUnavailable) as exc:
            sandbox.check_localhost_resolution(**nss)
        assert f"{tmp_path}: " in str(exc.value)
        assert "so no loopback entry" in str(exc.value)

    def test_missing_hosts_file_is_not_created(self, nss, tmp_path):
        nss["hosts_path"] = str(tmp_path / "absent-hosts")
        assert sandbox.check_localhost_resolution(**nss) == "nss"
        assert not (tmp_path / "absent-hosts").exists()

    @pytest.mark.parametrize(
        "line",
        [
            "hosts: files myhostname dns",
            "hosts: files myhostname",
            "hosts:\tmyhostname files dns",
            "hosts: files mdns4_minimal myhostname dns # trailing comment",
        ],
    )
    def test_myhostname_before_dns_or_without_dns_is_accepted(self, nss, line):
        Path(nss["nsswitch_path"]).write_text(f"passwd: files\n{line}\n")
        assert sandbox.check_localhost_resolution(**nss) == "nss"

    @pytest.mark.parametrize(
        ("text", "reason"),
        [
            ("hosts: files dns\n", "myhostname"),
            ("hosts: files dns myhostname\n", "after dns"),
            ("# hosts: files myhostname dns\nhosts: files dns\n", "myhostname"),
            ("passwd: files\n", "no hosts line"),
            ("hosts: files [NOTFOUND=return] myhostname dns\n", "return"),
        ],
    )
    def test_nsswitch_without_a_usable_myhostname_is_unavailable(self, nss, text, reason):
        Path(nss["nsswitch_path"]).write_text(text)
        with pytest.raises(SandboxUnavailable) as exc:
            sandbox.check_localhost_resolution(**nss)
        msg = str(exc.value)
        assert msg.startswith("sandbox cannot resolve localhost: ")
        assert reason in msg
        assert "no loopback entry" in msg

    def test_missing_nsswitch_is_unavailable(self, nss, tmp_path):
        nss["nsswitch_path"] = str(tmp_path / "absent-nsswitch")
        with pytest.raises(SandboxUnavailable) as exc:
            sandbox.check_localhost_resolution(**nss)
        assert "absent-nsswitch" in str(exc.value)

    def test_missing_nss_module_is_unavailable(self, nss):
        nss["lib_dirs"] = nss["lib_dirs"][:1]
        with pytest.raises(SandboxUnavailable) as exc:
            sandbox.check_localhost_resolution(**nss)
        assert sandbox.NSS_MYHOSTNAME_LIB in str(exc.value)

    def test_never_writes_hosts(self):
        assert not hasattr(sandbox, "ensure_loopback_hosts")
        assert not hasattr(sandbox, "LOOPBACK_HOSTS_LINE")

    def test_default_paths(self):
        p = sandbox.DEFAULT_PATHS
        assert p.hosts == "/etc/hosts"
        assert p.nsswitch == "/etc/nsswitch.conf"
        # Debian arm64 (the image) and amd64, merged /usr or not.
        for d in ("/usr/lib/aarch64-linux-gnu", "/lib/aarch64-linux-gnu"):
            assert d in p.nss_lib_dirs
        assert sandbox.NSS_MYHOSTNAME_LIB == "libnss_myhostname.so.2"

    def _nss_paths(self, paths: SandboxPaths, nss: dict[str, Any]) -> SandboxPaths:
        return paths._replace(
            hosts=nss["hosts_path"], nsswitch=nss["nsswitch_path"], nss_lib_dirs=nss["lib_dirs"]
        )

    @pytest.mark.parametrize("mode", list(Mode))
    def test_run_checks_before_spawning(self, paths, nss, mode):
        clock = FakeClock()
        seen: dict[str, str] = {}
        p = self._nss_paths(paths, nss)

        def _popen(cmd, **kw):
            seen["via"] = sb.localhost_via
            return FakeProc(clock, exits_at=0.0)

        sb = Sandbox(
            p,
            popen=_popen,
            clock=clock,
            sleep=clock.sleep,
            sweeper=lambda: None,
            reaper=lambda: None,
        )
        argv = [p.claude, "-p", "x"] if mode is Mode.CLI else ["true"]
        sb.run(argv, mode=mode, cwd="/w", timeout=5)
        assert seen["via"] == "nss"
        assert Path(p.hosts).read_text() == ""

    def test_run_refuses_to_spawn_when_localhost_cannot_resolve(self, paths, nss, tmp_path):
        Path(nss["nsswitch_path"]).write_text("hosts: files dns\n")
        calls: list[Any] = []
        sb = Sandbox(
            self._nss_paths(paths, nss),
            popen=lambda *a, **k: calls.append(a),
            sweeper=lambda: None,
        )
        with pytest.raises(SandboxUnavailable, match="cannot resolve localhost"):
            sb.run(["true"], cwd="/w", timeout=5)
        assert calls == []
        assert sb.localhost_via == "none"

    def test_localhost_via_starts_unchecked_and_records_the_route(self, paths, nss):
        sb = Sandbox(paths)
        assert sb.localhost_via == "unchecked"
        assert sb.check_localhost() == "hosts"
        assert sb.localhost_via == "hosts"
        sb = Sandbox(self._nss_paths(paths, nss))
        assert sb.check_localhost() == "nss"
        assert sb.localhost_via == "nss"


class TestCliDisallowedTools:
    """S-182 fix round 2 (defence in depth): every headless ``claude -p`` run gets
    ``--disallowedTools=WebFetch,WebSearch`` on top of the managed deny, as one
    token (the option is variadic) placed straight after the binary."""

    FLAG = "--disallowedTools=WebFetch,WebSearch"

    def test_flag_constant(self):
        assert sandbox.CLI_DISALLOWED_TOOLS == ("WebFetch", "WebSearch")
        assert sandbox.CLI_DISALLOWED_FLAG == self.FLAG

    @pytest.mark.parametrize("print_flag", ["-p", "--print"])
    def test_print_runs_get_the_flag_right_after_the_binary(self, paths, print_flag):
        cmd = Sandbox(paths).build_command(
            Mode.CLI, [paths.claude, print_flag, "do it", "--output-format", "json"]
        )
        i = cmd.index(paths.claude)
        assert cmd[i + 1] == self.FLAG
        assert cmd[i + 2 :] == [print_flag, "do it", "--output-format", "json"]
        assert cmd.count(self.FLAG) == 1

    def test_version_run_is_unchanged(self, paths):
        cmd = Sandbox(paths).build_command(Mode.CLI, [paths.claude, "--version"])
        assert cmd[-2:] == [paths.claude, "--version"]
        assert self.FLAG not in cmd

    def test_not_duplicated_when_caller_already_passes_it(self, paths):
        cmd = Sandbox(paths).build_command(Mode.CLI, [paths.claude, self.FLAG, "-p", "x"])
        assert cmd.count(self.FLAG) == 1

    def test_script_mode_never_gets_it(self, paths):
        cmd = Sandbox(paths).build_command(Mode.SCRIPT, ["npm", "-p", "x"])
        assert self.FLAG not in cmd


# ---------------------------------------------------------------------------
# qa-engineer completion gate (S-182): kill path on error, flag strength,
# and nsswitch action-block parsing
# ---------------------------------------------------------------------------


class TestKillOnError:
    """If waiting for the child fails for any reason, including a
    ``BaseException`` such as ``KeyboardInterrupt``, the child gets SIGKILL
    before the post-run sweep and reap, so no fixer process outlives the run."""

    @pytest.mark.parametrize("exc", [RuntimeError, KeyboardInterrupt])
    def test_child_is_killed_then_swept_and_reaped(self, paths, exc):
        clock = FakeClock()
        events: list[str] = []

        class Exploding(FakeProc):
            def poll(self):
                raise exc("poll failed")

        sb, _ = _sandbox(paths, Exploding(clock, exits_at=0.0), clock, events)
        with pytest.raises(exc):
            sb.run(["true"], cwd="/w", timeout=5)
        assert events == [f"signal:{int(signal.SIGKILL)}", "sweep", "reap"]


class TestCliDisallowedToolsStrength:
    """A caller-supplied, weaker ``--disallowedTools`` value never replaces the
    wrapper's own flag: only the exact full token counts as already present."""

    @pytest.mark.parametrize(
        "weaker",
        ["--disallowedTools=WebFetch", "--disallowedTools=WebSearch", "--disallowedTools="],
    )
    def test_weaker_caller_value_still_gets_the_full_flag(self, paths, weaker):
        cmd = Sandbox(paths).build_command(Mode.CLI, [paths.claude, weaker, "-p", "x"])
        i = cmd.index(paths.claude)
        assert cmd[i + 1] == sandbox.CLI_DISALLOWED_FLAG
        assert weaker in cmd[i + 2 :]


class TestNsswitchActionBlocks:
    """glibc's nsswitch parser allows whitespace inside ``[...]`` blocks, around
    ``=``, and several ``STATUS=action`` pairs in one block. Each line below
    stops the lookup after ``files`` (empty ``/etc/hosts`` -> NOTFOUND ->
    return), so ``myhostname`` is never reached and the preflight must refuse.

    Known defect: ``_nss_hosts_reason`` only inspects single tokens that
    start with ``[`` and contain ``=return``, so these forms pass the
    preflight (fail-open). Mitigated in the shipped image: the Dockerfile
    writes the exact line ``hosts: files myhostname dns`` and image-smoke
    asserts it. Strict xfail: remove the marker once the parser is fixed."""

    @pytest.mark.xfail(
        strict=True,
        reason="S-182 QA gap: multi-token [..=return] action blocks are not detected",
    )
    @pytest.mark.parametrize(
        "line",
        [
            "hosts: files [ NOTFOUND=return ] myhostname dns",
            "hosts: files [NOTFOUND = return] myhostname dns",
            "hosts: files [SUCCESS=continue NOTFOUND=return] myhostname dns",
        ],
    )
    def test_spaced_or_multi_action_return_block_is_refused(self, nss, line):
        Path(nss["nsswitch_path"]).write_text(f"{line}\n")
        with pytest.raises(SandboxUnavailable, match="return"):
            sandbox.check_localhost_resolution(**nss)

    @pytest.mark.parametrize(
        "line",
        [
            "hosts: files [NOTFOUND=RETURN] myhostname dns",
            "hosts: files [!UNAVAIL=return] myhostname dns",
        ],
    )
    def test_single_token_return_block_any_case_is_refused(self, nss, line):
        Path(nss["nsswitch_path"]).write_text(f"{line}\n")
        with pytest.raises(SandboxUnavailable, match="can return before myhostname"):
            sandbox.check_localhost_resolution(**nss)

    def test_continue_block_ahead_of_myhostname_is_accepted(self, nss):
        Path(nss["nsswitch_path"]).write_text("hosts: files [NOTFOUND=continue] myhostname dns\n")
        assert sandbox.check_localhost_resolution(**nss) == "nss"
