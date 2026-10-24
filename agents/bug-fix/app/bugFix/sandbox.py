"""
sandbox — start ``fixer`` subprocesses (S-182; D-51, D-62, D-109).

uid switch, minimal env, sandbox runtime, wall-clock timeout, no survivors.

Every process that runs model output or repo-controlled code starts here, as
uid ``fixer``, never in the wrapper's own process or with its env (spec §7, §12):

1. **uid switch (D-109).** ``sudo -n -u fixer`` through the one sudoers rule
   ``wrapper ALL=(fixer) NOPASSWD: ALL`` (``env_reset``, fixed ``secure_path``).
2. **Minimal env (D-51 layer 1).** The spawn gets an env built from an
   allow-list, never from ``os.environ``: ``ANTHROPIC_API_KEY`` (only when the
   caller passes it), ``PATH``, ``HOME=/home/fixer``, ``LANG``, ``CI=1``. Only
   those names cross ``sudo`` (``--preserve-env=<names>``), and
   ``fixer_exec.py`` rebuilds the final env from the same allow-list, dropping
   what ``sudo`` adds. No secret is ever put in argv.
3. **Sandbox (D-51 layers 2-3).** Two modes, and no third:

   - :attr:`Mode.SCRIPT` — install, gates, changed tests and probe helpers run
     under ``srt`` (``@anthropic-ai/sandbox-runtime``, the runtime Claude
     Code's own Bash sandbox is built on) with ``/etc/bug-fix/srt-settings.json``:
     the same registry-only network allow-list as the managed policy, a fresh
     pid namespace and ``/proc``, and no network namespace (all traffic goes
     through srt's filtering proxy).
   - :attr:`Mode.CLI` — only the pinned ``claude`` binary, which enforces its
     own Bash sandbox from ``/etc/claude-code/managed-settings.json``. Nesting
     ``claude`` inside ``srt`` would cut it off from the Anthropic API.

   A bare exec (sudo straight to an arbitrary command) is never built.
4. **Wall-clock timeout.** SIGTERM at the deadline (``sudo`` relays it). If the
   child is still alive after :data:`KILL_GRACE_SECONDS` (15 s), every
   ``fixer`` process is swept and the child gets SIGKILL (``sudo`` does not
   relay SIGKILL).
5. **No survivors (D-62).** After the child exits, for any reason, the wrapper
   sweeps every ``fixer`` process (``sudo -u fixer kill -9 -- -1``), so a
   daemon left behind can't touch ``/work/repo`` while the wrapper reads it,
   then reaps zombies (the wrapper may be pid 1 in the container).

Sandbox runs are serialized by a module lock: the zombie reaper waits for any
child, which is only safe while no other ``Popen`` of this process is live.
"""

from __future__ import annotations

import contextlib
import enum
import os
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import IO, Any, NamedTuple

FIXER_USER = "fixer"
FIXER_HOME = "/home/fixer"
FIXER_PATH = "/usr/local/bin:/usr/bin:/bin"
DEFAULT_LANG = "C.UTF-8"

# The child's env, by name (D-51). fixer_exec.ALLOWED must be equal.
ALLOWED_ENV: tuple[str, ...] = ("ANTHROPIC_API_KEY", "PATH", "HOME", "LANG", "CI")
# The names that cross sudo. PATH and HOME are fixed again by fixer_exec.py.
_PRESERVED: tuple[str, ...] = ("ANTHROPIC_API_KEY", "LANG", "CI")

KILL_GRACE_SECONDS = 15.0
POLL_INTERVAL_SECONDS = 0.2
SWEEP_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_OUTPUT = 64 * 1024

_RUN_LOCK = threading.Lock()


class SandboxError(Exception):
    """A sandboxed run could not be started."""


class SandboxUnavailable(SandboxError):
    """A binary or file the sandbox needs is missing or not executable.

    Raised instead of ``FileNotFoundError`` so callers map it to one outcome.
    The message names the role and the path, never an env value.
    """


class Mode(enum.StrEnum):
    SCRIPT = "script"
    CLI = "cli"


class Outcome(enum.StrEnum):
    OK = "ok"
    FAILED = "failed"
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"
    NOT_EXECUTABLE = "not_executable"
    SIGNALED = "signaled"


