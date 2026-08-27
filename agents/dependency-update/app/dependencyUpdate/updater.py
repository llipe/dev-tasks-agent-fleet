"""
Package updater — applies dependency updates and reconciles lockfiles.

Provides:
  - ``install_deps(workspace, pm, frozen)`` — install dependencies (frozen or mutable).
  - ``update_packages(workspace, pm)`` — run the update command.
  - ``has_changes(workspace)`` — check if the working tree has uncommitted changes.
  - ``reconcile_lockfile(workspace, pm)`` — re-install after updates to align lockfile.
"""

from __future__ import annotations

import subprocess

from config import TOOL_COMMAND_TIMEOUT


class UpdaterError(Exception):
    """Raised when an updater operation fails with a known error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _run(
    cmd: list[str], cwd: str, timeout: int = TOOL_COMMAND_TIMEOUT
) -> subprocess.CompletedProcess[str]:
    """Run a command, capturing output. Raises CalledProcessError on failure."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        timeout=timeout,
    )


def install_deps(workspace: str, pm: str, frozen: bool = True) -> str:
    """
    Install dependencies using the detected package manager.

    When ``frozen=True`` (default), uses the CI-safe frozen lockfile mode
    (``pnpm install --frozen-lockfile`` or ``npm ci``).
    When ``frozen=False``, uses a mutable install for reconciliation after updates.

    Returns combined stdout+stderr output.
    """
    if pm == "pnpm":
        cmd = ["pnpm", "install", "--frozen-lockfile"] if frozen else ["pnpm", "install"]
    else:
        cmd = ["npm", "ci"] if frozen else ["npm", "install"]

    try:
        result = _run(cmd, workspace)
        return (result.stdout or "") + (result.stderr or "")
    except subprocess.CalledProcessError as exc:
        output = (exc.stdout or "") + "\n" + (exc.stderr or "")
        raise UpdaterError("INSTALL_FAILED", f"{pm} install failed:\n{output.strip()}") from exc


def update_packages(workspace: str, pm: str) -> str:
    """
    Apply available dependency updates using the package manager's update command.

    Uses ``pnpm update --no-optional`` or ``npm update`` to bump versions within
    declared semver ranges.

    Returns combined stdout+stderr output.
    """
    cmd = ["pnpm", "update", "--no-optional"] if pm == "pnpm" else ["npm", "update"]

    try:
        result = _run(cmd, workspace)
        return (result.stdout or "") + (result.stderr or "")
    except subprocess.CalledProcessError as exc:
        output = (exc.stdout or "") + "\n" + (exc.stderr or "")
        raise UpdaterError("UPDATE_FAILED", f"{pm} update failed:\n{output.strip()}") from exc


def has_changes(workspace: str) -> bool:
    """
    Check whether the working tree has uncommitted changes (new, modified, or deleted files).

    Uses ``git status --porcelain`` — any output means changes exist.
    """
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return bool(result.stdout.strip())


def reconcile_lockfile(workspace: str, pm: str) -> str:
    """
    Re-install after updates so the lockfile is internally consistent.

    A frozen-lockfile CI install after ``pnpm update`` or ``npm update`` would
    fail if the lockfile's integrity checksums or resolution tree don't match.
    This step runs a mutable install to reconcile them (req 30).

    Returns combined stdout+stderr output.
    """
    return install_deps(workspace, pm, frozen=False)
