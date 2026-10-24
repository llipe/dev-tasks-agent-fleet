# Copied from agents/dependency-update/app/dependencyUpdate/toolchain.py
# Source commit: ff5283598accdc24f8e9477dc9ebfddfeeaa2aef
# Adapted (S-189): kept the package-manager detection (packageManager field ->
# pnpm-lock.yaml -> package-lock.json) and ToolchainError; dropped
# ensure_pnpm_version (it ran `npm install -g` in the wrapper) and the
# optional-script contract. Added the Python stack (Makefile targets), static
# Makefile parsing, the `.claude/agents/developer.md` check and the repo gate,
# all read through a RepoReader rather than the filesystem (D-06, D-18, D-19,
# D-112). S-189 fix round: a packageManager field needs its own lockfile;
# yarn and bun are refused by name (QA-189-04); the makefile is the one GNU
# make reads (DF-189-08).
"""
Toolchain detection and the repo gate (spec §8.7 ``checkout``; FR-6;
D-06, D-17, D-18, D-19, D-63, D-112).

**Stacks.** A root ``package.json`` means JS/TS, even when a ``Makefile``
exists too (pinned, TC-189-05). Otherwise a root ``Makefile`` means Python.
Otherwise the repo has no supported stack.

**JS/TS** (D-17). The package manager is the ``packageManager`` field, which
must name pnpm or npm and have that manager's lockfile (``pnpm-lock.yaml`` or
``package-lock.json``; else the ``lockfile`` miss). Without the field it is
``pnpm-lock.yaml``, then ``package-lock.json``. yarn and bun (a
``packageManager: yarn@…`` or ``bun@…``, or only a ``yarn.lock``, ``bun.lockb``
or ``bun.lock``) are the :data:`UNSUPPORTED_PM_ITEM` miss (QA-189-04). Gates
are root ``package.json`` scripts, run as ``<pm> run <name>``. Install is
frozen: ``pnpm install --frozen-lockfile`` or ``npm ci`` (D-63). A monorepo is
handled at its root: the root scripts and the root lockfile.

**Python** (D-18, D-19, D-112). The makefile is the first of
:data:`MAKEFILE_NAMES` that exists, GNU make's own order (DF-189-08): make
reads that one and ignores the rest, so the gate does too. Gates are its targets, run as
``make <name>``. Install is ``make install``; a repo without an ``install``
target is refused ("missing install target").

**The repo gate** (FR-6, D-06, D-19). Required: ``.claude/agents/developer.md``
as a regular file, plus the four blocking gates, ``test``, ``lint``,
``format:check`` (scripts) or ``format-check`` (targets), and ``typecheck``.
A near miss is a miss: ``format_check`` is not ``format-check``, and a
``format-check`` script is not ``format:check``. ``audit`` is recorded when
present and never required (D-14). Every miss is named; the refusal reply
names the first (D-92), from a closed set (:data:`MISS_ITEMS`).

**Reading.** Every check reads through a :class:`RepoReader`. At run time that
is ``safe_git.TreeReader`` on the wrapper clone's base commit: trusted data,
regular blobs only, never a file in the ``fixer``-writable work tree. The
``Makefile`` is parsed statically: evaluating it (``make -pn``) would run
repo code in the wrapper, so ``include`` is not followed (pinned, TC-189-09).
"""

from __future__ import annotations

import enum
import json
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

DEVELOPER_MD = ".claude/agents/developer.md"
PACKAGE_JSON = "package.json"
MAKEFILE = "Makefile"
# GNU make's default makefile order: it reads the first that exists.
MAKEFILE_NAMES: tuple[str, ...] = ("GNUmakefile", "makefile", MAKEFILE)
MAX_FILE_BYTES = 1024 * 1024

# Supported package managers, in detection precedence order for lockfiles.
_LOCKFILES: tuple[tuple[str, str], ...] = (
    ("pnpm", "pnpm-lock.yaml"),
    ("npm", "package-lock.json"),
)

_SUPPORTED = {"pnpm", "npm"}
# Lockfiles of managers bug-fix doesn't run (QA-189-04).
_UNSUPPORTED_LOCKFILES: tuple[str, ...] = ("yarn.lock", "bun.lockb", "bun.lock")

# The four blocking gates, by logical name, in run order (D-14).
GATE_ORDER: tuple[str, ...] = ("test", "lint", "format", "typecheck")
AUDIT = "audit"
JS_GATE_NAMES: Mapping[str, str] = {
    "test": "test",
    "lint": "lint",
    "format": "format:check",
    "typecheck": "typecheck",
}
PY_GATE_NAMES: Mapping[str, str] = {
    "test": "test",
    "lint": "lint",
    "format": "format-check",
    "typecheck": "typecheck",
}
PY_INSTALL_TARGET = "install"

