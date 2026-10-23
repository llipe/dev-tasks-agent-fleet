"""
Review, budget and failure comments (S-212; spec §8.8, §13; D-28, D-29, D-36, D-38).

Three renderers, all pure (no I/O, no clock, no randomness) and linear in
their input:

- ``render_review`` — the review comment, in spec §8.8 order: hidden marker,
  verdict header with the short head SHA, Blocking, Verifier, collapsed
  Suggestions, the context line, and the footer (out-of-scope list, model,
  rubric version, run link). Section order follows the spec template
  (Verifier before Suggestions; test plan DF-01 is pinned to it). Empty
  sections are omitted. Returns ``Rendered`` (body, applied size stages).
- ``render_budget`` — the PRD FR-6 budget comment, with the line counts
  (``OverBudget.reason == "lines"``; "at least" when the file listing was
  cut at GitHub's cap) or the token counts (``"tokens"``, test plan DF-08).
- ``render_failure`` — the FR-26 one-line failure comment: fixed text per
  spec §13 code, never an exception message.

Each ends with the run link ``PANEL_BASE_URL/runs/<run_id>`` (D-29). The link
is built only from a validated base URL (``http(s)``, host, optional port,
plain path segments, at most 200 characters, trailing slashes dropped) and a
UUID ``run_id``; otherwise it reads "(run link unavailable)", so neither value
can inject Markdown.

**Neutralization** (spec §8.8, §12). Every piece of model or repository text
(titles, scenarios, consequences, reasons, candidate rows, paths, report and
spec paths, file names, the model ID and rubric version) goes through one of
two functions, after any length cut, so a cut can never split an escape:

- ``neutralize`` for plain text: C0/C1 controls and line separators become a
  space and bidi controls are removed (so content stays on its line and in
  its slot); ``&``, ``<`` and ``>`` become entities; ``@`` is followed by
  U+200B (no ping, no email autolink); ``#`` and a ``GH-`` before a digit are followed by U+200B
  (no heading, no issue cross-reference); the Markdown punctuation
  ``\\ ` * _ [ ] ! | ~ $`` is backslash-escaped (no emphasis, code, links,
  images, tables, strikethrough or math); ``://`` and ``www.`` get a U+200B so
  GitHub's extended autolinks cannot form. Surrounding whitespace is stripped.
- ``code_span`` for text shown inside inline code (paths, the model ID):
  ``context.diff.escape_path`` first (controls, backslash and line separators
  as escapes, as in the diff the model saw), every backtick removed, bidi
  controls removed, then ``&``, ``<`` and ``>`` as entities and ``@`` with
  U+200B. Backslash escapes do not work inside code spans, so nothing else is
  escaped; entities are shown literally there (a path holding ``<`` reads
  ``&lt;``), which is accepted for the rare path that holds one. An empty
  result renders "(unknown)" instead of an empty code span, which would not
  close. With no backtick and no ``<`` the span always closes and nothing in
  it is parsed.

So no content can open ``<!--``, close the marker with ``-->`` or a
``</details>``, start a heading or a list, or form a table, link, image or
autolink: the marker is the only ``<!--`` in the body, and the only raw
``<`` are the wrapper's own ``<details>``, ``<summary>`` and ``<sub>`` tags.
Verifier rows come from the wrapper's ``Candidate.text``, never from model
output (D-38); the model's reason is shown only when
``CandidateStatus.reason_from_model``, otherwise "not checked by the model".

**Size guarantee** (D-28, D-36). The body is measured after neutralization.
While it is over ``MAX_COMMENT_CHARS`` (60,000; GitHub's limit is 65,536) the
next stage applies, in order, each one recorded in ``Rendered.stages`` only
when it changed something:

1. drop suggestions from the end (the summary then reads "k of n");
2. cut each blocking ``failure_scenario`` to 500 and each ``consequence`` to
   200 characters;
3. cut each verifier row and reason to 300 characters;
4. render blocking findings in rank order with full detail while they fit,
   and the rest as one-line entries after "N more blocking findings are
   listed by title only:";
5. hard cut the middle of the body at the last line boundary that fits;
   blocking findings are cut as whole one-line entries, the lead-in states
   how many are listed and "and N more blocking findings not shown." counts
   the rest, so every blocking finding is rendered or counted.

Cuts count characters of the raw text, the ellipsis included. Any applied
stage adds ``TRUNCATION_NOTE`` before the footer. The marker, the verdict
header, the note and the footer are never cut (all bounded: the model ID is
cut to 200 and the rubric version to 20 characters). The verdict never
changes. Every stage is one pass over prefix sums, so the whole render stays
linear.

**Bounded parts.** A finding's path is cut to 400 characters (the schema
maximum), context-line paths to 200. Each context-line list shows at most
``LIST_MAX`` (20) names, and past the first name of each list the names
on one line share ``CONTEXT_MAX_CHARS`` (8,000) characters; the rest read
"and N more". Line numbers above 999,999,999 render as ``999999999+``; they are only
compared, so ``str()`` is never called on a huge int (over 4,300 digits it
raises).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TypeVar

from budget import (
    BLOCK_CONVENTIONS,
    BLOCK_DIFF,
    BLOCK_ISSUE,
    BLOCK_PR,
    BLOCK_SPEC,
    BLOCK_VERIFIER,
    REASON_BUDGET,
    REASON_EMPTY,
    STATE_OMITTED,
    STATE_TRIMMED,
    BlockNote,
    ContextData,
)
from context.diff import (
    OVER_TOKENS,
    DiffContext,
    FileDiff,
    NameOnlyFile,
    OverBudget,
    escape_path,
)
from context.verifier import REPORT_NOT_PARSEABLE, REPORT_PARSED, VerifierContext, VerifierReport
from validate import (
    DOWNGRADE_NO_SCENARIO,
    DOWNGRADE_OUTSIDE_DIFF,
    NOT_CHECKED_REASON,
    STATUS_CONFIRMED,
    STATUS_DROPPED_FOR_BUDGET,
    STATUS_NOT_CHECKED,
    STATUS_NOT_REPRODUCED,
    VERDICT_BLOCKING,
    VERDICT_CLEAR,
    CandidateStatus,
    Finding,
    Validation,
)

__all__ = [
    "CONSEQUENCE_CUT",
    "CONTEXT_MAX_CHARS",
    "ERROR_CODES",
    "LINE_MAX",
    "LIST_MAX",
    "MARKER_PREFIX",
    "MAX_COMMENT_CHARS",
    "MIN_LIMIT",
    "OUT_OF_SCOPE",
    "SCENARIO_CUT",
    "TRUNCATION_NOTE",
    "VERIFIER_CUT",
    "Rendered",
    "canonical_code",
    "code_span",
    "format_line",
    "neutralize",
    "render_budget",
    "render_failure",
    "render_review",
    "run_link",
]

MAX_COMMENT_CHARS = 60_000  # D-28: under GitHub's 65,536 with margin
MIN_LIMIT = 10_000  # the smallest ``limit``: the never-cut parts always fit
SCENARIO_CUT = 500  # stage 2
CONSEQUENCE_CUT = 200  # stage 2
VERIFIER_CUT = 300  # stage 3, rows and reasons
PATH_MAX = 400  # a finding's path (the schema's ``file`` maxLength)
# Fixed caps on every other rendered field (QA residual 4), so no single field
# can push the Context line past the stage-5 cut. The schema maxima for model
# fields, S-208's candidate cap for rows (300 estimated tokens), 200 or less
# for everything else.
TITLE_MAX = 200
SCENARIO_MAX = 1_500
CONSEQUENCE_MAX = 500
ROW_MAX = 1_050
REASON_MAX = 300
LABEL_MAX = 60  # IDs, categories, statuses, name-only reasons, withheld rules, issue refs
CONTEXT_PATH_MAX = 200  # a path in the context line, the Verifier section, the budget comment
MODEL_MAX = 200
VERSION_MAX = 20
LIST_MAX = 20  # names per context-line list
CONTEXT_MAX_CHARS = 8_000  # names per context line, all lists together
LINE_MAX = 999_999_999  # larger line numbers and counts render as ``999999999+``
PANEL_URL_MAX = 200

MARKER_PREFIX = "<!-- code-review-agent:v1 "
TRUNCATION_NOTE = "Truncated; the full review is in the run's audit report."
NO_LINK = "(run link unavailable)"
NOT_CHECKED = NOT_CHECKED_REASON  # "not checked by the model" (spec §8.7)

# PRD FR-21, item for item with rubric.md's "Out of scope" list.
OUT_OF_SCOPE = (
    "fidelity and AC coverage (`verifier`)",
    "lint, format, typecheck, tests, dependency audit, coverage (CI)",
    "SAST and secrets (CI, `security-analyst`)",
)

# Spec §13, in table order. Anything else renders as ``INTERNAL_ERROR``.
ERROR_CODES = (
    "INVALID_PARAMS",
    "GITHUB_PERMISSION_DENIED",
    "GITHUB_API_ERROR",
    "BEDROCK_ACCESS_DENIED",
    "BEDROCK_ERROR",
    "MODEL_OUTPUT_INVALID",
    "RUN_TIMEOUT",
    "COMMENT_POST_FAILED",
    "INTERNAL_ERROR",
)
FALLBACK_CODE = "INTERNAL_ERROR"
_CANONICAL_CODES = {code: code for code in ERROR_CODES}

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_PANEL_RE = re.compile(
    r"https?://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::[0-9]{1,5})?(?:/[A-Za-z0-9._~-]+)*"
)
_ISSUE_REF_RE = re.compile(r"#[0-9]{1,9}")

_ZW = chr(0x200B)  # ZERO WIDTH SPACE
_ELLIPSIS = "\u2026"
# ALM, LRM, RLM, LRE..RLO, LRI..PDI: removed, so text cannot reorder its display.
_BIDI = (0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A))
_SPACED: dict[int, str | None] = dict.fromkeys(range(0x20), " ")
_SPACED |= dict.fromkeys(range(0x7F, 0xA0), " ")
_SPACED |= {0x2028: " ", 0x2029: " "}
_DROPPED: dict[int, str | None] = dict.fromkeys(_BIDI)
_MARKUP = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "@": "@" + _ZW,
    "#": "#" + _ZW,
    "\\": "\\\\",
    "`": "\\`",
    "*": "\\*",
    "_": "\\_",
    "[": "\\[",
    "]": "\\]",
    "!": "\\!",
    "|": "\\|",
    "~": "\\~",
    "$": "\\$",
}
_PLAIN: dict[int, str | None] = {**_SPACED, **_DROPPED}
_PLAIN |= {ord(k): v for k, v in _MARKUP.items()}
_CODE: dict[int, str | None] = dict(_DROPPED)
_CODE |= {
    ord("`"): None,
    ord("&"): "&amp;",
    ord("<"): "&lt;",
    ord(">"): "&gt;",
    ord("@"): "@" + _ZW,
}
_SCHEME_RE = re.compile(r"://")
_WWW_RE = re.compile(r"([Ww][Ww][Ww])\.")
# GitHub's ``GH-<n>`` issue reference, any case, not inside a word (QA-212-D1).
_GH_REF_RE = re.compile(r"(?<![A-Za-z0-9])([Gg][Hh]-)(?=[0-9])")
_END_PUNCT = (".", "!", "?", _ELLIPSIS)

_T = TypeVar("_T")

_STATUS_LABELS = {
    STATUS_CONFIRMED: "confirmed",
    STATUS_NOT_REPRODUCED: "not reproduced",
    STATUS_NOT_CHECKED: "unchecked",
    STATUS_DROPPED_FOR_BUDGET: "unchecked",
}
_DOWNGRADE_TAGS = {
    DOWNGRADE_OUTSIDE_DIFF: " (Downgraded: not located in the diff.)",
    DOWNGRADE_NO_SCENARIO: " (Downgraded: no failure scenario.)",
}
# S-206 D7: GitHub's binary shape (no patch, no counts) is also an empty file
# or a mode-only change, so ``binary`` is never shown as "binary".
_NAME_ONLY_LABELS = {
    "lockfile": "lockfile",
    "generated": "generated",
    "binary": "no text diff",
    "excluded": "excluded",
    "content_unavailable": "content unavailable",
}
_WITHHELD_LABELS = {
    "excluded": "previous name is excluded",
    "lockfile": "previous name is a lockfile",
    "generated": "previous name is generated",
}


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


def _cut(text: str, limit: int | None) -> str:
    """``text`` cut to ``limit`` characters, the ellipsis included."""
    if limit is None or len(text) <= limit:
        return text
    return text[: limit - 1] + _ELLIPSIS


def neutralize(text: str, limit: int | None = None) -> str:
    """Plain model or repository text, inert in any Markdown slot (module docstring)."""
    out = _cut(text, limit).translate(_PLAIN).strip()
    out = _SCHEME_RE.sub(":" + _ZW + "//", out)
    out = _WWW_RE.sub(r"\1" + _ZW + ".", out)
    return _GH_REF_RE.sub(r"\1" + _ZW, out)


# What ``context.diff.escape_path`` rewrites; without one, it is the identity.
_PATH_UNSAFE_RE = re.compile("[\\\\\x00-\x1f\x7f-\x9f\u2028\u2029]")


def _escaped_path(text: str, limit: int | None) -> str:
    """``escape_path(text)`` without backticks, cut to ``limit``.

    Escaping only lengthens and keeps prefixes, so escaping the first
    ``limit + 1`` characters and cutting gives the same text as escaping all
    of it: a hostile 1 MB path costs one ``replace`` plus ``O(limit)``.
    """
    text = text.replace("`", "")  # escape_path neither makes nor touches backticks
    if limit is not None:
        text = text[: limit + 1]
    if _PATH_UNSAFE_RE.search(text) is not None:
        text = escape_path(text)
    return _cut(text, limit)


def _code_text(text: str, limit: int | None) -> str:
    return _escaped_path(text, limit).translate(_CODE)


def code_span(text: str, limit: int = CONTEXT_PATH_MAX, *, empty: str = "(unknown)") -> str:
    """``text`` as an inline code span that always closes (module docstring)."""
    inner = _code_text(text, limit)
    return f"`{inner}`" if inner.strip() else empty


def _plain(text: str, limit: int, *, empty: str = "(none)") -> str:
    out = neutralize(text, limit)
    return out if out else empty


def format_line(n: int) -> str:
    """A line number or count; above ``LINE_MAX`` it is ``999999999+`` (no huge ``str()``)."""
    if -LINE_MAX <= n <= LINE_MAX:
        return str(n)
    return ("-" if n < 0 else "") + f"{LINE_MAX}+"


def _plural(n: int, word: str) -> str:
    return word if n == 1 else word + "s"


def _counted(n: int, word: str) -> str:
    return f"{format_line(n)} {_plural(n, word)}"


# ---------------------------------------------------------------------------
# Run link and marker (D-29)
# ---------------------------------------------------------------------------


def run_link(panel_base_url: str, run_id: str) -> str | None:
    """``<base>/runs/<run_id>``, or ``None`` unless both are well-formed."""
    if not isinstance(panel_base_url, str) or not isinstance(run_id, str):
        return None
    base = panel_base_url.rstrip("/")
    if len(base) > PANEL_URL_MAX or not _PANEL_RE.fullmatch(base):
        return None
    if not _UUID_RE.fullmatch(run_id):
        return None
    return f"{base}/runs/{run_id}"


def _link(panel_base_url: str, run_id: str) -> str:
    url = run_link(panel_base_url, run_id)
    return f"[run]({url})" if url is not None else NO_LINK


def _marker(run_id: str, head_sha: str) -> str:
    run = run_id if isinstance(run_id, str) and _UUID_RE.fullmatch(run_id) else "invalid"
    sha = head_sha if isinstance(head_sha, str) and _SHA_RE.fullmatch(head_sha) else "invalid"
    return f"{MARKER_PREFIX}run={run} sha={sha} -->"


def _short_sha(head_sha: str) -> str:
    if isinstance(head_sha, str) and _SHA_RE.fullmatch(head_sha):
        return head_sha[:7]
    return "invalid"


# ---------------------------------------------------------------------------
# Lists with a shared budget (the context line, the budget comment)
# ---------------------------------------------------------------------------


class _Names:
    """Character budget shared by every list on one line."""

    def __init__(self, budget: int) -> None:
        self.left = budget

    def join(self, items: Sequence[_T], render: Callable[[_T], str], sep: str = ", ") -> str:
        """Render items while ``LIST_MAX`` and the budget allow; then "and N more"."""
        shown: list[str] = []
        for item in items:
            if len(shown) == LIST_MAX:
                break
            text = render(item)
            if shown and len(text) + len(sep) > self.left:
                break
            self.left -= len(text) + len(sep)
            shown.append(text)
        rest = len(items) - len(shown)
        if rest:
            shown.append(f"and {format_line(rest)} more")
        return sep.join(shown)


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def _location(f: Finding) -> str:
    start, end = format_line(f.line_start), format_line(f.line_end)
    span = start if start == end else f"{start}-{end}"
    path = _escaped_path(f.file, PATH_MAX)
    return "`" + (path + ":" + span).translate(_CODE) + "`"


def _lead(f: Finding, title: str | None = None) -> str:
    if title is None:
        title = _plain(f.title, TITLE_MAX, empty="(untitled)")
    fid, category = _plain(f.id, LABEL_MAX), _plain(f.category, LABEL_MAX)
    return f"**{fid} · {category} · {_location(f)}** — {title}"


def _blocking_full(f: Finding, lead: str, cut: bool) -> str:
    scenario = _plain(f.failure_scenario, SCENARIO_CUT if cut else SCENARIO_MAX)
    consequence = _plain(f.consequence, CONSEQUENCE_CUT if cut else CONSEQUENCE_MAX)
    return f"{lead}\n\n- **Fails when:** {scenario}\n- **Consequence:** {consequence}"


def _suggestion(f: Finding) -> str:
    title = _plain(f.title, TITLE_MAX, empty="(untitled)")
    sep = " " if title.endswith(_END_PUNCT) else ". "
    tag = ""
    if f.downgraded is not None:
        tag = _DOWNGRADE_TAGS.get(f.downgraded, " (Downgraded.)")
    return f"{_lead(f, title)}{sep}{_plain(f.consequence, CONSEQUENCE_MAX)}{tag}"


BLOCKING_HEADING = "### Blocking"


def _more(rest: int) -> str:
    verb = "finding is" if rest == 1 else "findings are"
    return f"{format_line(rest)} more blocking {verb} listed by title only:"


def _blocking_section(full: Sequence[str], lines: Sequence[str], j: int) -> str:
    """Blocking with the first ``j`` findings in full and the rest as one-liners."""
    parts = [BLOCKING_HEADING, *full[:j]]
    rest = len(full) - j
    if rest:
        parts.append(_more(rest))
        parts.append("\n".join(lines[j:]))
    return "\n\n".join(parts)


def _fit_blocking(fixed: int, full: Sequence[str], lines: Sequence[str], limit: int) -> int:
    """The largest ``j`` whose Blocking section fits in ``limit - fixed`` (stage 4).

    ``fixed`` is the body without the section and its separator. Lengths are
    summed, never rendered, so this is linear.
    """
    n = len(full)
    suffix = [0] * (n + 1)  # len("\n".join(lines[j:]))
    for i in range(n - 1, -1, -1):
        suffix[i] = len(lines[i]) + (suffix[i + 1] + 1 if i < n - 1 else 0)
    head = 0  # sum(2 + len(full[i]) for i < j)
    best = 0
    for j in range(n):
        rest = n - j
        size = len(BLOCKING_HEADING) + head + 2 + len(_more(rest)) + 2 + suffix[j]
        if fixed + 2 + size > limit:
            break
        best = j
        head += 2 + len(full[j])
    return best


_DETAILS_CLOSE = "\n\n</details>"


def _details_open(k: int, n: int) -> str:
    count = format_line(n) if k == n else f"{format_line(k)} of {format_line(n)}"
    return f"<details><summary>Suggestions ({count})</summary>\n\n"


def _suggestions_section(entries: Sequence[str], k: int) -> str | None:
    if k == 0:
        return None
    body = "\n\n".join(entries[:k])
    return _details_open(k, len(entries)) + body + _DETAILS_CLOSE


def _fit_suggestions(fixed: int, entries: Sequence[str], limit: int) -> int:
    """The largest ``k < len(entries)`` whose section fits beside ``fixed`` (stage 1)."""
    n = len(entries)
    total = 0  # sum(len(entries[i]) for i < k) + 2 * (k - 1)
    best = 0
    for k in range(1, n):
        total += len(entries[k - 1]) + (2 if k > 1 else 0)
        size = 2 + len(_details_open(k, n)) + total + len(_DETAILS_CLOSE)
        if fixed + size > limit:
            break
        best = k
    return best


# ---------------------------------------------------------------------------
# Verifier section (FR-16, FR-17; D-33, D-38)
# ---------------------------------------------------------------------------


def _candidate_line(c: CandidateStatus, cut: bool, paths: dict[str, str]) -> str:
    label = _STATUS_LABELS.get(c.status) or _plain(c.status, LABEL_MAX)
    row = _plain(c.candidate.text, VERIFIER_CUT if cut else ROW_MAX, empty="(empty row)")
    if c.reason_from_model:
        reason = _plain(c.reason, VERIFIER_CUT if cut else REASON_MAX, empty="(no reason given)")
    else:
        reason = NOT_CHECKED
    report = c.candidate.report_path
    path = paths.get(report)
    if path is None:
        path = paths[report] = code_span(report, CONTEXT_PATH_MAX)
    return f"- **{_plain(c.id, LABEL_MAX)} ({label})** from {path}: {row} — {reason}"


def _verifier_section(
    validation: Validation,
    context: ContextData,
    verifier: VerifierContext | None,
    cut: bool,
) -> str:
    reports: tuple[VerifierReport, ...] = verifier.reports if verifier is not None else ()
    state = verifier.state if verifier is not None else context.verifier_state
    unavailable = context.verifier_unavailable or (verifier is not None and verifier.unavailable)
    parsed = [r for r in reports if r.state == REPORT_PARSED]
    unparseable = [r for r in reports if r.state == REPORT_NOT_PARSEABLE]
    candidates = validation.candidates

    if candidates or parsed or state == REPORT_PARSED:
        paths: dict[str, str] = {}
        items = [_candidate_line(c, cut, paths) for c in candidates]
        for r in parsed:
            if not r.candidates:
                items.append(
                    f"- {code_span(r.path, CONTEXT_PATH_MAX)}: no Critical Unintended drift."
                )
        for r in unparseable:
            items.append(f"- {code_span(r.path, CONTEXT_PATH_MAX)}: report not parseable.")
        if unavailable:
            items.append("- Some verifier reports unavailable (permission).")
        other = verifier.other_drift if verifier is not None else 0
        if other:
            where = "reports" if len(parsed) > 1 else "report"
            items.append(f"- Other drift: {_counted(other, 'item')}, see the {where}.")
        if not items:
            items.append("- No Critical Unintended drift.")
        return "### Verifier\n\n" + "\n".join(items)

    if unparseable or state == REPORT_NOT_PARSEABLE:
        names = _Names(CONTEXT_MAX_CHARS).join([r.path for r in unparseable], _path)
        text = "**Verifier:** report not parseable" + (f" ({names})" if names else "")
        if unavailable:
            text += "; some verifier reports unavailable (permission)"
        return text + "."
    if unavailable:
        return "**Verifier:** verifier reports unavailable (permission)."
    return "**Verifier:** no verifier report."


# ---------------------------------------------------------------------------
# Context line (spec §8.4 step 4, §8.8)
# ---------------------------------------------------------------------------


def _shown_suffix(note: BlockNote | None) -> str:
    """The suffix for a block that reached the model, cut or not."""
    if note is None or note.state == STATE_OMITTED:
        return ""
    if note.state == STATE_TRIMMED:
        return " (trimmed)"
    return " (truncated for budget)" if note.reason == REASON_BUDGET else " (truncated)"


def _left_out(note: BlockNote) -> str:
    """The suffix for a block left out of the prompt."""
    return " (empty, not included)" if note.reason == REASON_EMPTY else " omitted (budget)"


def _note_suffix(note: BlockNote) -> str:
    return _left_out(note) if note.state == STATE_OMITTED else _shown_suffix(note)


def _issue_ref(ref: str | None) -> str:
    if ref is not None and _ISSUE_REF_RE.fullmatch(ref):
        return ref
    return _plain(ref or "", LABEL_MAX, empty="(unknown)")


def _name_only_label(f: NameOnlyFile) -> str:
    label = _NAME_ONLY_LABELS.get(f.reason) or _plain(f.reason.replace("_", " "), LABEL_MAX)
    if f.detail:
        label += ": " + _plain(f.detail, CONTEXT_PATH_MAX)
    return f"{code_span(f.filename, CONTEXT_PATH_MAX, empty='(no name)')} ({label})"


def _path(p: str | None) -> str:
    return code_span(p or "", CONTEXT_PATH_MAX, empty="(no name)")


def _withheld_label(f: FileDiff) -> str:
    rule = f.base_withheld or ""
    label = _WITHHELD_LABELS.get(rule) or "previous name is " + _plain(rule, LABEL_MAX)
    return f"{_path(f.filename)} ({label})"


def _context_line(context: ContextData, diff: DiffContext | None) -> str:
    """The context line: what the review saw, what it did not, and why."""
    names = _Names(CONTEXT_MAX_CHARS)
    notes: dict[tuple[str, str | None], BlockNote] = {}
    for note in context.notes:
        notes.setdefault((note.block, note.ref), note)
    clauses: list[str] = []

    # Issues.
    shown = context.issue_numbers

    def issue(n: int) -> str:
        return "#" + format_line(n) + _shown_suffix(notes.get((BLOCK_ISSUE, f"#{n}")))

    def left_issue(note: BlockNote) -> str:
        return "issue " + _issue_ref(note.ref) + _left_out(note)

    if shown:
        clauses.append(("issue " if len(shown) == 1 else "issues ") + names.join(shown, issue))
    shown_refs = {f"#{n}" for n in shown}
    left_issues = [
        n
        for n in context.notes
        if n.block == BLOCK_ISSUE and n.ref not in shown_refs and n.state == STATE_OMITTED
    ]
    if left_issues:
        clauses.append(names.join(left_issues, left_issue, " · "))
    if context.issues_unavailable:
        clauses.append("issues unavailable (permission)")
    elif not shown and not left_issues:
        clauses.append("no linked issues")

    # Spec: shown (with its trim or cut), then left out.
    specs = [(p, _shown_suffix(notes.get((BLOCK_SPEC, p)))) for p in context.spec_paths]
    shown_specs = set(context.spec_paths)
    specs += [
        (n.ref or "", _left_out(n))
        for n in context.notes
        if n.block == BLOCK_SPEC and n.ref not in shown_specs and n.state == STATE_OMITTED
    ]

    def spec(item: tuple[str, str]) -> str:
        return "spec " + _path(item[0]) + item[1]

    clauses.append(names.join(specs, spec, " · ") if specs else "no spec found")

    # PR description, drift sections, conventions.
    pr = notes.get((BLOCK_PR, None))
    if pr is not None:
        clauses.append("PR description" + _note_suffix(pr))

    def drift_note(note: BlockNote) -> str:
        return "verifier report " + _path(note.ref) + _note_suffix(note)

    drift = [n for n in context.notes if n.block == BLOCK_VERIFIER]
    if drift:
        clauses.append(names.join(drift, drift_note, " · "))
    conventions = notes.get((BLOCK_CONVENTIONS, None))
    if conventions is not None:
        clauses.append("conventions" + _note_suffix(conventions))

    # Full files (S-210 DR-12: with none left, the reason is the context, not size).
    dropped = context.full_files_dropped
    if dropped and not context.full_files_included:
        count = _counted(len(dropped), "file")
        clauses.append(f"full files omitted to fit the model's context ({count})")
    elif dropped:
        lead = f"{_counted(len(dropped), 'file')} too large to include in full: "
        clauses.append(lead + names.join(dropped, _path))

    # Listed by name only, the listing cut, withheld bases (S-206 D4, D7).
    if diff is not None and diff.name_only:
        clauses.append("listed by name only: " + names.join(diff.name_only, _name_only_label))
    if any(n.block == BLOCK_DIFF for n in context.notes):
        clauses.append("name-only list truncated for the model")
    withheld = [f for f in diff.files if f.base_withheld] if diff is not None else []
    if withheld:
        clauses.append("base withheld: " + names.join(withheld, _withheld_label))
    return "**Context:** " + " · ".join(clauses)


# ---------------------------------------------------------------------------
# The review comment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rendered:
    """A rendered review comment and the size stages it needed (spec §5.3 metrics)."""

    body: str
    stages: tuple[int, ...] = ()  # applied stages, 1–5, in order

    @property
    def truncated(self) -> bool:
        """``runs.metrics.comment_truncated``."""
        return bool(self.stages)

    @property
    def chars(self) -> int:
        """``runs.metrics.comment_chars``."""
        return len(self.body)


def _join(parts: Iterable[str | None]) -> str:
    return "\n\n".join(p for p in parts if p) + "\n"


def _footer(model_id: str, rubric_version: str, link: str) -> str:
    model = code_span(model_id, MODEL_MAX)
    version = _plain(rubric_version, VERSION_MAX, empty="?")
    scope = "; ".join(OUT_OF_SCOPE)
    return f"<sub>Not reviewed here: {scope}. Model {model} · rubric v{version} · {link}</sub>"


def render_review(
    validation: Validation,
    *,
    context: ContextData,
    diff: DiffContext | None,
    verifier: VerifierContext | None,
    run_id: str,
    head_sha: str,
    model_id: str,
    rubric_version: str,
    panel_base_url: str,
    limit: int = MAX_COMMENT_CHARS,
) -> Rendered:
    """The review comment (spec §8.8), at most ``limit`` characters (module docstring).

    ``context`` is the ``ContextData`` of the call whose output was accepted
    (``ReviewResult.context``); ``diff`` is the run's ``DiffContext`` (name-only
    files, withheld bases); ``verifier`` the run's ``VerifierContext``
    (per-report states, other drift). ``limit`` exists for tests; it must be
    at least ``MIN_LIMIT``.
    """
    if not isinstance(limit, int) or limit < MIN_LIMIT:
        raise ValueError(f"limit must be an int >= {MIN_LIMIT}")
    if validation.verdict not in (VERDICT_BLOCKING, VERDICT_CLEAR):
        raise ValueError("unknown verdict")

    header = f"## Code review: **{validation.verdict}** · `{_short_sha(head_sha)}`"
    head = f"{_marker(run_id, head_sha)}\n\n{header}"
    footer = _footer(model_id, rubric_version, _link(panel_base_url, run_id))
    context_line = _context_line(context, diff)
    blocking, suggestions = validation.blocking, validation.suggestions
    leads = [_lead(f) for f in blocking]
    full = [_blocking_full(f, lead, False) for f, lead in zip(blocking, leads, strict=True)]
    lines: list[str] = []
    entries = [_suggestion(f) for f in suggestions]
    verifier_text = _verifier_section(validation, context, verifier, False)
    k, j = len(entries), len(blocking)

    def assemble(note: bool, *, with_suggestions: bool = True, with_blocking: bool = True) -> str:
        return _join(
            [
                head,
                _blocking_section(full, lines, j) if blocking and with_blocking else None,
                verifier_text,
                _suggestions_section(entries, k) if with_suggestions else None,
                context_line,
                TRUNCATION_NOTE if note else None,
                footer,
            ]
        )

    body = assemble(False)
    if len(body) <= limit:
        return Rendered(body)
    stages: list[int] = []

    # Stage 1: drop suggestions from the end.
    if entries:
        stages.append(1)
        k = _fit_suggestions(len(assemble(True, with_suggestions=False)), entries, limit)
        body = assemble(True)
        if len(body) <= limit:
            return Rendered(body, tuple(stages))

    # Stage 2: cut blocking scenarios and consequences.
    cut_full = [_blocking_full(f, lead, True) for f, lead in zip(blocking, leads, strict=True)]
    if cut_full != full:
        stages.append(2)
        full = cut_full
        body = assemble(True)
        if len(body) <= limit:
            return Rendered(body, tuple(stages))

    # Stage 3: cut verifier rows and reasons.
    cut_verifier = _verifier_section(validation, context, verifier, True)
    if cut_verifier != verifier_text:
        stages.append(3)
        verifier_text = cut_verifier
        body = assemble(True)
        if len(body) <= limit:
            return Rendered(body, tuple(stages))

    # Stage 4: the blocking findings that do not fit become one-line entries.
    if blocking:
        stages.append(4)
        lines = ["- " + lead for lead in leads]
        j = _fit_blocking(len(assemble(True, with_blocking=False)), full, lines, limit)
        body = assemble(True)
        if len(body) <= limit:
            return Rendered(body, tuple(stages))

    # Stage 5: hard cut at the last line boundary that fits. Blocking findings
    # are cut as whole entries and the rest are counted (QA-212-D2).
    stages.append(5)
    top = head + "\n\n"
    bottom = "\n\n" + TRUNCATION_NOTE + "\n\n" + footer + "\n"
    room = limit - len(top) - len(bottom)
    if blocking:  # stage 4 ran and fitted no full entry, so ``j == 0``
        section = _blocking_section(full, lines, 0)
        if len(section) <= room:
            rest = _cut_lines(
                _join([verifier_text, context_line]).rstrip("\n"), room - len(section) - 2
            )
            middle = section + ("\n\n" + rest if rest else "")
        else:
            middle = _trim_blocking(lines, room)
    else:
        middle = _cut_lines(body[len(top) : len(body) - len(bottom)], room)
    body = top + middle + bottom if middle else head + bottom
    return Rendered(body, tuple(stages))


def _cut_lines(text: str, room: int) -> str:
    """``text`` cut at the last line boundary within ``room`` characters."""
    if len(text) <= room:
        return text
    if room <= 0:
        return ""
    piece = text[: room + 1]
    cut = piece.rfind("\n")
    return piece[:cut].rstrip("\n") if cut >= 0 else ""


def _not_shown(rest: int, listed: int) -> str:
    noun = "finding" if rest == 1 else "findings"
    lead = "and " if listed else ""
    more = "more " if listed else ""
    return f"{lead}{format_line(rest)} {more}blocking {noun} not shown."


def _trim_blocking(lines: Sequence[str], room: int) -> str:
    """The one-line Blocking list cut to whole entries within ``room``, the rest counted.

    The lead-in states exactly how many entries follow, and the closing line
    how many are not shown, so every blocking finding is rendered or counted.
    """
    n = len(lines)
    best, total = 0, 0
    for m in range(1, n + 1):
        total += len(lines[m - 1]) + (1 if m > 1 else 0)
        size = len(BLOCKING_HEADING) + 2 + len(_more(m)) + 2 + total
        if m < n:
            size += 2 + len(_not_shown(n - m, m))
        if size > room:
            break
        best = m
    parts = [BLOCKING_HEADING]
    if best:
        parts += [_more(best), "\n".join(lines[:best])]
    if best < n:
        parts.append(_not_shown(n - best, best))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Budget and failure comments (PRD FR-6, FR-26; spec §8.8, §13)
# ---------------------------------------------------------------------------


def render_budget(
    over: OverBudget,
    *,
    run_id: str,
    panel_base_url: str,
    name_only: Sequence[NameOnlyFile] = (),
) -> str:
    """The budget comment (FR-6), with the counts and the run link.

    ``name_only`` (the classification's name-only files, which the line count
    excludes) adds one "Not counted" line.
    """
    files = _counted(over.files, "file")
    changed = _counted(over.lines, "line")
    budget = format_line(over.max_diff_lines)
    if over.reason == OVER_TOKENS:
        if (
            over.tokens is not None
            and over.diff_tokens is not None
            and over.max_context_tokens is not None
        ):
            text = (
                f"This PR changes {changed} in {files}; its expanded diff needs about"
                f" {format_line(over.diff_tokens)} tokens ({format_line(over.tokens)} with the"
                f" review instructions), over the context budget of"
                f" {format_line(over.max_context_tokens)} tokens. Not reviewed."
            )
        else:
            text = (
                f"This PR changes {changed} in {files}; its expanded diff is over the"
                " context budget. Not reviewed."
            )
    elif over.truncated:
        text = (
            f"This PR changes at least {changed} in at least {files}. Its file list is longer"
            " than GitHub returns, so it cannot be reviewed in full within the review budget"
            f" of {budget} lines. Not reviewed."
        )
    else:
        text = (
            f"This PR changes {changed} in {files}, over the review budget of {budget} lines."
            " Not reviewed."
        )
    body = f"{text} {_link(panel_base_url, run_id)}\n"
    if name_only:
        listed = _Names(CONTEXT_MAX_CHARS).join(name_only, _name_only_label)
        body += f"\nNot counted, listed by name only: {listed}.\n"
    return body


def canonical_code(error_code: object) -> str:
    """The ``ERROR_CODES`` constant ``error_code`` names, else ``INTERNAL_ERROR`` (QA-212-D3).

    The caller's object is never rendered: a ``(str, Enum)`` member or a ``str``
    subclass with its own ``__format__`` or ``__eq__`` is reduced to its plain
    string value with ``str.__str__`` and looked up, and the matched constant
    is what the comment prints.
    """
    if not isinstance(error_code, str):
        return FALLBACK_CODE
    return _CANONICAL_CODES.get(str.__str__(error_code), FALLBACK_CODE)


def render_failure(error_code: str, *, run_id: str, panel_base_url: str) -> str:
    """The one-line failure comment: fixed text for a spec §13 code, never a message."""
    code = canonical_code(error_code)
    return f"Code review failed (`{code}`). {_link(panel_base_url, run_id)}\n"
