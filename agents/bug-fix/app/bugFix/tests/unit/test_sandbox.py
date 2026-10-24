"""L1 tests for ``sandbox.py`` and ``fixer_exec.py`` (S-182 task 3.1; TC-182-01..05; D-51, D-109).

``sandbox.py`` starts every ``fixer`` process through
``sudo -n -u fixer --preserve-env=<allow-listed names> -- python3 -I
fixer_exec.py <runtime> ...``:

- the env handed to the spawn is built from an **allow-list** and never from
  ``os.environ``;
- ``fixer_exec.py`` rebuilds the final environment from the same allow-list,
  dropping whatever ``sudo`` adds (``SUDO_*``, ``USER``, ``MAIL``...);
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

    return SandboxPaths(
        sudo=_exe("sudo"),
        python=_exe("python3"),
        fixer_exec=_exe("fixer_exec.py"),
        srt=_exe("srt"),
        srt_settings=_exe("srt-settings.json"),
        claude=_exe("claude"),
        kill=_exe("kill"),
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

    def test_sudo_preserves_only_allow_listed_names(self, paths):
        clock = FakeClock()
        sb, rec = _sandbox(paths, FakeProc(clock, exits_at=0.0), clock, [])
        sb.run(["true"], cwd="/work/repo", timeout=60, anthropic_api_key=KEY)
        cmd = rec.calls[0][0]
        pres = [a for a in cmd if a.startswith("--preserve-env=")]
        assert len(pres) == 1
        names = set(pres[0].split("=", 1)[1].split(","))
        assert names <= EXPECTED_NAMES
        assert names == {"ANTHROPIC_API_KEY", "LANG", "CI"}
        assert "-E" not in cmd and "--preserve-env" not in cmd

    def test_preserve_list_omits_key_when_none(self, paths):
        clock = FakeClock()
        sb, rec = _sandbox(paths, FakeProc(clock, exits_at=0.0), clock, [])
        sb.run(["true"], cwd="/work/repo", timeout=60)
        cmd = rec.calls[0][0]
        pres = next(a for a in cmd if a.startswith("--preserve-env="))
        assert "ANTHROPIC_API_KEY" not in pres
        assert "ANTHROPIC_API_KEY" not in rec.calls[0][1]["env"]


class TestFixerExecEnv:
    """``fixer_exec.py`` runs as fixer after sudo and rebuilds the env."""

    def test_rebuilds_from_allow_list_dropping_sudo_additions(self):
        after_sudo = {
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
        env = fixer_exec.build_env(after_sudo)
        assert set(env) == EXPECTED_NAMES
        assert env["PATH"] == fixer_exec.FIXER_PATH == sandbox.FIXER_PATH
        assert env["HOME"] == "/home/fixer"
        assert env["ANTHROPIC_API_KEY"] == KEY

    def test_without_key_the_env_has_four_names(self):
        env = fixer_exec.build_env({"LANG": "C.UTF-8", "CI": "1", **POLLUTION})
        assert set(env) == {"PATH", "HOME", "LANG", "CI"}

    def test_main_execs_with_rebuilt_env(self, monkeypatch):
        seen: dict[str, Any] = {}

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

    def test_allow_lists_agree(self):
        assert set(fixer_exec.ALLOWED) == EXPECTED_NAMES == set(sandbox.ALLOWED_ENV)


# ---------------------------------------------------------------------------
# TC-182-02: uid switch and sandbox wrapper
# ---------------------------------------------------------------------------


class TestCommandShape:
    def test_script_mode_switches_to_fixer_and_wraps_in_srt(self, paths):
        cmd = Sandbox(paths).build_command(Mode.SCRIPT, ["npm", "test"], ["CI", "LANG"])
        assert cmd[:4] == [paths.sudo, "-n", "-u", "fixer"]
        dd = cmd.index("--")
        assert cmd[dd + 1 : dd + 4] == [paths.python, "-I", paths.fixer_exec]
        rest = cmd[dd + 4 :]
        assert rest[:3] == [paths.srt, "--settings", paths.srt_settings]
        assert rest[3] == "--"
        assert rest[4:] == ["npm", "test"]

    def test_cli_mode_runs_only_the_claude_binary(self, paths):
        cmd = Sandbox(paths).build_command(Mode.CLI, [paths.claude, "-p"], ["CI"])
        assert cmd[:4] == [paths.sudo, "-n", "-u", "fixer"]
        dd = cmd.index("--")
        assert cmd[dd + 1 : dd + 5] == [paths.python, "-I", paths.fixer_exec, paths.claude]

    @pytest.mark.parametrize("argv0", ["bash", "/bin/sh", "claude-but-not", "/tmp/claude"])
    def test_cli_mode_refuses_any_other_binary(self, paths, argv0):
        with pytest.raises(ValueError):
            Sandbox(paths).build_command(Mode.CLI, [argv0, "-c", "id"], ["CI"])

    def test_empty_argv_refused(self, paths):
        with pytest.raises(ValueError):
            Sandbox(paths).build_command(Mode.SCRIPT, [], ["CI"])

    @pytest.mark.parametrize("mode", list(Mode))
    def test_no_bare_exec_is_ever_built(self, paths, mode):
        argv = [paths.claude, "-p"] if mode is Mode.CLI else ["true"]
        cmd = Sandbox(paths).build_command(mode, argv, ["CI"])
        assert cmd[0] == paths.sudo
        assert "-u" in cmd and cmd[cmd.index("-u") + 1] == "fixer"
        runtime = cmd[cmd.index("--") + 4]
        assert runtime in (paths.srt, paths.claude)

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
        # sudo does not relay SIGKILL: the fixer sweep runs before it.
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
    @pytest.mark.parametrize("field", ["sudo", "python", "fixer_exec", "srt", "srt_settings"])
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
    def test_default_sweeper_kills_every_fixer_process_as_fixer(self, paths):
        calls: list[list[str]] = []

        def _run(cmd, **kw):
            calls.append(cmd)

            class R:
                returncode = 0

            return R()

        sb = Sandbox(paths, run=_run)
        sb.sweep()
        assert calls == [[paths.sudo, "-n", "-u", "fixer", "--", paths.kill, "-9", "--", "-1"]]

    def test_sweep_failure_is_swallowed(self, paths):
        def _run(cmd, **kw):
            raise OSError("sudo gone")

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
