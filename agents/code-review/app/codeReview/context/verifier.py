"""
Verifier drift candidates (S-208; spec §8.3 step 4, §8.4 b/d, §8.7; D-25, D-33, D-38).

Lookup (``report_paths``), per linked issue in issue order: for each story ID
in the title (``title_story_ids``: ``Story S-<id>`` first, then any
``[A-Z]{1,4}-\\d+`` such as riel's ``GC-08``; D-64) the story report
``workstream/fidelity-report-<ID>.md``, then
``workstream/fidelity-report-issue-<N>.md``. Each exact name is followed by
the suffixed names (``<name>-<slug>.md``) the head tree lists, when the caller
passes ``tree_paths``, so a suffix costs no blind read. Documents the
selection call picked as ``verifier_report`` (``extra_paths``, PRD FR-32) are
read last. Rollups are never requested. Paths are deduped across issues, so
two issues sharing a story ID read that report once (attributed to the first
issue; a selected report with no rule-based match is attributed to issue 0).
Every read is at ``head_sha``. A 404 means "no such report" (state ``none``, no warning: most PRs
have none). A 403 is skipped with a ``warn`` and sets ``unavailable``, like an
issue 403 in S-207; 401, rate limits and 5xx propagate unchanged.

Parsing (``parse_drift``), on lines split at ``\\r\\n``, ``\\r`` or ``\\n``:

- The drift section starts at the first line, outside a code fence, that
  matches ``DRIFT_HEADING_RE`` (``^#{2,3}[ \\t]+(Drift|Drift catalog)\\b`` with an
  optional numeric section prefix such as ``4.`` or ``3.2``, D-44) and runs
  to the next ATX heading of the same or a higher level (fewer or equal
  ``#``), also outside a fence, or to the end. None → ``not_parseable``; an
  empty report is ``not_parseable`` too.
- Inside it, a table is a header line with an unescaped ``|`` followed by a
  delimiter row with the same number of cells (each ``:?-+:?``). Data rows
  follow until a blank line, a line with no unescaped ``|``, a heading, a fence,
  or the section end. Lines inside fenced code blocks are never table lines
  (a fenced table is code). Indented code blocks are not recognized.
- Every data row (never the header or delimiter) that contains the whole,
  case-sensitive words ``Critical`` and ``Unintended`` (``DRIFT_CRITICAL_RE``,
  ``DRIFT_UNINTENDED_RE``, ``re.ASCII`` word boundaries, matched over the row
  line) is a candidate; the rest count as "other drift". Rows are numbered
  from 1 across all tables in the section (``row_index``, "drift row N").

Candidates are taken from the whole section; the section passed as context is
then capped at ``DRIFT_SECTION_TOKEN_CAP`` (4,000) with a ``[truncated]``
marker, so a qualifying row past the cap is never lost. Candidate IDs
``V1…Vk`` are global, in report order then row order. Each candidate's text is
the source line verbatim (line ending dropped), cut to ``CANDIDATE_TOKEN_CAP``
(300) estimated tokens.

Report text is untrusted repository content: the PR author controls it on
their branch. Nothing here interprets it beyond the regexes; ``Candidate.label``
carries only the ID, path, and row index for use outside the nonce markers,
and the row text is for the per-candidate nonce block S-209 builds (D-38).
Every regex is linear in the line length. ``warn`` events carry only the path
and a fixed reason, never report text.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass

from context.conventions import (
    CANDIDATE_TOKEN_CAP,
    DRIFT_CRITICAL_RE,
    DRIFT_HEADING_RE,
    DRIFT_SECTION_TOKEN_CAP,
    DRIFT_UNINTENDED_RE,
    LINE_END_RE,
    MAX_REPORT_SUFFIXES,
    MAX_TITLE_IDS,
    REPORT_DIR,
    REPORT_SLUG_RE,
    STORY_ID_RE,
    STORY_TITLE_RE,
    issue_report_path,
    story_report_path,
)
from context.issues import LinkedIssue, Warn
from context.markdown import FenceTracker
from context.tokens import estimate, truncate
from github_client import GitHubClient, GitHubPermissionDenied

__all__ = [
    "REPORT_NONE",
    "REPORT_NOT_PARSEABLE",
    "REPORT_PARSED",
    "Candidate",
    "DriftRow",
    "DriftSection",
    "ReportRead",
    "VerifierContext",
    "VerifierReport",
    "build_verifier_context",
    "is_candidate_row",
    "parse_drift",
    "report_paths",
    "split_cells",
    "title_story_ids",
    "verifier_candidates",
]

REPORT_NONE = "none"
REPORT_NOT_PARSEABLE = "not_parseable"
REPORT_PARSED = "parsed"

# (report path, linked issue number, content or ``None`` for no such report)
ReportRead = tuple[str, int, str | None]

_ATX_RE = re.compile(r" {0,3}(#{1,6})(?:[ \t]|$)")
# One delimiter-row cell, stripped: ``---``, ``:---``, ``---:``, ``:-:``.
_DELIMITER_CELL_RE = re.compile(r":?-+:?")


@dataclass(frozen=True)
class Candidate:
    """A drift row the wrapper escalates for the model to confirm (D-33)."""

    id: str  # ``V<k>``, global across reports
    report_path: str
    row_index: int  # 1-based data row in the drift section ("drift row N")
    line: int  # 1-based line number in the report
    text: str  # the source line verbatim, cut to 300 estimated tokens
    truncated: bool

    def label(self) -> str:
        """The text that may sit outside the nonce markers: ID, path, row (D-38)."""
        return f"{self.id} — `{self.report_path}`, drift row {self.row_index}"


@dataclass(frozen=True)
class DriftRow:
    index: int  # 1-based across the section's tables
    line: int  # 1-based line number in the report
    text: str  # the source line, without its line ending
    candidate: bool


@dataclass(frozen=True)
class DriftSection:
    heading: str  # the heading line, without its line ending
    text: str  # the whole section, verbatim, heading included
    rows: tuple[DriftRow, ...]


@dataclass(frozen=True)
class VerifierReport:
    path: str
    issue: int  # the first linked issue that looked it up
    state: str  # REPORT_NONE | REPORT_NOT_PARSEABLE | REPORT_PARSED
    section: str  # the drift section capped at 4,000 tokens; "" unless parsed
    section_truncated: bool
    section_tokens: int  # estimate of the whole section, before the cap
    candidates: tuple[Candidate, ...]
    other_drift: int  # data rows in the section that are not candidates


@dataclass(frozen=True)
class VerifierContext:
    reports: tuple[VerifierReport, ...]  # one per distinct path looked up, in order
    candidates: tuple[Candidate, ...]  # V1…Vk across every report
    unavailable: bool = False  # at least one report read was refused with a 403

    @property
    def state(self) -> str:
        """``parsed`` if any report parsed, else ``not_parseable`` if any, else ``none``."""
        states = {r.state for r in self.reports}
        for state in (REPORT_PARSED, REPORT_NOT_PARSEABLE):
            if state in states:
                return state
        return REPORT_NONE

    @property
    def other_drift(self) -> int:
        return sum(r.other_drift for r in self.reports)


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def title_story_ids(title: str) -> tuple[str, ...]:
    """Story IDs in ``title``: ``Story S-<id>`` first, then ``STORY_ID_RE``; deduped, capped."""
    ids = [m.group(1) for m in STORY_TITLE_RE.finditer(title)]
    ids += [m.group(1) for m in STORY_ID_RE.finditer(title)]
    return tuple(dict.fromkeys(ids))[:MAX_TITLE_IDS]


def _suffixed(exact: str, tree_paths: Collection[str]) -> list[str]:
    """``<exact stem>-<slug>.md`` names directly under ``workstream/`` that ``tree_paths`` lists."""
    stem = exact[: -len(".md")] + "-"
    found = []
    for path in tree_paths:
        if not (path.startswith(stem) and path.endswith(".md")):
            continue
        slug = path[len(stem) : -len(".md")]
        if slug != "rollup" and REPORT_SLUG_RE.fullmatch(slug):
            found.append(path)
    return sorted(found)[:MAX_REPORT_SUFFIXES]


def report_paths(issue: LinkedIssue, tree_paths: Collection[str] | None = None) -> tuple[str, ...]:
    """The story reports, then the issue report; each followed by its listed suffixed names."""
    exact = [story_report_path(i) for i in title_story_ids(issue.title)]
    exact.append(issue_report_path(issue.number))
    paths: list[str] = []
    for name in exact:
        paths.append(name)
        if tree_paths:
            paths.extend(_suffixed(name, tree_paths))
    return tuple(dict.fromkeys(paths))


def _report_names(tree_paths: Iterable[str]) -> frozenset[str]:
    """The tree's report-shaped names directly under ``workstream/``: one pass over the tree."""
    prefix = f"{REPORT_DIR}/fidelity-report-"
    return frozenset(
        p for p in tree_paths if p.startswith(prefix) and "/" not in p[len(REPORT_DIR) + 1 :]
    )


