"""
sandbox — start ``fixer`` subprocesses (S-182; D-51, D-62, D-110).

uid drop, minimal env, sandbox runtime, wall-clock timeout, no survivors.

Every process that runs model output or repo-controlled code starts here, as
uid ``fixer``, never in the wrapper's own process or with its env (spec §7, §12):

1. **uid drop (D-110).** The wrapper runs as root. AgentCore starts the
   container with ``no_new_privs`` set, so setuid ``sudo`` can't run (probe
   run 1, which retired D-109). Dropping privileges as root still works:
   every fixer process starts as ``setpriv --reuid=10002 --regid=10002
   --clear-groups --inh-caps=-all --no-new-privs -- ...``. The child has
   uid/gid 10002 (real, effective, saved), no supplementary groups, no
   capabilities and ``no_new_privs`` set, so no setuid binary can take it back
   to root. Nothing but wrapper code runs as root.
2. **Minimal env (D-51 layer 1).** The spawn gets an env built from an
   allow-list, never from ``os.environ``: ``ANTHROPIC_API_KEY`` (only when the
   caller passes it), ``PATH``, ``HOME=/home/fixer``, ``LANG``, ``CI=1``.
   ``setpriv`` passes it through unchanged, and ``fixer_exec.py`` rebuilds the
   final env from the same allow-list (and refuses to exec while still root).
   No secret is ever put in argv.
3. **Sandbox (D-51 layers 2-3).** Two modes, and no third:

   - :attr:`Mode.SCRIPT` — install, gates, changed tests and probe helpers run
     under ``srt`` (``@anthropic-ai/sandbox-runtime``, the runtime Claude
     Code's own Bash sandbox is built on) with ``/etc/bug-fix/srt-settings.json``:
     the same registry-only network allow-list as the managed policy, a fresh
     pid namespace and ``/proc``, and no network namespace (all traffic goes
     through srt's filtering proxy).
   - :attr:`Mode.CLI` — only the pinned ``claude`` binary, which enforces its
     own Bash sandbox from ``/etc/claude-code/managed-settings.json``. Nesting
     ``claude`` inside ``srt`` would cut it off from the Anthropic API. Every
     headless run (``-p``/``--print``) also gets
     ``--disallowedTools=WebFetch,WebSearch``, on top of the managed deny.

   A bare exec (setpriv straight to an arbitrary command) is never built.

   Both runtimes point their proxy variables at ``localhost`` (hard-coded),
   and the sandbox's network namespace has no DNS, so ``localhost`` must come
   from ``/etc/hosts``. The image's ``/etc/hosts`` is empty and AgentCore
   doesn't write one (S-182 re-probe 2b: ``getaddrinfo EAI_AGAIN
   localhost``), so before every run the wrapper adds ``127.0.0.1
   localhost`` if no loopback entry exists (:func:`ensure_loopback_hosts`),
   and refuses to start the run if it can't.
4. **Wall-clock timeout.** SIGTERM at the deadline (``setpriv`` and
   ``fixer_exec.py`` exec, so the child pid is the runtime itself). If it is
   still alive after :data:`KILL_GRACE_SECONDS` (15 s), every ``fixer``
   process is swept and the child gets SIGKILL.
5. **No survivors (D-62).** After the child exits, for any reason, the wrapper
   sweeps every ``fixer`` process, so a daemon left behind can't touch
   ``/work/repo`` while the wrapper reads it, then reaps zombies (the wrapper
   may be pid 1 in the container). The sweep is two passes: ``kill -9 -- -1``
   as ``fixer`` (one kernel pass over every process fixer may signal, which a
   fork loop can't outrun), then ``pkill -KILL -u 10002`` as root.

Sandbox runs are serialized by a module lock: the zombie reaper waits for any
child, which is only safe while no other ``Popen`` of this process is live.
"""

from __future__ import annotations

import contextlib
import enum
import ipaddress
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
FIXER_UID = 10002
FIXER_GID = 10002
FIXER_HOME = "/home/fixer"
FIXER_PATH = "/usr/local/bin:/usr/bin:/bin"
DEFAULT_LANG = "C.UTF-8"

# The child's env, by name (D-51). fixer_exec.ALLOWED must be equal.
ALLOWED_ENV: tuple[str, ...] = ("ANTHROPIC_API_KEY", "PATH", "HOME", "LANG", "CI")

# The drop from root to fixer (D-110). Works under no_new_privs; needs only
# CAP_SETUID and CAP_SETGID in the wrapper.
SETPRIV_FLAGS: tuple[str, ...] = (
    f"--reuid={FIXER_UID}",
    f"--regid={FIXER_GID}",
    "--clear-groups",
    "--inh-caps=-all",
    "--no-new-privs",
)

# Defence in depth on top of the managed deny (S-182 fix round 2): every
# headless run of the CLI gets these tools removed by flag as well. One token,
# because the option is variadic and would swallow a following positional.
CLI_DISALLOWED_TOOLS: tuple[str, ...] = ("WebFetch", "WebSearch")
CLI_DISALLOWED_FLAG = f"--disallowedTools={','.join(CLI_DISALLOWED_TOOLS)}"
_CLI_PRINT_FLAGS = frozenset({"-p", "--print"})