# Exit-code mapping. A timeout wins over any code; a negative code (Popen's
# "killed by signal N") or 128+N (a shell's) is SIGNALED; anything else
# non-zero is FAILED.
EXIT_CODE_TABLE: dict[int, Outcome] = {
    0: Outcome.OK,
    126: Outcome.NOT_EXECUTABLE,
    127: Outcome.NOT_FOUND,
}


def map_exit(code: int | None, timed_out: bool) -> Outcome:
    if timed_out:
        return Outcome.TIMEOUT
    if code is None:
        return Outcome.FAILED
    if code in EXIT_CODE_TABLE:
        return EXIT_CODE_TABLE[code]
    if code < 0 or 128 < code < 160:
        return Outcome.SIGNALED
    return Outcome.FAILED


class SandboxPaths(NamedTuple):
    sudo: str = "/usr/bin/sudo"
    python: str = "/usr/local/bin/python3"
    fixer_exec: str = "/app/fixer_exec.py"
    srt: str = "/usr/bin/srt"
    srt_settings: str = "/etc/bug-fix/srt-settings.json"
    claude: str = "/usr/bin/claude"
    kill: str = "/usr/bin/kill"


DEFAULT_PATHS = SandboxPaths()


@dataclass(frozen=True)
class SandboxResult:
    outcome: Outcome
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
    duration_s: float

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.OK


def build_env(anthropic_api_key: str | None = None, lang: str = DEFAULT_LANG) -> dict[str, str]:
    """The env handed to the spawn: the allow-list, built from scratch.

    Nothing is read from ``os.environ``. The Anthropic key is included only
    when the caller passes it (the CLI needs it; repo scripts don't).
    """
    env = {"PATH": FIXER_PATH, "HOME": FIXER_HOME, "LANG": lang, "CI": "1"}
    if anthropic_api_key:
        env["ANTHROPIC_API_KEY"] = anthropic_api_key
    return env


def fixer_prefix(paths: SandboxPaths, preserve: Sequence[str]) -> list[str]:
    """``sudo -n -u fixer --preserve-env=<names> -- python3 -I fixer_exec.py``.

    ``preserve`` is filtered to the allow-list, so no caller can widen it.
    """
    names = [n for n in _PRESERVED if n in preserve]
    return [
        paths.sudo,
        "-n",
        "-u",
        FIXER_USER,
        f"--preserve-env={','.join(names)}",
        "--",
        paths.python,
        "-I",
        paths.fixer_exec,
    ]


def reap_zombies() -> list[int]:
    """Reap every exited child (orphans reparented to the wrapper as pid 1)."""
    reaped: list[int] = []
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return reaped
        if pid == 0:
            return reaped
        reaped.append(pid)


def _tail(f: IO[bytes], max_output: int) -> str:
    f.flush()
    size = f.seek(0, os.SEEK_END)
    f.seek(max(0, size - max_output))
    return f.read().decode("utf-8", "replace")


