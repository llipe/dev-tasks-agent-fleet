"""
node — the Node.js versions the image ships, and which one a repo runs on.

A target repo pins Node through ``engines.node``, and pnpm enforces it on a
frozen install: a repo that wants ``>=24.21.0 <25`` fails on Node 26 with
``ERR_PNPM_UNSUPPORTED_ENGINE`` before any gate runs. The image ships one
Node per supported major, side by side under :data:`NODE_ROOT`
(``/opt/node/<major>``, root-owned); the Dockerfile's ``NODE_VERSIONS`` must
equal :data:`NODE_VERSIONS` (a unit test pins both).

**Selection** (:func:`select_node`), from the base commit through a
``RepoReader``, before anything of the repo runs:

1. ``engines.node`` in the root ``package.json``, when it is a string, keeps
   the shipped versions it accepts. When it accepts none, the repo is
   refused by name (``toolchain.NODE_ITEM``). When it doesn't parse, every
   shipped version stays a candidate: that is the old behaviour (one Node),
   and pnpm still reports what it thinks of the range.
2. ``.nvmrc``, then ``.node-version``: a major (``24``, ``v24.1.0``) that
   names a candidate picks that major. Aliases (``lts/*``, ``node``) and
   anything else are ignored. A version file never widens ``engines.node``.
3. Otherwise :data:`DEFAULT_NODE` when it is a candidate, else the highest.

The wrapper then puts the choice's ``bin`` first on ``fixer``'s PATH
(``sandbox.node_path``), for install and every gate. ``pnpm``, ``claude``
and ``srt`` are ``#!/usr/bin/env node`` scripts, so they run on the same
Node; all three accept every shipped major (``>=22.12``).

**Ranges** (:func:`satisfies`) follow node-semver's grammar: ``||`` unions,
space-separated comparators (``<``, ``<=``, ``>``, ``>=``, ``=``), bare and
``v``-prefixed versions, X-ranges and partials (``24``, ``24.x``, ``*``),
``~`` and ``^``, and hyphen ranges (``22 - 24``). A prerelease bound sorts
below its release. Anything else raises :class:`RangeError`.

Standard library only, and no project import: ``sandbox.py`` imports this.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

NODE_ROOT = "/opt/node"
# One per major, ascending. Must equal the Dockerfile's ``ARG NODE_VERSIONS``.
NODE_VERSIONS: tuple[str, ...] = ("22.23.4", "24.22.2", "26.12.1")
# The Node of a repo that doesn't pin one; the image's /usr/bin/node.
DEFAULT_NODE = "26.12.1"
VERSION_FILES: tuple[str, ...] = (".nvmrc", ".node-version")
PACKAGE_JSON = "package.json"

# A version's sort key: (major, minor, patch, 1 for a release / 0 for a prerelease).
Key = tuple[int, int, int, int]


class RangeError(ValueError):
    """An ``engines.node`` value outside the node-semver range grammar."""


class RepoReader(Protocol):
    def read_text(self, path: str) -> str | None: ...


@dataclass(frozen=True)
class NodeChoice:
    version: str  # one of NODE_VERSIONS
    source: str  # "engines.node", ".nvmrc", ".node-version" or "default ..."

    @property
    def major(self) -> int:
        return _major(self.version)


def _major(version: str) -> int:
    return int(version.split(".", 1)[0])


def bin_dir(version: str) -> str:
    """``/opt/node/<major>/bin`` for a shipped version; ``ValueError`` otherwise."""
    if version not in NODE_VERSIONS:
        raise ValueError("not a shipped Node version")
    return f"{NODE_ROOT}/{_major(version)}/bin"


# ---------------------------------------------------------------------------
# Ranges
# ---------------------------------------------------------------------------

_X = r"\*|x|X|\d+"
_PARTIAL = re.compile(
    rf"v?(?P<M>{_X})(?:\.(?P<m>{_X})(?:\.(?P<p>{_X})(?:-(?P<pre>[0-9A-Za-z.-]+))?)?)?"
    r"(?:\+[0-9A-Za-z.-]+)?"
)
_COMPARATOR = re.compile(r"(?P<op><=|>=|<|>|=|~>|~|\^)?(?P<v>.+)")
_OP_SPACE = re.compile(r"(<=|>=|<|>|=|~>|~|\^)\s+")
_HYPHEN = re.compile(r"(\S+)\s+-\s+(\S+)")

Comparator = tuple[str, Key]


def _num(part: str | None) -> int | None:
    return None if part is None or part in ("*", "x", "X") else int(part)


def _parse_partial(text: str) -> tuple[int | None, int | None, int | None, int]:
    m = _PARTIAL.fullmatch(text)
    if m is None:
        raise RangeError("not a version")
    major, minor, patch = _num(m["M"]), _num(m["m"]), _num(m["p"])
    # Once a part is a wildcard, the parts after it are too (24.x.3 is 24.x).
    if major is None:
        minor = patch = None
    elif minor is None:
        patch = None
    return major, minor, patch, 0 if m["pre"] else 1


def _upper(major: int, minor: int | None) -> Key:
    """The exclusive upper bound of a partial: ``24`` -> 25.0.0-0, ``24.1`` -> 24.2.0-0."""
    return (major + 1, 0, 0, 0) if minor is None else (major, minor + 1, 0, 0)


def _comparators(op: str, text: str) -> list[Comparator]:
    major, minor, patch, rel = _parse_partial(text)
    if major is None:
        return [] if op in ("", "=", ">=", "<=", "~", "~>", "^") else [("<", (0, 0, 0, 0))]
    full = minor is not None and patch is not None
    low: Key = (major, minor or 0, patch or 0, rel if full else 0)
    if op in ("", "="):
        return [("=", low)] if full else [(">=", low), ("<", _upper(major, minor))]
    if op == ">=":
        return [(">=", low)]
    if op == ">":
        return [(">", low)] if full else [(">=", _upper(major, minor))]
    if op == "<":
        return [("<", low)]
    if op == "<=":
        return [("<=", low)] if full else [("<", _upper(major, minor))]
    if op in ("~", "~>"):
        return [(">=", low), ("<", _upper(major, minor))]
    # ^: the leftmost non-zero part may not change.
    if major > 0 or minor is None:
        hi: Key = (major + 1, 0, 0, 0)
    elif minor > 0 or patch is None:
        hi = (0, minor + 1, 0, 0)
    else:
        hi = (0, 0, patch + 1, 0)
    return [(">=", low), ("<", hi)]


def _parse_set(text: str) -> list[Comparator]:
    text = _OP_SPACE.sub(r"\1", text.strip())
    if not text:
        return []
    hyphen = _HYPHEN.fullmatch(text)
    if hyphen:
        low = _comparators(">=", hyphen[1])
        major, minor, patch, _rel = _parse_partial(hyphen[2])
        if major is None:
            return low
        if minor is not None and patch is not None:
            return [*low, *_comparators("<=", hyphen[2])]
        return [*low, ("<", _upper(major, minor))]
    out: list[Comparator] = []
    for token in text.split():
        m = _COMPARATOR.fullmatch(token)
        if m is None:
            raise RangeError("not a comparator")
        out.extend(_comparators(m["op"] or "", m["v"]))
    return out


def _holds(key: Key, op: str, bound: Key) -> bool:
    return {
        "=": key == bound,
        ">=": key >= bound,
        ">": key > bound,
        "<": key < bound,
        "<=": key <= bound,
    }[op]


def satisfies(version: str, spec: str) -> bool:
    """Whether the release ``version`` (``X.Y.Z``) is in the range ``spec``.
    Raises :class:`RangeError` when ``spec`` doesn't parse."""
    major, minor, patch = (int(p) for p in version.split("."))
    key: Key = (major, minor, patch, 1)
    sets = [_parse_set(part) for part in spec.split("||")]
    return any(all(_holds(key, op, bound) for op, bound in s) for s in sets)


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