# Frozen install per manager (D-63); Python per D-112.
INSTALL_ARGV: Mapping[str, tuple[str, ...]] = {
    "pnpm": ("pnpm", "install", "--frozen-lockfile"),
    "npm": ("npm", "ci"),
    "make": ("make", PY_INSTALL_TARGET),
}

MANIFEST_ITEM = "package.json or Makefile"
LOCKFILE_ITEM = "lockfile"
UNSUPPORTED_PM_ITEM = "supported package manager (pnpm or npm)"
# Every item a miss can name. refusal.REPO_GATE_ITEMS must contain all of them.
MISS_ITEMS: tuple[str, ...] = (
    DEVELOPER_MD,
    MANIFEST_ITEM,
    LOCKFILE_ITEM,
    UNSUPPORTED_PM_ITEM,
    *dict.fromkeys([*JS_GATE_NAMES.values(), *PY_GATE_NAMES.values()]),
    PY_INSTALL_TARGET,
)


class ToolchainError(Exception):
    """Raised when toolchain detection or validation fails with a known error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class Stack(enum.StrEnum):
    JS = "js"
    PYTHON = "python"


class RepoReader(Protocol):
    def read_text(self, path: str) -> str | None:
        """The text of the regular file at repo-relative ``path``, or ``None``."""
        ...


def _exists(reader: RepoReader, path: str) -> bool:
    """``path`` has an entry of any kind (a symlink or an oversized file
    included). Readers without ``exists`` fall back to ``read_text``."""
    exists = getattr(reader, "exists", None)
    if exists is not None:
        return bool(exists(path))
    return reader.read_text(path) is not None


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------


def _safe_rel(path: str) -> list[str] | None:
    """``path`` split into components, or ``None`` when it could leave the root."""
    if not path or path.startswith("/") or "\0" in path:
        return None
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None
    return parts


class DirReader:
    """Reads regular files under ``root``, never through a symlink.

    Every component of the path is ``lstat``-ed; a symlink anywhere, a
    non-regular file, a path that leaves ``root``, or a file above
    :data:`MAX_FILE_BYTES` reads as ``None``.
    """

    def __init__(self, root: str) -> None:
        self.root = root

    def exists(self, path: str) -> bool:
        parts = _safe_rel(path)
        return parts is not None and os.path.lexists(os.path.join(self.root, *parts))

    def read_text(self, path: str) -> str | None:
        parts = _safe_rel(path)
        if parts is None:
            return None
        current = self.root
        for i, part in enumerate(parts):
            current = os.path.join(current, part)
            try:
                st = os.lstat(current)
            except OSError:
                return None
            last = i == len(parts) - 1
            if stat.S_ISLNK(st.st_mode):
                return None
            if not last and not stat.S_ISDIR(st.st_mode):
                return None
            if last and (not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE_BYTES):
                return None
        try:
            fd = os.open(current, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError:
            return None
        with os.fdopen(fd, "rb") as f:
            data = f.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            return None
        return data.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# JS/TS
# ---------------------------------------------------------------------------


def _read_package_json(reader: RepoReader) -> dict:
    """Return the parsed package.json, or an empty dict if missing/malformed."""
    text = reader.read_text(PACKAGE_JSON)
    if text is None:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def detect_package_manager(reader: RepoReader) -> str:
    """
    Detect the package manager for the repository.

    Precedence:
      1. ``packageManager`` field in package.json (e.g. ``"pnpm@9.1.0"``).
         It must name pnpm or npm (else ``UNSUPPORTED_PACKAGE_MANAGER``), and
         that manager's lockfile must exist (else ``NO_LOCKFILE``): corepack
         runs the named manager whatever lockfile is there (QA-189-04).
      2. Presence of ``pnpm-lock.yaml`` -> pnpm.
      3. Presence of ``package-lock.json`` -> npm.
      4. Only ``yarn.lock``, ``bun.lockb`` or ``bun.lock`` ->
         ``UNSUPPORTED_PACKAGE_MANAGER``.

    Lockfiles are checked for presence, not read, so a lockfile over the
    reader's size cap still counts. Raises
    ``ToolchainError('NO_PACKAGE_MANAGER', ...)`` if nothing matches.
    """
    pkg = _read_package_json(reader)

    field = pkg.get("packageManager")
    if isinstance(field, str) and field.strip():
        name = field.split("@", 1)[0].strip().lower()
        if name not in _SUPPORTED:
            raise ToolchainError(
                "UNSUPPORTED_PACKAGE_MANAGER", "packageManager names neither pnpm nor npm"
            )
        lockfile = dict(_LOCKFILES)[name]
        if not _exists(reader, lockfile):
            raise ToolchainError(
                "NO_LOCKFILE", f"packageManager is {name} but {lockfile} is absent"
            )
        return name

    for name, lockfile in _LOCKFILES:
        if _exists(reader, lockfile):
            return name

    if any(_exists(reader, lockfile) for lockfile in _UNSUPPORTED_LOCKFILES):
        raise ToolchainError(
            "UNSUPPORTED_PACKAGE_MANAGER", "only a yarn or bun lockfile is present"
        )

    searched = ", ".join(lockfile for _, lockfile in _LOCKFILES)
    raise ToolchainError(
        "NO_PACKAGE_MANAGER",
        "No supported package manager detected "
        f"(searched packageManager field and lockfiles: {searched})",
    )


def package_scripts(reader: RepoReader) -> dict[str, str]:
    """The root ``package.json`` scripts with a non-empty string command."""
    scripts = _read_package_json(reader).get("scripts")
    if not isinstance(scripts, dict):
        return {}
    return {k: v for k, v in scripts.items() if isinstance(k, str) and isinstance(v, str) and v}


# ---------------------------------------------------------------------------
# Python: Makefile targets
# ---------------------------------------------------------------------------

_DIRECTIVES = frozenset(
    {
        "include",
        "-include",
        "sinclude",
        "ifeq",
        "ifneq",
        "ifdef",
        "ifndef",
        "else",
        "endif",
        "export",
        "unexport",
        "override",
        "vpath",
        "undefine",
        "private",
    }
)


def _logical_lines(text: str) -> list[str]:
    """Physical lines joined across backslash-newline continuations."""
    lines: list[str] = []
    current = ""
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.endswith("\\") and not line.endswith("\\\\"):
            current += line[:-1] + " "
            continue
        lines.append(current + line)
        current = ""
    if current:
        lines.append(current)
    return lines


def parse_make_targets(text: str) -> frozenset[str]:
    """The explicit targets a ``Makefile`` defines, by static parsing only.

    - A rule line starts in column 0 (recipe lines start with a tab) and has a
      ``:`` (or ``::``) before any ``=``; each name before the colon is a target.
    - Variable assignments (``=``, ``:=``, ``::=``, ``:::=``, ``?=``, ``+=``,
      ``!=``) are not rules. ``test: VAR := x`` is a rule for ``test``.
    - Comments, ``define`` blocks and directives are skipped; ``include`` is
      **not** followed.
    - Names with ``$`` or ``%`` (variables, patterns) and special targets
      (``.PHONY`` and every other name starting with ``.``) don't count, nor do
      prerequisites.
    """
    targets: set[str] = set()
    in_define = False
    for line in _logical_lines(text):
        stripped = line.strip()
        if in_define:
            if stripped.split(None, 1)[:1] == ["endef"]:
                in_define = False
            continue
        if not stripped or line.startswith("\t") or stripped.startswith("#"):
            continue
        words = stripped.split(None, 1)
        if words[0] == "define" or (
            words[0] in ("override", "export") and "define" in stripped.split()[:2]
        ):
            in_define = True
            continue
        if words[0] in _DIRECTIVES and ":" not in words[0]:
            continue
        line_no_comment = stripped.split("#", 1)[0]
        colon = line_no_comment.find(":")
        equals = line_no_comment.find("=")
        if colon < 0 or (0 <= equals < colon):
            continue
        rest = line_no_comment[colon:]
        if rest.lstrip(":").startswith("=") and len(rest) - len(rest.lstrip(":")) <= 3:
            continue  # :=, ::=, :::=
        for name in line_no_comment[:colon].split():
            if "$" in name or "%" in name or name.startswith("."):
                continue
            targets.add(name)
    return frozenset(targets)


# ---------------------------------------------------------------------------
# The repo gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateMiss:
    """One missing repo-gate item: ``item`` (from :data:`MISS_ITEMS`) and its
    ``kind``: ``file``, ``manifest``, ``lockfile``, ``manager``, ``script`` or
    ``target``."""

    item: str
    kind: str

    def describe(self) -> str:
        if self.kind == "target" and self.item == PY_INSTALL_TARGET:
            return "missing install target"  # D-112's wording
        if self.kind in ("script", "target"):
            return f"missing {self.kind} {self.item}"
        if self.kind == "lockfile":
            return "missing lockfile (pnpm-lock.yaml or package-lock.json)"
        return f"missing {self.item}"


@dataclass(frozen=True)
class Toolchain:
    stack: Stack
    manager: str  # "pnpm", "npm" or "make"
    gates: Mapping[str, str]  # logical -> script or target name
    audit: str | None

    @property
    def install_argv(self) -> list[str]:
        return list(INSTALL_ARGV[self.manager])

    def gate_argv(self, logical: str) -> list[str]:
        """``<pm> run <script>`` or ``make <target>`` for a logical gate or
        ``audit``. Raises ``KeyError`` for an unknown or absent gate."""
        if logical == AUDIT:
            if self.audit is None:
                raise KeyError(AUDIT)
            name = self.audit
        else:
            name = self.gates[logical]
        if self.stack is Stack.JS:
            return [self.manager, "run", name]
        return ["make", name]

    def command(self, logical: str) -> str:
        return " ".join(self.gate_argv(logical))


@dataclass(frozen=True)
class RepoGate:
    toolchain: Toolchain | None
    missing: tuple[GateMiss, ...]

    @property
    def ok(self) -> bool:
        return not self.missing

    @property
    def first(self) -> GateMiss | None:
        return self.missing[0] if self.missing else None

    @property
    def summary(self) -> str:
        if self.ok:
            assert self.toolchain is not None
            return f"repo gate passed ({self.toolchain.stack}, {self.toolchain.manager})"
        return "repo gate: " + "; ".join(m.describe() for m in self.missing)


def makefile_name(reader: RepoReader) -> str | None:
    """The makefile GNU make would read: the first of :data:`MAKEFILE_NAMES`
    with an entry of any kind (DF-189-08). A symlinked or oversized one is
    still the one make uses, so the gate never falls through to the next."""
    for name in MAKEFILE_NAMES:
        if _exists(reader, name):
            return name
    return None


def detect_stack(reader: RepoReader) -> Stack | None:
    """JS when a root ``package.json`` exists (it wins over a makefile),
    Python when only a root makefile exists (any of :data:`MAKEFILE_NAMES`),
    else ``None``."""
    if reader.read_text(PACKAGE_JSON) is not None:
        return Stack.JS
    if makefile_name(reader) is not None:
        return Stack.PYTHON
    return None


def check_repo_gate(reader: RepoReader) -> RepoGate:
    """FR-6: ``developer.md`` plus the four gates (and Python's ``install``).

    Misses come in a fixed order: ``developer.md``, the manifest, the
    lockfile, the gates (test, lint, format, typecheck), then ``install``.
    """
    missing: list[GateMiss] = []
    if reader.read_text(DEVELOPER_MD) is None:
        missing.append(GateMiss(DEVELOPER_MD, "file"))

    stack = detect_stack(reader)
    if stack is None:
        missing.append(GateMiss(MANIFEST_ITEM, "manifest"))
        return RepoGate(None, tuple(missing))

    toolchain: Toolchain | None
    if stack is Stack.JS:
        scripts = package_scripts(reader)
        try:
            manager: str | None = detect_package_manager(reader)
        except ToolchainError as exc:
            manager = None
            if exc.code == "UNSUPPORTED_PACKAGE_MANAGER":
                missing.append(GateMiss(UNSUPPORTED_PM_ITEM, "manager"))
            else:
                missing.append(GateMiss(LOCKFILE_ITEM, "lockfile"))
        for logical in GATE_ORDER:
            if JS_GATE_NAMES[logical] not in scripts:
                missing.append(GateMiss(JS_GATE_NAMES[logical], "script"))
        audit = AUDIT if AUDIT in scripts else None
        toolchain = (
            Toolchain(Stack.JS, manager, dict(JS_GATE_NAMES), audit)
            if manager is not None
            else None
        )
    else:
        # A makefile the reader can't read (a symlink, too big) has no
        # targets here: every gate is named missing, never a different file.
        name = makefile_name(reader)
        targets = parse_make_targets((reader.read_text(name) if name else None) or "")
        for logical in GATE_ORDER:
            if PY_GATE_NAMES[logical] not in targets:
                missing.append(GateMiss(PY_GATE_NAMES[logical], "target"))
        if PY_INSTALL_TARGET not in targets:
            missing.append(GateMiss(PY_INSTALL_TARGET, "target"))
        audit = AUDIT if AUDIT in targets else None
        toolchain = Toolchain(Stack.PYTHON, "make", dict(PY_GATE_NAMES), audit)

    return RepoGate(toolchain, tuple(missing))
