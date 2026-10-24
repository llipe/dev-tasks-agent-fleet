"""
Hidden comment markers: build, parse and trust-check (spec §8.3; D-53, D-80, D-104).

Every comment the agent posts begins with a block of marker lines::

    <!-- agent-fleet:bug-fix:claim run_id=<uuid> -->
    <!-- agent-fleet:bug-fix:disposition run_id=<uuid> -->
    <!-- agent-fleet:bug-fix:pr run_id=<uuid> -->
    <!-- agent-fleet:bug-fix:refusal run_id=<uuid> reason=<code> -->

Parsing rules:

- Only the **leading block** counts: consecutive marker lines from line 1. The
  first line that isn't a marker (a blank line included) ends the block, so a
  marker quoted further down a comment is never read (D-80).
- A marker line matches the grammar exactly: no leading or trailing text, a
  lowercase canonical UUID, a known kind, and for ``refusal`` exactly one known
  ``reason``. A line ending in ``\\r`` (a CRLF body) is accepted.
- A marker is **trusted** only when the comment's ``performed_via_github_app.id``
  is the fleet App id (an ``int``) and ``user.type == "Bot"``. The login is never
  consulted, because an App can be renamed (D-53).

Claim lifecycle: a trusted ``claim`` is **open** until a trusted ``pr`` or
``disposition`` marker exists for the same ``run_id``. A ``refusal`` never opens
or closes a claim (D-104). Ordering always uses the integer comment id.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

PREFIX = "agent-fleet:bug-fix"
KINDS: tuple[str, ...] = ("claim", "disposition", "refusal", "pr")
REFUSAL_REASONS: tuple[str, ...] = (
    "pull_request",
    "closed",
    "linked_pr",
    "active_run",
    "repo_gate",
    "invalid_params",
)
# Kinds that close an open claim for the same run_id.
CLOSING_KINDS: frozenset[str] = frozenset({"pr", "disposition"})

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_LINE = re.compile(
    r"<!-- agent-fleet:bug-fix:(?:"
    rf"(?P<kind>claim|disposition|pr) run_id=(?P<run_id>{_UUID})"
    rf"|refusal run_id=(?P<refusal_run_id>{_UUID}) reason=(?P<reason>{'|'.join(REFUSAL_REASONS)})"
    r") -->"
)


@dataclass(frozen=True)
class Marker:
    kind: str
    run_id: str
    reason: str | None = None


def canonical_run_id(run_id: str) -> str:
    """Return the lowercase canonical form of a UUID. Raises ``ValueError``."""
    if not isinstance(run_id, str):
        raise ValueError("run_id must be a UUID string")
    try:
        return str(uuid.UUID(run_id))
    except ValueError:
        raise ValueError("run_id must be a UUID") from None


def build(kind: str, run_id: str, reason: str | None = None) -> str:
    """Return one marker line (no newline). Raises ``ValueError`` on bad input."""
    if kind not in KINDS:
        raise ValueError(f"unknown marker kind {kind!r}")
    rid = canonical_run_id(run_id)
    if kind == "refusal":
        if reason not in REFUSAL_REASONS:
            raise ValueError("a refusal marker needs a known reason")
        return f"<!-- {PREFIX}:refusal run_id={rid} reason={reason} -->"
    if reason is not None:
        raise ValueError(f"a {kind} marker takes no reason")
    return f"<!-- {PREFIX}:{kind} run_id={rid} -->"


def build_block(markers: Iterable[Marker]) -> str:
    """Return a leading marker block, one line per marker (D-80)."""
    lines = [build(m.kind, m.run_id, m.reason) for m in markers]
    if not lines:
        raise ValueError("a marker block needs at least one marker")
    return "\n".join(lines)


def _parse_line(line: str) -> Marker | None:
    m = _LINE.fullmatch(line)
    if m is None:
        return None
    if m.group("kind"):
        return Marker(m.group("kind"), m.group("run_id"))
    return Marker("refusal", m.group("refusal_run_id"), m.group("reason"))


def parse_block(body: Any) -> tuple[Marker, ...]:
    """Return the markers in the leading block of ``body`` (empty if none)."""
    if not isinstance(body, str):
        return ()
    found: list[Marker] = []
    for raw in body.split("\n"):
        marker = _parse_line(raw.removesuffix("\r"))
        if marker is None:
            break
        found.append(marker)
    return tuple(found)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def comment_id(comment: Any) -> int | None:
    """The comment's positive integer id, or ``None`` if it has none."""
    if not isinstance(comment, Mapping):
        return None
    cid = comment.get("id")
    if isinstance(cid, int) and not isinstance(cid, bool) and cid > 0:
        return cid
    return None


def is_trusted(comment: Any, app_id: int) -> bool:
    """True iff the comment was posted by the fleet App's bot (D-53)."""
    if not _is_int(app_id):
        raise TypeError("app_id must be an int")
    if not isinstance(comment, Mapping):
        return False
    app = comment.get("performed_via_github_app")
    user = comment.get("user")
    if not isinstance(app, Mapping) or not isinstance(user, Mapping):
        return False
    app_value = app.get("id")
    return _is_int(app_value) and app_value == app_id and user.get("type") == "Bot"


def trusted_markers(comments: Iterable[Any], app_id: int) -> list[tuple[int, Marker]]:
    """``(comment id, marker)`` for every marker in a trusted comment, by id."""
    out: list[tuple[int, Marker]] = []
    for comment in comments:
        cid = comment_id(comment)
        if cid is None or not is_trusted(comment, app_id):
            continue
        out.extend((cid, marker) for marker in parse_block(comment.get("body")))
    out.sort(key=lambda pair: (pair[0], KINDS.index(pair[1].kind), pair[1].run_id))
    return out


def open_claims(comments: Iterable[Any], app_id: int) -> list[tuple[int, str]]:
    """``(comment id, run_id)`` of each trusted claim not closed by ``pr``/``disposition``."""
    found = trusted_markers(comments, app_id)
    closed = {m.run_id for _, m in found if m.kind in CLOSING_KINDS}
    return [(cid, m.run_id) for cid, m in found if m.kind == "claim" and m.run_id not in closed]


def has_trusted(comments: Iterable[Any], app_id: int, kind: str, run_id: str) -> bool:
    """True iff a trusted ``kind`` marker exists for ``run_id``."""
    rid = canonical_run_id(run_id)
    return any(m.kind == kind and m.run_id == rid for _, m in trusted_markers(comments, app_id))
