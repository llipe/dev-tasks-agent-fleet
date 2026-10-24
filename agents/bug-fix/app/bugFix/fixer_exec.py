"""
fixer_exec — rebuild the environment from the allow-list, then exec (S-182, D-51, D-109).

``sandbox.py`` starts every ``fixer`` process as::

    sudo -n -u fixer --preserve-env=<names> -- python3 -I fixer_exec.py <cmd> [args...]

``sudo`` (``env_reset``) already starts from a clean environment, but it adds
its own variables (``SUDO_USER``, ``SUDO_COMMAND``, ``USER``, ``MAIL``...).
This shim runs as ``fixer`` and execs ``<cmd>`` with exactly the allow-listed
names, so the command sees ``ANTHROPIC_API_KEY`` (when the wrapper passed it),
``PATH``, ``HOME=/home/fixer``, ``LANG`` and ``CI=1``, and nothing else.

Values never travel in argv (``/proc/<pid>/cmdline`` is world-readable): the
key arrives in this process's environment through ``--preserve-env`` and
leaves it through ``execvpe``'s environment. Standard library only; run with
``python3 -I`` so no ``PYTHON*`` variable or user site can change it.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence

# Must equal sandbox.ALLOWED_ENV / sandbox.FIXER_PATH; a unit test pins both.
ALLOWED: tuple[str, ...] = ("ANTHROPIC_API_KEY", "PATH", "HOME", "LANG", "CI")
FIXER_PATH = "/usr/local/bin:/usr/bin:/bin"
FIXER_HOME = "/home/fixer"
# Copied from the incoming env when present; PATH and HOME are always fixed.
_PASSED_THROUGH: tuple[str, ...] = ("ANTHROPIC_API_KEY", "LANG", "CI")


def build_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The exact environment for the command: the allow-list, nothing else."""
    env = {name: environ[name] for name in _PASSED_THROUGH if environ.get(name)}
    env["PATH"] = FIXER_PATH
    env["HOME"] = FIXER_HOME
    env.setdefault("LANG", "C.UTF-8")
    env["CI"] = "1"
    return env


def main(argv: Sequence[str]) -> None:
    if len(argv) < 2:
        sys.stderr.write("usage: fixer_exec.py <command> [args...]\n")
        raise SystemExit(2)
    cmd = list(argv[1:])
    os.execvpe(cmd[0], cmd, build_env(os.environ))


if __name__ == "__main__":  # pragma: no cover - exercised by the image smoke test
    main(sys.argv)