_FILE_MAJOR = re.compile(r"v?(\d+)(?:\.\d+){0,2}")


def _engines_node(reader: RepoReader) -> str | None:
    text = reader.read_text(PACKAGE_JSON)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    engines = data.get("engines") if isinstance(data, dict) else None
    value = engines.get("node") if isinstance(engines, dict) else None
    return value if isinstance(value, str) else None


def _file_major(reader: RepoReader, name: str) -> int | None:
    text = reader.read_text(name)
    m = _FILE_MAJOR.fullmatch(text.strip()) if text is not None else None
    return int(m[1]) if m else None


def select_node(reader: RepoReader) -> NodeChoice | None:
    """The shipped Node a JS repo runs on, or ``None`` when its
    ``engines.node`` accepts none of :data:`NODE_VERSIONS`."""
    spec = _engines_node(reader)
    candidates = list(NODE_VERSIONS)
    source = "default"
    if spec is not None:
        try:
            candidates = [v for v in NODE_VERSIONS if satisfies(v, spec)]
            source = "engines.node"
        except RangeError:
            source = "default (engines.node not parsed)"
        if not candidates:
            return None
    for name in VERSION_FILES:
        major = _file_major(reader, name)
        matching = [v for v in candidates if _major(v) == major]
        if matching:
            return NodeChoice(matching[-1], name)
    if DEFAULT_NODE in candidates:
        return NodeChoice(DEFAULT_NODE, source)
    return NodeChoice(candidates[-1], source)
