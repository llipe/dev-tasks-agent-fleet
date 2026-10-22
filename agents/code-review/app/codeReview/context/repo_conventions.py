"""
Repository conventions (S-208; spec §8.3 step 5, §8.4 f; PRD FR-11).

Read at ``head_sha``:

1. the first present file of ``CONVENTION_FILES``: ``AGENTS.md``, else
   ``CLAUDE.md``. Presence decides: an empty ``AGENTS.md`` is used;
2. the ``docs/adr`` directory listing. Entries of type ``file`` whose name
   matches ``ADR_NAME_RE`` (``[A-Za-z0-9._-]+\\.md``) are sorted by name and
   the first ``MAX_ADRS`` (50) read, each as ``docs/adr/<name>`` built from
   the validated name, never from the listed ``path``. Later ones are counted
   (``adrs_ignored``);
3. from each ADR, the title (the first ``# `` line) and the ``Status`` line
   (``adr_summary``), each cut to ``MAX_ADR_FIELD_CHARS``. Only the first
   ``MAX_ADR_BYTES`` (64 KiB) of an ADR is parsed, cut at a line ending.

The bundle (``render_conventions``) lists the ADRs first and the conventions
file after, so the whole-bundle cap of 10% of ``max_context_tokens`` cuts the
file's tail before the ADR index. Over the cap it is truncated at a line
boundary with a ``[truncated]`` marker.

A 404 means "no such file" (and a missing or file-typed ``docs/adr`` lists
nothing). A 403 skips that read with a ``warn`` and sets ``unavailable``; for
``AGENTS.md`` the lookup moves on to ``CLAUDE.md``. 401, rate limits and 5xx
propagate unchanged. The text is untrusted repository content, kept verbatim
for the prompt builder (S-209) to fence; ``warn`` events carry only the path
and a fixed reason.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from context.conventions import (
    ADR_DIR,
    ADR_NAME_RE,
    ADR_STATUS_HEADING_RE,
    ADR_STATUS_LINE_RE,
    CONVENTION_FILES,
    CONVENTIONS_SHARE_DENOMINATOR,
    CONVENTIONS_SHARE_NUMERATOR,
    LINE_END_RE,
    MAX_ADR_BYTES,
    MAX_ADR_FIELD_CHARS,
    MAX_ADRS,
)
from context.issues import Warn
from context.tokens import estimate, truncate
from github_client import DirEntry, GitHubClient, GitHubPermissionDenied

__all__ = [
    "AdrSummary",
    "ConventionsContext",
    "adr_summary",
    "conventions_cap",
    "render_conventions",
    "repo_conventions",
]

ADR_HEADER = f"ADRs in {ADR_DIR} (title and Status line):\n"
NO_TITLE = "(no title)"
BOM = "\ufeff"

_ATX_RE = re.compile(r"[ \t]{0,3}#{1,6}(?:[ \t]|$)")


@dataclass(frozen=True)
class AdrSummary:
    path: str
    title: str | None
    status: str | None  # the Status line as written, or ``Status: <next line>``


@dataclass(frozen=True)
class ConventionsContext:
    source: str | None  # ``AGENTS.md``, ``CLAUDE.md``, or ``None``
    adrs: tuple[AdrSummary, ...]
    adrs_ignored: int  # ``*.md`` ADRs past ``MAX_ADRS``
    text: str  # the bundle, capped; "" when there is nothing (no block)
    truncated: bool
    tokens: int  # estimate of the bundle before the cap
    unavailable: bool = False  # at least one read was refused with a 403


def conventions_cap(max_context_tokens: int) -> int:
    """10% of ``max_context_tokens``, rounded down (spec §8.3, §8.4 f)."""
    return max_context_tokens * CONVENTIONS_SHARE_NUMERATOR // CONVENTIONS_SHARE_DENOMINATOR


def _cut(value: str) -> str:
    return value[:MAX_ADR_FIELD_CHARS]


def adr_summary(path: str, text: str) -> AdrSummary:
    """The first ``# `` title and the first ``Status`` line of an ADR.

    The Status is a line such as ``Status: Accepted`` or ``**Status:** Accepted``
    (kept as written, stripped), or a ``## Status`` heading followed by its first
    non-blank line when that is not a heading (``Status: <line>``).
    Case-sensitive. Lines split on ``\\r\\n``, ``\\r`` or ``\\n``. One leading
    UTF-8 BOM (U+FEFF) is dropped first, as GitHub renders the file (QA D3).
    """
    text = text.removeprefix(BOM)
    title: str | None = None
    status: str | None = None
    # One linear pass (QA D1). ``pending``: a ``Status`` heading was seen and
    # its first non-blank line has not been reached yet.
    pending = False
    for line in LINE_END_RE.split(text):
        if title is None and line[:2] in ("# ", "#\t") and line[2:].strip():
            title = _cut(line[2:].strip())
        if status is None:
            if pending and line.strip():
                pending = False
                if not _ATX_RE.match(line):
                    status = _cut("Status: " + line.strip())
            if status is None and not pending:
                if ADR_STATUS_LINE_RE.match(line):
                    status = _cut(line.strip())
                elif ADR_STATUS_HEADING_RE.fullmatch(line):
                    pending = True
        if title is not None and status is not None:
            break
    return AdrSummary(path, title, status)


def render_conventions(source: str | None, content: str | None, adrs: Sequence[AdrSummary]) -> str:
    """The conventions block text: the ADR index, then the conventions file."""
    parts: list[str] = []
    if adrs:
        lines = [ADR_HEADER]
        for adr in adrs:
            entry = f"- `{adr.path}`: {adr.title if adr.title is not None else NO_TITLE}"
            if adr.status is not None:
                entry += f" — {adr.status}"
            lines.append(entry + "\n")
        parts.append("".join(lines))
    if source is not None:
        body = content or ""
        if body and not body.endswith("\n"):
            body += "\n"
        parts.append(f"{source} at head:\n{body}")
    return "\n".join(parts)


def _read(
    client: GitHubClient, path: str, head_sha: str, warn: Warn | None
) -> tuple[str | None, bool]:
    """``(content or None, refused)``; a 403 is ``(None, True)`` with a warning."""
    try:
        return client.get_content_raw(path, head_sha), False
    except GitHubPermissionDenied as exc:
        if exc.status != 403:
            raise
        _warn_unavailable(warn, path)
        return None, True


def _read_adr(
    client: GitHubClient, path: str, head_sha: str, warn: Warn | None
) -> tuple[str | None, bool]:
    """Like ``_read``, but only the first ``MAX_ADR_BYTES``, cut at a line ending.

    The cut is made on the bytes, at the last ``\\n`` or ``\\r`` inside the cap,
    so no multi-byte character is split; a line straddling the cap is dropped.
    """
    try:
        raw = client.get_content_bytes(path, head_sha)
    except GitHubPermissionDenied as exc:
        if exc.status != 403:
            raise
        _warn_unavailable(warn, path)
        return None, True
    if raw is None:
        return None, False
    if len(raw) > MAX_ADR_BYTES:
        head = raw[:MAX_ADR_BYTES]
        raw = head[: max(head.rfind(b"\n"), head.rfind(b"\r")) + 1]
    return raw.decode("utf-8", errors="replace"), False


def _warn_unavailable(warn: Warn | None, path: str) -> None:
    if warn is not None:
        warn("conventions file unavailable", path=path, reason="permission")


def _adr_names(entries: Sequence[DirEntry]) -> list[str]:
    names = {e.name for e in entries if e.type == "file" and ADR_NAME_RE.fullmatch(e.name)}
    return sorted(names)


def repo_conventions(
    client: GitHubClient,
    head_sha: str,
    *,
    max_context_tokens: int,
    warn: Warn | None = None,
) -> ConventionsContext:
    """Read the conventions file and ADR summaries at ``head_sha`` and cap them."""
    unavailable = False
    source: str | None = None
    content: str | None = None
    for name in CONVENTION_FILES:
        content, refused = _read(client, name, head_sha, warn)
        unavailable = unavailable or refused
        if content is not None:
            source = name
            break

    entries: list[DirEntry] = []
    try:
        entries = client.list_dir(ADR_DIR, head_sha)
    except GitHubPermissionDenied as exc:
        if exc.status != 403:
            raise
        unavailable = True
        _warn_unavailable(warn, ADR_DIR)
    names = _adr_names(entries)
    adrs: list[AdrSummary] = []
    for name in names[:MAX_ADRS]:
        path = f"{ADR_DIR}/{name}"
        text, refused = _read_adr(client, path, head_sha, warn)
        unavailable = unavailable or refused
        if text is not None:
            adrs.append(adr_summary(path, text))

    bundle = render_conventions(source, content, adrs)
    capped, truncated = truncate(bundle, conventions_cap(max_context_tokens))
    return ConventionsContext(
        source=source,
        adrs=tuple(adrs),
        adrs_ignored=max(0, len(names) - MAX_ADRS),
        text=capped,
        truncated=truncated,
        tokens=estimate(bundle),
        unavailable=unavailable,
    )
