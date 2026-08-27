"""
Toolchain detection — identifies package manager, version, and available scripts.

Detection precedence (D19):
    packageManager field -> pnpm-lock.yaml -> package-lock.json -> fail

The agent supports exactly two package managers: pnpm and npm.
"""

from __future__ import annotations

import json
import os

# Supported package managers, in detection precedence order for lockfiles.
_LOCKFILES: tuple[tuple[str, str], ...] = (
    ("pnpm", "pnpm-lock.yaml"),
    ("npm", "package-lock.json"),
)

_SUPPORTED = {"pnpm", "npm"}


class ToolchainError(Exception):
    """Raised when toolchain detection or validation fails with a known error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _read_package_json(workspace: str) -> dict:
    """Return the parsed package.json, or an empty dict if missing/malformed."""
    path = os.path.join(workspace, "package.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def detect_package_manager(workspace: str) -> str:
    """
    Detect the package manager for the repository at ``workspace``.

    Precedence:
      1. ``packageManager`` field in package.json (e.g. ``"pnpm@9.1.0"``),
         when it names a supported manager.
      2. Presence of ``pnpm-lock.yaml`` -> pnpm.
      3. Presence of ``package-lock.json`` -> npm.

    Raises ``ToolchainError('NO_PACKAGE_MANAGER', ...)`` if none match.
    """
    pkg = _read_package_json(workspace)

    field = pkg.get("packageManager")
    if isinstance(field, str) and field:
        name = field.split("@", 1)[0].strip().lower()
        if name in _SUPPORTED:
            return name

    for name, lockfile in _LOCKFILES:
        if os.path.isfile(os.path.join(workspace, lockfile)):
            return name

    searched = ", ".join(lockfile for _, lockfile in _LOCKFILES)
    raise ToolchainError(
        "NO_PACKAGE_MANAGER",
        f"No supported package manager detected in '{workspace}' "
        f"(searched packageManager field and lockfiles: {searched})",
    )
