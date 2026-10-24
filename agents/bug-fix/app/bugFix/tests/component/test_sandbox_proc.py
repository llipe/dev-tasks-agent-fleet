"""L2 tests for ``sandbox.py`` with real processes (S-182 tasks 3.1, 3.17; TC-182-03, TC-182-05).

The real command chain runs: ``<setpriv> --reuid=10002 ... --no-new-privs --
<python> -I fixer_exec.py <srt> --settings <file> -- <command>``. Only the two
privileged pieces are replaced by exec-through shims, because a developer
machine or CI runner is not root, has no ``fixer`` user and no ``bwrap``
sandbox:

- ``fake-setpriv`` drops its options up to ``--`` and execs the rest (the
  real ``setpriv`` passes the env through unchanged, like the shim);
- ``fake-srt`` checks ``--settings <file> --`` and execs the rest (absolute
  path, no shell).

``fixer_exec.py`` is the real script, so the env the command sees is the real
rebuilt allow-list. The production sweep (``kill -9 -- -1`` as fixer, then
``pkill -KILL -u 10002`` as root) would kill every process of the current
user here, so the test injects a
sweeper scoped to a per-test marker; the production sweep itself is asserted
against the built image by ``scripts/image-smoke.sh``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

import pytest

import sandbox
from sandbox import Mode, Outcome, Sandbox, SandboxPaths

PKG = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("pkill") is None,
    reason="needs a POSIX host with pkill",
)


def _shim(path: Path, body: str) -> str:
    path.write_text("#!/bin/sh\n" + textwrap.dedent(body))
    path.chmod(0o755)
    return str(path)


@pytest.fixture
def marker() -> str:
    return f"bugfix-sbx-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def chain(tmp_path: Path, marker: str):
    fake_setpriv = _shim(
        tmp_path / "fake-setpriv",
        """\
        while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done
        shift
        exec "$@"
        """,
    )
    # Python, not sh: a shell would add PWD/SHLVL after fixer_exec.py ran.
    fake_srt_path = tmp_path / "fake-srt"
    fake_srt_path.write_text(
        f"#!{sys.executable}\n"
        + textwrap.dedent(
            """\
            import os, sys
            a = sys.argv[1:]
            if a[:1] != ["--settings"] or not os.path.isfile(a[1]) or a[2] != "--":
                sys.exit(90)
            os.execv(a[3], a[3:])
            """
        )
    )
    fake_srt_path.chmod(0o755)
    fake_srt = str(fake_srt_path)
    settings = tmp_path / "srt-settings.json"
    settings.write_text("{}")
    paths = SandboxPaths(
        setpriv=fake_setpriv,
        python=sys.executable,
        fixer_exec=str(PKG / "fixer_exec.py"),
        srt=fake_srt,
        srt_settings=str(settings),
        claude=str(tmp_path / "claude"),
        kill="/bin/kill",
        pkill=shutil.which("pkill") or "/usr/bin/pkill",
    )

    def _sweep() -> None:
        subprocess.run(["pkill", "-KILL", "-f", marker], check=False)

    return paths, _sweep


def _alive(marker: str) -> list[str]:
    out = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True, check=False)
    return [line for line in out.stdout.split() if line.strip()]


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", textwrap.dedent(code)]


class TestRealChain:
    def test_env_seen_by_the_command_is_the_allow_list(self, chain, tmp_path, monkeypatch):
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIASENTINEL")
        monkeypatch.setenv("GITHUB_PROJECTS_TOKEN", "ghp_" + "c" * 36)
        paths, sweep = chain
        sb = Sandbox(paths, sweeper=sweep)
        res = sb.run(
            _py("import json, os; print(json.dumps(dict(os.environ)))"),
            cwd=str(tmp_path),
            timeout=20,
            anthropic_api_key="sk-ant-api03-sentinel-0123456789",
        )
        assert res.outcome is Outcome.OK, res.stderr
        env = json.loads(res.stdout.strip().splitlines()[-1])
        # The polluted names never reach the command: the spawn env is the
        # allow-list, and fixer_exec.py rebuilds it again before the exec.
        # macOS injects __CF_USER_TEXT_ENCODING into every process it starts.
        env.pop("__CF_USER_TEXT_ENCODING", None)
        assert set(env) == {
            "ANTHROPIC_API_KEY",
            "PATH",
            "HOME",
            "LANG",
            "CI",
        }
        assert env["HOME"] == "/home/fixer"
        assert env["CI"] == "1"

    def test_exit_code_and_output(self, chain, tmp_path):
        paths, sweep = chain
        res = Sandbox(paths, sweeper=sweep).run(
            _py("import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"),
            cwd=str(tmp_path),
            timeout=20,
        )
        assert res.outcome is Outcome.FAILED
        assert res.exit_code == 3
        assert res.stdout.strip() == "out"
        assert res.stderr.strip() == "err"

    def test_stdin_reaches_the_command(self, chain, tmp_path):
        paths, sweep = chain
        res = Sandbox(paths, sweeper=sweep).run(
            _py("import sys; print(sys.stdin.read().upper())"),
            cwd=str(tmp_path),
            timeout=20,
            stdin=b"prompt",
        )
        assert res.stdout.strip() == "PROMPT"

    def test_missing_command_maps_to_not_found(self, chain, tmp_path):
        paths, sweep = chain
        res = Sandbox(paths, sweeper=sweep).run(
            ["/nonexistent/bugfix-binary"], cwd=str(tmp_path), timeout=20
        )
        assert res.outcome in (Outcome.NOT_FOUND, Outcome.NOT_EXECUTABLE, Outcome.FAILED)
        assert res.exit_code != 0


class TestTimeoutReal:
    """TC-182-03 with a short grace instead of 15 s."""

    def test_sigterm_ignored_child_is_killed_after_grace(self, chain, tmp_path, marker):
        paths, sweep = chain
        sb = Sandbox(paths, sweeper=sweep, kill_grace=0.5, poll_interval=0.05)
        started = time.monotonic()
        res = sb.run(
            _py(
                f"""
                import signal, time
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                marker = {marker!r}
                print('ready', flush=True)
                time.sleep(60)
                """
            ),
            cwd=str(tmp_path),
            timeout=0.5,
        )
        elapsed = time.monotonic() - started
        assert res.timed_out is True
        assert res.outcome is Outcome.TIMEOUT
        assert res.exit_code == -9  # SIGKILL, not a normal exit
        assert 0.9 <= elapsed < 10, elapsed

    def test_sigterm_honoured_child_stops_without_sigkill(self, chain, tmp_path):
        paths, sweep = chain
        sb = Sandbox(paths, sweeper=sweep, kill_grace=5, poll_interval=0.05)
        started = time.monotonic()
        res = sb.run(_py("import time; time.sleep(60)"), cwd=str(tmp_path), timeout=0.5)
        assert res.outcome is Outcome.TIMEOUT
        assert res.exit_code == -15
        assert time.monotonic() - started < 4


class TestNoSurvivors:
    """TC-182-05: a daemonized grandchild does not outlive the step."""

    def test_daemonized_grandchild_is_swept(self, chain, tmp_path, marker):
        paths, sweep = chain
        sb = Sandbox(paths, sweeper=sweep, poll_interval=0.05)
        res = sb.run(
            _py(
                f"""
                import subprocess, sys
                # A new session, like `setsid sleep 1000 &`. The marker sits
                # in the daemon's own argv so the scoped test sweep can find it.
                subprocess.Popen(
                    [sys.executable, '-c', 'import time; time.sleep(1000)  # {marker}'],
                    start_new_session=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                print('spawned')
                """
            ),
            cwd=str(tmp_path),
            timeout=20,
        )
        assert res.outcome is Outcome.OK, res.stderr
        time.sleep(0.2)
        assert _alive(marker) == []

    def test_daemon_is_swept_after_timeout_too(self, chain, tmp_path, marker):
        paths, sweep = chain
        sb = Sandbox(paths, sweeper=sweep, kill_grace=0.3, poll_interval=0.05)
        res = sb.run(
            _py(
                f"""
                import subprocess, sys, time
                subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(1000)  # {marker}'],
                                 start_new_session=True, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
                time.sleep(60)
                """
            ),
            cwd=str(tmp_path),
            timeout=0.5,
        )
        assert res.timed_out
        time.sleep(0.2)
        assert _alive(marker) == []

    def test_no_zombie_left_for_the_direct_child(self, chain, tmp_path):
        paths, sweep = chain
        Sandbox(paths, sweeper=sweep).run(["/usr/bin/true"], cwd=str(tmp_path), timeout=20)
        assert sandbox.reap_zombies() == []


class TestModes:
    def test_cli_mode_execs_the_configured_claude(self, chain, tmp_path):
        paths, sweep = chain
        claude = _shim(tmp_path / "claude", 'echo "claude-args:$*"\n')
        paths = paths._replace(claude=claude)
        res = Sandbox(paths, sweeper=sweep).run(
            [claude, "-p", "hi"], mode=Mode.CLI, cwd=str(tmp_path), timeout=20
        )
        assert res.stdout.strip() == "claude-args:-p hi"
