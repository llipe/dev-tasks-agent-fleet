"""
Toolchain detection — identifies package manager, version, and available scripts.

Detection precedence (D19):
    packageManager field -> pnpm-lock.yaml -> package-lock.json -> fail

The agent supports exactly two package managers: pnpm and npm.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field

from config import TOOL_COMMAND_TIMEOUT

# Supported package managers, in detection precedence order for lockfiles.
_LOCKFILES: tuple[tuple[str, str], ...] = (
    ("pnpm", "pnpm-lock.yaml"),
    ("npm", "package-lock.json"),
)

_SUPPORTED = {"pnpm", "npm"}

# pnpm-lock.yaml lockfileVersion major -> pnpm major.
_LOCKFILE_TO_PNPM_MAJOR: dict[int, int] = {
    9: 9,
    6: 8,
    5: 7,
}

# Matches `lockfileVersion: '9.0'`, `lockfileVersion: 9.0`, `lockfileVersion: 5.4`.
_LOCKFILE_VERSION_RE = re.compile(
    r"^lockfileVersion:\s*['\"]?(?P<major>\d+)(?:\.\d+)?['\"]?\s*$",
    re.MULTILINE,
)


class ToolchainError(Exception):
    """Raised when toolchain detection or validation fails with a known error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


# Optional checks and their accepted script-name variants, in preference order.
# The canonical name is listed first so it wins when several variants coexist.
_OPTIONAL_SCRIPT_VARIANTS: dict[str, tuple[str, ...]] = {
    "lint": ("lint",),
    "format": ("format", "format:check"),
    "typecheck": ("typecheck", "type-check"),
}

# Fix-variant scripts used by the validator's fix-and-retry step.
_FIX_SCRIPT_VARIANTS: dict[str, tuple[str, ...]] = {
    "lint_fix": ("lint:fix",),
    "format_fix": ("format:fix", "format:write"),
}


@dataclass
class ScriptContract:
    """
    The set of npm scripts the agent will invoke for a repository.

    Each field holds the *actual* script name to run (accounting for variants),
    or ``None`` when the logical script is absent. ``test`` is always present
    (``detect_scripts`` raises ``NO_TEST_SCRIPT`` otherwise).
    """

    test: str
    lint: str | None = None
    format: str | None = None
    typecheck: str | None = None
    lint_fix: str | None = None
    format_fix: str | None = None
    missing_optional: list[str] = field(default_factory=list)


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


def detect_pnpm_version(workspace: str) -> int | None:
    """
    Determine the required pnpm major version for the repository.

    Precedence:
      1. ``packageManager`` field (e.g. ``"pnpm@9.1.0"``) -> major from the version.
      2. ``lockfileVersion`` in pnpm-lock.yaml, mapped via ``_LOCKFILE_TO_PNPM_MAJOR``
         (9.x -> pnpm 9, 6.x -> pnpm 8, 5.x -> pnpm 7).

    Returns the pnpm major version, or ``None`` when it cannot be determined
    (caller may then use the container default).
    """
    pkg = _read_package_json(workspace)

    field = pkg.get("packageManager")
    if isinstance(field, str) and "@" in field:
        name, _, version = field.partition("@")
        if name.strip().lower() == "pnpm":
            major_str = version.strip().split(".", 1)[0]
            if major_str.isdigit():
                return int(major_str)

    lockfile_path = os.path.join(workspace, "pnpm-lock.yaml")
    try:
        with open(lockfile_path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None

    match = _LOCKFILE_VERSION_RE.search(content)
    if not match:
        return None

    lockfile_major = int(match.group("major"))
    return _LOCKFILE_TO_PNPM_MAJOR.get(lockfile_major)


def _run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run a command, capturing output. Raises CalledProcessError on failure."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        timeout=TOOL_COMMAND_TIMEOUT,
    )


def _current_pnpm_major() -> int | None:
    """Return the pnpm major version currently on PATH, or None if unavailable."""
    try:
        result = subprocess.run(
            ["pnpm", "--version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=TOOL_COMMAND_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    major_str = result.stdout.strip().split(".", 1)[0]
    return int(major_str) if major_str.isdigit() else None


def ensure_pnpm_version(workspace: str) -> None:
    """
    Ensure the pnpm major version on PATH matches what the repository requires.

    If the required major (from ``detect_pnpm_version``) differs from the
    container default, installs the correct major globally via
    ``npm install -g pnpm@<major>``. No-op when the required version cannot be
    determined or already matches the current one.
    """
    required = detect_pnpm_version(workspace)
    if required is None:
        return

    current = _current_pnpm_major()
    if current == required:
        return

    _run(["npm", "install", "-g", f"pnpm@{required}"], cwd=workspace)



def _resolve_variant(scripts: dict, variants: tuple[str, ...]) -> str | None:
    """Return the first variant present in ``scripts``, or None."""
    for name in variants:
        if name in scripts:
            return name
    return None


def detect_scripts(workspace: str) -> ScriptContract:
    """
    Inspect package.json scripts and build the :class:`ScriptContract`.

    ``test`` is mandatory (D20): a missing ``test`` script raises
    ``ToolchainError('NO_TEST_SCRIPT', ...)``. ``lint``, ``format`` and
    ``typecheck`` are optional — absent ones are recorded in
    ``missing_optional`` so the caller can emit warn events and mark them
    skipped in the PR body. Known variants are recognised
    (``format:check`` -> format, ``type-check`` -> typecheck).
    """
    pkg = _read_package_json(workspace)
    scripts = pkg.get("scripts")
    if not isinstance(scripts, dict):
        scripts = {}

    if "test" not in scripts:
        raise ToolchainError(
            "NO_TEST_SCRIPT",
            f"package.json in '{workspace}' has no 'test' script; "
            "the agent requires a test script to verify updates",
        )

    contract = ScriptContract(test="test")

    missing: list[str] = []
    for logical, variants in _OPTIONAL_SCRIPT_VARIANTS.items():
        resolved = _resolve_variant(scripts, variants)
        setattr(contract, logical, resolved)
        if resolved is None:
            missing.append(logical)
    contract.missing_optional = missing

    for attr, variants in _FIX_SCRIPT_VARIANTS.items():
        setattr(contract, attr, _resolve_variant(scripts, variants))

    return contract