# srt and the CLI's own Bash sandbox point every proxy variable at
# ``localhost`` (hard-coded in both), and the sandbox's network namespace has
# no DNS, so ``localhost`` must come from /etc/hosts (S-182 re-probe 2b).
LOOPBACK_HOSTS_LINE = "127.0.0.1\tlocalhost\n"

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
    setpriv: str = "/usr/bin/setpriv"
    python: str = "/usr/local/bin/python3"
    fixer_exec: str = "/app/fixer_exec.py"
    srt: str = "/usr/bin/srt"
    srt_settings: str = "/etc/bug-fix/srt-settings.json"
    claude: str = "/usr/bin/claude"
    kill: str = "/usr/bin/kill"
    pkill: str = "/usr/bin/pkill"
    hosts: str = "/etc/hosts"


DEFAULT_PATHS = SandboxPaths()


def _maps_localhost_to_loopback(text: str) -> bool:
    for line in text.splitlines():
        fields = line.split("#", 1)[0].split()
        if len(fields) < 2 or "localhost" not in fields[1:]:
            continue
        try:
            if ipaddress.ip_address(fields[0]).is_loopback:
                return True
        except ValueError:
            continue
    return False


def ensure_loopback_hosts(path: str = "/etc/hosts") -> str:
    """Make ``localhost`` resolve to loopback from ``path``; ``"present"`` or ``"added"``.

    Why (S-182 re-probe 2b): srt and the CLI's Bash sandbox set every proxy
    variable to ``http://…@localhost:<port>``, and inside the sandbox's network
    namespace there is no DNS. The image's own ``/etc/hosts`` is empty
    (BuildKit bind-mounts it during the build, so the Dockerfile can't fill
    it); Docker writes one at run time, AgentCore does not. Without the entry
    every registry fails with ``getaddrinfo EAI_AGAIN localhost``.

    Appends one line, in place (``/etc/hosts`` may be a bind mount, so no
    rename). Raises :class:`SandboxUnavailable` if the entry is missing and
    can't be added: running anyway would only produce confusing network errors.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    except OSError as exc:
        raise SandboxUnavailable(
            f"sandbox cannot resolve localhost: {path}: {exc.strerror}"
        ) from None
    if _maps_localhost_to_loopback(text):
        return "present"
    prefix = "\n" if text and not text.endswith("\n") else ""
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(prefix + LOOPBACK_HOSTS_LINE)
    except OSError as exc:
        raise SandboxUnavailable(
            f"sandbox cannot resolve localhost: {path} has no loopback entry "
            f"and is not writable ({exc.strerror})"
        ) from None
    return "added"


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


def as_fixer(paths: SandboxPaths) -> list[str]:
    """``setpriv <D-110 flags> --``: what follows runs as fixer, unprivileged."""
    return [paths.setpriv, *SETPRIV_FLAGS, "--"]


def fixer_prefix(paths: SandboxPaths) -> list[str]:
    """``setpriv <D-110 flags> -- python3 -I fixer_exec.py``."""
    return [*as_fixer(paths), paths.python, "-I", paths.fixer_exec]


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
        self.hosts_status = "unchecked"

    # ------------------------------------------------------------ host setup

    def ensure_hosts(self) -> str:
        """:func:`ensure_loopback_hosts` on ``paths.hosts``. ``hosts_status`` keeps
        ``"added"`` once the wrapper had to add the entry, so the probe can say so."""
        status = ensure_loopback_hosts(self.paths.hosts)
        if self.hosts_status != "added":
            self.hosts_status = status
        return status

    # ------------------------------------------------------------ availability

    def _required(self, mode: Mode) -> list[tuple[str, str, bool]]:
        """(role, path, must be executable) for ``mode``."""
        p = self.paths
        common = [
            ("setpriv", p.setpriv, True),
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

    def build_command(self, mode: Mode, argv: Sequence[str]) -> list[str]:
        if not argv:
            raise ValueError("empty command")
        prefix = fixer_prefix(self.paths)
        if mode is Mode.SCRIPT:
            return [*prefix, self.paths.srt, "--settings", self.paths.srt_settings, "--", *argv]
        if argv[0] != self.paths.claude:
            raise ValueError("CLI mode runs only the pinned claude binary")
        rest = list(argv[1:])
        if _CLI_PRINT_FLAGS.intersection(rest) and CLI_DISALLOWED_FLAG not in rest:
            rest.insert(0, CLI_DISALLOWED_FLAG)
        return [*prefix, argv[0], *rest]

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
        self.ensure_hosts()
        env = build_env(anthropic_api_key)
        cmd = self.build_command(mode, argv)

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
        """Kill every ``fixer`` process. Best effort; two passes.

        1. ``kill -9 -- -1`` run as ``fixer``: ``kill(-1)`` signals every
           process the caller may signal except itself, in one kernel pass, so
           it reaches every ``fixer`` process (daemons and srt's pid-namespaced
           children included), nothing else, and can't be outrun by a fork loop.
        2. ``pkill -KILL -u 10002`` as root: anything with effective uid fixer
           that pass 1 missed (for example, if ``setpriv`` itself failed).
        """
        commands = [
            [*as_fixer(self.paths), self.paths.kill, "-9", "--", "-1"],
            [self.paths.pkill, "-KILL", "-u", str(FIXER_UID)],
        ]
        for cmd in commands:
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