class Sandbox:
    def __init__(
        self,
        paths: SandboxPaths = DEFAULT_PATHS,
        *,
        kill_grace: float = KILL_GRACE_SECONDS,
        poll_interval: float = POLL_INTERVAL_SECONDS,
        popen: Callable[..., Any] = subprocess.Popen,
        run: Callable[..., Any] = subprocess.run,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        kill: Callable[[int, int], None] = os.kill,
        sweeper: Callable[[], None] | None = None,
        reaper: Callable[[], object] | None = None,
    ) -> None:
        self.paths = paths
        self.kill_grace = kill_grace
        self.poll_interval = poll_interval
        self._popen = popen
        self._run = run
        self._clock = clock
        self._sleep = sleep
        self._kill = kill
        self._sweeper = sweeper or self.sweep
        self._reaper = reaper or reap_zombies

    # ------------------------------------------------------------ availability

    def _required(self, mode: Mode) -> list[tuple[str, str, bool]]:
        """(role, path, must be executable) for ``mode``."""
        p = self.paths
        common = [
            ("sudo", p.sudo, True),
            ("python", p.python, True),
            ("fixer_exec", p.fixer_exec, False),
        ]
        if mode is Mode.SCRIPT:
            return [*common, ("srt", p.srt, True), ("srt_settings", p.srt_settings, False)]
        return [*common, ("claude", p.claude, True)]

    def check_available(self, mode: Mode) -> None:
        for role, path, executable in self._required(mode):
            if not os.path.isfile(path):
                raise SandboxUnavailable(f"sandbox {role} is missing: {path}")
            if executable and not os.access(path, os.X_OK):
                raise SandboxUnavailable(f"sandbox {role} is not executable: {path}")

    # ------------------------------------------------------------ command shape

    def build_command(self, mode: Mode, argv: Sequence[str], preserve: Sequence[str]) -> list[str]:
        if not argv:
            raise ValueError("empty command")
        prefix = fixer_prefix(self.paths, preserve)
        if mode is Mode.SCRIPT:
            return [*prefix, self.paths.srt, "--settings", self.paths.srt_settings, "--", *argv]
        if argv[0] != self.paths.claude:
            raise ValueError("CLI mode runs only the pinned claude binary")
        return [*prefix, *argv]

    # ------------------------------------------------------------ running

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str,
        timeout: float,
        mode: Mode = Mode.SCRIPT,
        anthropic_api_key: str | None = None,
        stdin: bytes | None = None,
        max_output: int = DEFAULT_MAX_OUTPUT,
    ) -> SandboxResult:
        """Run ``argv`` as ``fixer`` in the sandbox. Output is returned unscrubbed:
        callers pass it through ``scrubber.tail`` before it leaves the process."""
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.check_available(mode)
        env = build_env(anthropic_api_key)
        cmd = self.build_command(mode, argv, list(env))

        with (
            _RUN_LOCK,
            tempfile.TemporaryFile() as out_f,
            tempfile.TemporaryFile() as err_f,
            tempfile.TemporaryFile() as in_f,
        ):
            if stdin is not None:
                in_f.write(stdin)
                in_f.flush()
                in_f.seek(0)
            started = self._clock()
            try:
                proc = self._popen(
                    cmd,
                    env=env,
                    cwd=cwd,
                    stdin=in_f if stdin is not None else subprocess.DEVNULL,
                    stdout=out_f,
                    stderr=err_f,
                    start_new_session=True,
                    close_fds=True,
                )
            except FileNotFoundError as exc:
                raise SandboxUnavailable(f"sandbox could not start: {exc.filename}") from None

            timed_out = False
            try:
                if not self._wait_until(proc, started + timeout):
                    timed_out = True
                    self._signal(proc, signal.SIGTERM)
                    if not self._wait_until(proc, self._clock() + self.kill_grace):
                        self._sweeper()
                        self._signal(proc, signal.SIGKILL)
                code = proc.wait()
            except BaseException:
                self._signal(proc, signal.SIGKILL)
                raise
            finally:
                self._sweeper()
                self._reaper()

            return SandboxResult(
                outcome=map_exit(code, timed_out),
                exit_code=code,
                timed_out=timed_out,
                stdout=_tail(out_f, max_output),
                stderr=_tail(err_f, max_output),
                duration_s=self._clock() - started,
            )

    def _wait_until(self, proc: Any, deadline: float) -> bool:
        """True if ``proc`` exited before ``deadline``."""
        while proc.poll() is None:
            if self._clock() >= deadline:
                return False
            self._sleep(self.poll_interval)
        return True

    def _signal(self, proc: Any, sig: int) -> None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            self._kill(proc.pid, sig)

    def sweep(self) -> None:
        """Kill every ``fixer`` process: ``kill -9 -- -1`` run as ``fixer``.

        ``kill(-1)`` signals every process the caller may signal except itself,
        so as ``fixer`` it reaches every ``fixer`` process, daemons and srt's
        pid-namespaced children included, and nothing else. Best effort.
        """
        cmd = [self.paths.sudo, "-n", "-u", FIXER_USER, "--", self.paths.kill, "-9", "--", "-1"]
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            self._run(
                cmd,
                env=build_env(None),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=SWEEP_TIMEOUT_SECONDS,
                check=False,
            )
