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
   from NSS without DNS (S-182 re-probe 2b: ``getaddrinfo EAI_AGAIN
   localhost``). AgentCore's ``/etc/hosts`` is empty **and read-only**
   (re-probe 2c), so the image resolves it with ``libnss-myhostname``
   (``hosts: files myhostname dns``) and prefers IPv4 through
   ``/etc/gai.conf``. Before every run the wrapper only *checks* that
   ``localhost`` has a route, ``/etc/hosts`` or NSS
   (:func:`check_localhost_resolution`), and refuses to start the run if
   neither is in place. It never writes ``/etc/hosts``.
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
# no DNS (S-182 re-probe 2b). AgentCore's /etc/hosts is empty and read-only
# (re-probe 2c), so the image resolves ``localhost`` with nss-myhostname; the
# wrapper only checks that the module is installed and listed before ``dns``.
NSS_MYHOSTNAME_LIB = "libnss_myhostname.so.2"
NSS_MYHOSTNAME = "myhostname"
# Where glibc's NSS modules live: Debian multiarch (the image is arm64), with
# and without merged /usr, then the usual non-Debian locations.
NSS_LIB_DIRS: tuple[str, ...] = (
    "/usr/lib/aarch64-linux-gnu",
    "/lib/aarch64-linux-gnu",
    "/usr/lib/x86_64-linux-gnu",
    "/lib/x86_64-linux-gnu",
    "/usr/lib64",
    "/lib64",
    "/usr/lib",
    "/lib",
)

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
    nsswitch: str = "/etc/nsswitch.conf"
    nss_lib_dirs: tuple[str, ...] = NSS_LIB_DIRS


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


def _read(path: str) -> tuple[str | None, str]:
    """``(text, "")``, or ``(None, reason)`` when ``path`` can't be read."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(), ""
    except FileNotFoundError:
        return None, f"{path} is missing"
    except OSError as exc:
        return None, f"{path}: {exc.strerror}"


def _nss_hosts_reason(text: str | None, path: str, missing: str) -> str:
    """Why the nsswitch ``hosts:`` line can't resolve ``localhost`` without
    DNS, or ``""`` when ``myhostname`` comes before ``dns`` (or there is no
    ``dns``) with no ``[...=return]`` action ahead of it."""
    if text is None:
        return missing
    for line in text.splitlines():
        fields = line.split("#", 1)[0].split()
        if not fields or fields[0] != "hosts:":
            continue
        services = fields[1:]
        line_text = " ".join(services)
        if NSS_MYHOSTNAME not in services:
            return f"{path} hosts line '{line_text}' does not list {NSS_MYHOSTNAME}"
        ahead = services[: services.index(NSS_MYHOSTNAME)]
        if "dns" in ahead:
            return f"{path} hosts line '{line_text}' lists {NSS_MYHOSTNAME} after dns"
        if any(f.startswith("[") and "=return" in f.lower() for f in ahead):
            return f"{path} hosts line '{line_text}' can return before {NSS_MYHOSTNAME}"
        return ""
    return f"{path} has no hosts line"


def check_localhost_resolution(
    hosts_path: str = "/etc/hosts",
    nsswitch_path: str = "/etc/nsswitch.conf",
    lib_dirs: Sequence[str] = NSS_LIB_DIRS,
) -> str:
    """How ``localhost`` resolves to loopback without DNS: ``"hosts"`` or ``"nss"``.

    Why (S-182 re-probes 2b, 2c): srt and the CLI's Bash sandbox set every
    proxy variable to ``http://…@localhost:<port>``, and inside the sandbox's
    network namespace there is no DNS. On AgentCore ``/etc/hosts`` is empty and
    read-only, so the image resolves ``localhost`` with nss-myhostname.

    - ``"hosts"``: ``hosts_path`` maps ``localhost`` to a loopback address;
    - ``"nss"``: the nsswitch ``hosts:`` line lists ``myhostname`` before
      ``dns`` (or has no ``dns``), and :data:`NSS_MYHOSTNAME_LIB` is in one of
      ``lib_dirs``.

    Read-only: it never writes either file. Raises :class:`SandboxUnavailable`
    when neither route is in place, since running anyway would only produce
    ``getaddrinfo EAI_AGAIN localhost`` errors from every registry.
    """
    hosts_text, hosts_reason = _read(hosts_path)
    if hosts_text is not None and _maps_localhost_to_loopback(hosts_text):
        return "hosts"
    hosts_why = (
        f"{hosts_reason}, so no loopback entry for localhost"
        if hosts_reason
        else f"{hosts_path} has no loopback entry for localhost"
    )

    nss_text, nss_missing = _read(nsswitch_path)
    nss_reason = _nss_hosts_reason(nss_text, nsswitch_path, nss_missing)
    if not nss_reason and not any(
        os.path.isfile(os.path.join(d, NSS_MYHOSTNAME_LIB)) for d in lib_dirs
    ):
        nss_reason = f"{NSS_MYHOSTNAME_LIB} not found in {', '.join(lib_dirs) or 'no lib dir'}"
    if not nss_reason:
        return "nss"
    raise SandboxUnavailable(f"sandbox cannot resolve localhost: {hosts_why}; {nss_reason}")


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
        self.localhost_via = "unchecked"

    # ------------------------------------------------------------ localhost

    def check_localhost(self) -> str:
        """:func:`check_localhost_resolution` on this sandbox's paths.
        ``localhost_via`` records the route (``hosts``/``nss``), or ``none``
        when the check refused the run, so the probe can say which."""
        p = self.paths
        try:
            via = check_localhost_resolution(p.hosts, p.nsswitch, p.nss_lib_dirs)
        except SandboxUnavailable:
            self.localhost_via = "none"
            raise
        self.localhost_via = via
        return via

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
        self.check_localhost()
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