def verifier_candidates(
    client: GitHubClient,
    issues: Iterable[LinkedIssue],
    head_sha: str,
    *,
    warn: Warn | None = None,
    tree_paths: Iterable[str] | None = None,
    extra_paths: Sequence[str] = (),
) -> VerifierContext:
    """Read each linked issue's reports, then the selected ones, at ``head_sha`` once; parse."""
    names = _report_names(tree_paths) if tree_paths is not None else None
    wanted: list[tuple[str, int]] = []
    for issue in issues:
        wanted.extend((path, issue.number) for path in report_paths(issue, names))
    wanted.extend((path, 0) for path in extra_paths)
    reads: list[ReportRead] = []
    seen: set[str] = set()
    unavailable = False
    for path, number in wanted:
        if path in seen:
            continue
        seen.add(path)
        content: str | None
        try:
            content = client.get_content_raw(path, head_sha)
        except GitHubPermissionDenied as exc:
            if exc.status != 403:
                raise
            content = None
            unavailable = True
            if warn is not None:
                warn("verifier report unavailable", path=path, reason="permission")
        reads.append((path, number, content))
    return build_verifier_context(reads, unavailable=unavailable, warn=warn)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _lines(text: str) -> list[tuple[int, int, str]]:
    """``(start, end, line)``: ``end`` is past the line ending; endings dropped."""
    out: list[tuple[int, int, str]] = []
    start = 0
    for m in LINE_END_RE.finditer(text):
        out.append((start, m.end(), text[start : m.start()]))
        start = m.end()
    if start < len(text):
        out.append((start, len(text), text[start:]))
    return out


def split_cells(line: str) -> list[str] | None:
    """The stripped cells of a table line, or ``None`` with no unescaped ``|``.

    A backslash escapes the next character, so ``\\|`` stays inside its cell
    (kept as written). One leading and one trailing pipe are outer pipes.
    """
    cells: list[str] = []
    start = 0
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if c == "\\":
            i += 2
            continue
        if c == "|":
            cells.append(line[start:i])
            start = i + 1
        i += 1
    if not cells:
        return None
    cells.append(line[start:])
    stripped = [c.strip() for c in cells]
    if not stripped[0] and line.lstrip().startswith("|"):
        stripped.pop(0)
    if len(stripped) > 1 and not stripped[-1] and not cells[-1].strip():
        stripped.pop()
    return stripped


def _is_delimiter(cells: list[str], width: int) -> bool:
    return len(cells) == width and all(_DELIMITER_CELL_RE.fullmatch(c) for c in cells)


def is_candidate_row(line: str) -> bool:
    """Both whole, case-sensitive words ``Critical`` and ``Unintended`` (D-33)."""
    return bool(DRIFT_CRITICAL_RE.search(line)) and bool(DRIFT_UNINTENDED_RE.search(line))


def _heading_level(line: str) -> int:
    m = _ATX_RE.match(line)
    return len(m.group(1)) if m is not None else 0


def parse_drift(text: str) -> DriftSection | None:
    """The drift section and its table rows, or ``None`` (not parseable)."""
    lines = _lines(text)
    fence = FenceTracker()
    start = None
    level = 0
    for k, (_, _, line) in enumerate(lines):
        if fence.step(line):
            continue
        if DRIFT_HEADING_RE.match(line):
            start = k
            level = _heading_level(line)
            break
    if start is None:
        return None
    end = len(lines)
    rows: list[DriftRow] = []
    fence = FenceTracker()
    width = 0  # cells in the current table's header; 0 when not in a table
    k = start + 1
    while k < len(lines):
        line = lines[k][2]
        if fence.step(line):
            width = 0
            k += 1
            continue
        heading = _heading_level(line)
        if heading:
            width = 0
            if heading <= level:
                end = k
                break
            k += 1
            continue
        cells = split_cells(line)
        if width:
            if cells is None or not line.strip():
                width = 0
            else:
                rows.append(DriftRow(len(rows) + 1, k + 1, line, is_candidate_row(line)))
                k += 1
                continue
        if cells is not None and k + 1 < len(lines):
            nxt = lines[k + 1][2]
            delimiter = split_cells(nxt)
            if delimiter is not None and _is_delimiter(delimiter, len(cells)):
                width = len(cells)
                k += 2
                continue
        k += 1
    first = lines[start]
    last = lines[end - 1]
    return DriftSection(first[2], text[first[0] : last[1]], tuple(rows))


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_verifier_context(
    reads: Sequence[ReportRead],
    *,
    unavailable: bool = False,
    warn: Warn | None = None,
) -> VerifierContext:
    """Parse each read report and number the candidates ``V1…Vk`` globally."""
    reports: list[VerifierReport] = []
    candidates: list[Candidate] = []
    for path, issue, content in reads:
        if content is None:
            reports.append(VerifierReport(path, issue, REPORT_NONE, "", False, 0, (), 0))
            continue
        section = parse_drift(content)
        if section is None:
            if warn is not None:
                warn("verifier report not parseable", path=path)
            reports.append(VerifierReport(path, issue, REPORT_NOT_PARSEABLE, "", False, 0, (), 0))
            continue
        mine: list[Candidate] = []
        for row in section.rows:
            if row.candidate:
                text, cut = truncate(row.text, CANDIDATE_TOKEN_CAP)
                mine.append(
                    Candidate(
                        f"V{len(candidates) + len(mine) + 1}", path, row.index, row.line, text, cut
                    )
                )
        capped, truncated = truncate(section.text, DRIFT_SECTION_TOKEN_CAP)
        reports.append(
            VerifierReport(
                path,
                issue,
                REPORT_PARSED,
                capped,
                truncated,
                estimate(section.text),
                tuple(mine),
                len(section.rows) - len(mine),
            )
        )
        candidates.extend(mine)
    return VerifierContext(tuple(reports), tuple(candidates), unavailable)
