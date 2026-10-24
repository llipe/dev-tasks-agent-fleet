"""
Spec resolution and trimming (S-207; spec §8.3 step 3, §8.4; D-24).

Resolution, per linked issue, first hit wins (``spec_candidates``):

(a) the first ``workstream/specification-*.md`` path in the checklist-stripped
    body;
(b) the title prefix ``[PRD-<name>]``;
(c) the first label ``prd:<name>``;

(b) and (c) map to ``workstream/specification-prd-<name>.md``. Each path is
read at ``head_sha``; a 404 (``None``) falls through to the next rule and logs
a ``warn``. Paths are cached, so each is requested at most once per run, and a
spec two issues resolve to is included once. No hit for any issue means no
spec (``SpecContext.spec is None``, "no spec found").

Several distinct specs (DF-20, pinned here): all are kept, in issue order, and
the spec block's 30% share of ``max_context_tokens`` is split equally among
them, so their combined estimate stays within the one spec cap of §8.4.

Trimming (``trim_spec``), when a spec is over its cap: the spec is split at
Markdown headings (ATX, levels 1-6, outside code fences as
``context.markdown.FenceTracker`` defines them) and keeps

(i) every heading line (the outline);
(ii) the sections cited in an issue body as ``Spec §<n>[.<m>…]``: a heading
     whose number has the citation as a dotted prefix (``8`` keeps ``8`` and
     ``8.10`` but not ``80``; ``8.1`` keeps ``8.1.2`` but not ``8.10``), with
     every deeper heading under it; only the first 200 distinct citations
     count (``MAX_SPEC_CITATIONS``; ``SpecContext.citations_ignored`` counts
     the rest);
(iii) the sections whose heading or text names a linked story ID (from the
      ``Story S-<id>`` title) or a reviewed file path;

then truncates to the cap with a ``[truncated]`` marker if still over.

Spec content and issue text are untrusted repository data: they are matched
against the regexes in ``context.conventions`` and otherwise kept verbatim for
the prompt builder (S-209) to fence. Extracted names cannot contain ``/``, so
every request is ``contents/workstream/specification-<name>.md`` at
``head_sha``; the client's guard percent-encodes and checks it again.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from context.conventions import (
    MAX_SPEC_CITATIONS,
    PRD_LABEL_RE,
    PRD_TITLE_RE,
    SPEC_CITATION_RE,
    SPEC_PATH_RE,
    SPEC_SHARE_DENOMINATOR,
    SPEC_SHARE_NUMERATOR,
    STORY_TITLE_RE,
    spec_path_for_prd,
)
from context.diff import split_lines
from context.issues import LinkedIssue, Warn
from context.markdown import FenceTracker
from context.tokens import estimate, truncate
from github_client import GitHubClient

__all__ = [
    "ResolvedSpec",
    "SpecContext",
    "resolve_specs",
    "spec_candidates",
    "spec_cap",
    "spec_citations",
    "story_ids",
    "trim_spec",
]


@dataclass(frozen=True)
class ResolvedSpec:
    path: str
    text: str  # whole, or trimmed/truncated to its share of the cap
    trimmed: bool
    truncated: bool
    tokens: int  # estimate of the spec as read, before trimming
    issue: int  # the linked issue that resolved it first


@dataclass(frozen=True)
class SpecContext:
    specs: tuple[ResolvedSpec, ...]
    misses: tuple[str, ...]  # paths tried that returned 404, in request order
    citations: tuple[str, ...]  # ``Spec §`` numbers cited in the linked issues
    story_ids: tuple[str, ...]  # story IDs from the linked issue titles
    citations_ignored: int = 0  # distinct citations past ``MAX_SPEC_CITATIONS``

    @property
    def spec(self) -> ResolvedSpec | None:
        """The first resolved spec, or ``None`` ("no spec found")."""
        return self.specs[0] if self.specs else None


def spec_cap(max_context_tokens: int) -> int:
    """30% of ``max_context_tokens``, rounded down (spec §8.3, §8.4 e)."""
    return max_context_tokens * SPEC_SHARE_NUMERATOR // SPEC_SHARE_DENOMINATOR


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def spec_candidates(issue: LinkedIssue) -> tuple[str, ...]:
    """Spec paths to try for ``issue``, in rule order (a), (b), (c), deduped."""
    candidates: list[str] = []
    explicit = SPEC_PATH_RE.search(issue.stripped_body)
    if explicit is not None:
        candidates.append(explicit.group(0))
    title = PRD_TITLE_RE.match(issue.title)
    if title is not None:
        candidates.append(spec_path_for_prd(title.group(1)))
    for label in issue.labels:
        match = PRD_LABEL_RE.fullmatch(label)
        if match is not None:
            candidates.append(spec_path_for_prd(match.group(1)))
            break
    return tuple(dict.fromkeys(candidates))


def _distinct_citations(issues: Iterable[LinkedIssue]) -> tuple[str, ...]:
    found = [m.group(1) for i in issues for m in SPEC_CITATION_RE.finditer(i.stripped_body)]
    return tuple(dict.fromkeys(found))


def spec_citations(issues: Iterable[LinkedIssue]) -> tuple[str, ...]:
    """``Spec §<n>`` numbers in the checklist-stripped bodies, deduped, in order.

    The first ``MAX_SPEC_CITATIONS`` distinct numbers; later ones are ignored.
    """
    return _distinct_citations(issues)[:MAX_SPEC_CITATIONS]


def story_ids(issues: Iterable[LinkedIssue]) -> tuple[str, ...]:
    """``S-<id>`` from ``Story S-<id>`` in the linked issue titles, deduped."""
    found = [m.group(1) for i in issues for m in STORY_TITLE_RE.finditer(i.title)]
    return tuple(dict.fromkeys(found))


def resolve_specs(
    client: GitHubClient,
    issues: Sequence[LinkedIssue],
    head_sha: str,
    *,
    reviewed_paths: Iterable[str],
    max_context_tokens: int,
    warn: Warn | None = None,
) -> SpecContext:
    """Resolve, fetch once, dedupe, and trim the specs of the linked issues."""
    reviewed = tuple(p for p in reviewed_paths if p)
    distinct = _distinct_citations(issues)
    citations = distinct[:MAX_SPEC_CITATIONS]
    ids = story_ids(issues)
    cache: dict[str, str | None] = {}
    misses: list[str] = []
    found: dict[str, tuple[str, int]] = {}  # path -> (content, issue number)
    for issue in issues:
        for path in spec_candidates(issue):
            if path not in cache:
                cache[path] = client.get_content_raw(path, head_sha)
                if cache[path] is None:
                    misses.append(path)
                    if warn is not None:
                        warn("spec not found", path=path)
            content = cache[path]
            if content is not None:
                found.setdefault(path, (content, issue.number))
                break
    share = spec_cap(max_context_tokens) // max(1, len(found))
    specs = []
    for path, (content, number) in found.items():
        text, trimmed, truncated = trim_spec(
            content, citations=citations, story_ids=ids, reviewed_paths=reviewed, cap_tokens=share
        )
        specs.append(ResolvedSpec(path, text, trimmed, truncated, estimate(content), number))
    return SpecContext(tuple(specs), tuple(misses), citations, ids, len(distinct) - len(citations))


# ---------------------------------------------------------------------------
# Trimming
# ---------------------------------------------------------------------------

# ATX heading, applied with ``fullmatch`` to a line without its ``\n``. The
# title is captured greedily and ``rstrip``-ed of spaces, tabs and ``\r``: a lazy
# title before ``[ \t]*`` backtracks quadratically over a long whitespace run.
_HEADING_RE = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*))?\r?")
# The leading section number of a heading: ``8``, ``8.``, ``8.1``, ``8.1.2``.
_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)*)\.?(?=\s|$)")


@dataclass
class _Section:
    heading: str  # the heading line with its newline; "" for the preamble
    level: int  # 0 for the preamble
    number: str | None
    body: str = ""


def _split_sections(text: str) -> list[_Section]:
    sections = [_Section("", 0, None)]
    fence = FenceTracker()
    for line in split_lines(text):
        bare = line.rstrip("\n")
        if fence.step(bare):
            sections[-1].body += line
            continue
        heading = _HEADING_RE.fullmatch(bare)
        if heading is None:
            sections[-1].body += line
            continue
        number = _NUMBER_RE.match((heading.group(2) or "").rstrip(" \t\r"))
        sections.append(_Section(line, len(heading.group(1)), number and number.group(1)))
    return sections


def _cited(number: str | None, exact: frozenset[str], prefixes: tuple[str, ...]) -> bool:
    """``number`` equals a citation or has one as a dotted prefix (C-level checks)."""
    return number is not None and (number in exact or number.startswith(prefixes))


def _names_any(text: str, ids: Sequence[re.Pattern[str]], paths: Sequence[str]) -> bool:
    return any(p.search(text) for p in ids) or any(path in text for path in paths)


def trim_spec(
    text: str,
    *,
    citations: Sequence[str],
    story_ids: Sequence[str],
    reviewed_paths: Sequence[str],
    cap_tokens: int,
) -> tuple[str, bool, bool]:
    """``(text, trimmed, truncated)``; whole when within ``cap_tokens``."""
    if estimate(text) <= cap_tokens:
        return text, False, False
    sections = _split_sections(text)
    # Deduped and capped, so the cost is at most ``MAX_SPEC_CITATIONS`` x sections.
    cited = tuple(dict.fromkeys(citations))[:MAX_SPEC_CITATIONS]
    exact = frozenset(cited)
    prefixes = tuple(c + "." for c in cited)
    id_patterns = [re.compile(r"\b" + re.escape(i) + r"(?!\d)") for i in story_ids]
    paths = [p for p in reviewed_paths if p]
    keep = [False] * len(sections)
    for i, section in enumerate(sections):
        if _cited(section.number, exact, prefixes):
            keep[i] = True
            j = i + 1
            while j < len(sections) and sections[j].level > section.level:
                keep[j] = True
                j += 1
        elif _names_any(section.heading + section.body, id_patterns, paths):
            keep[i] = True
    selected = "".join(
        s.heading + (s.body if k else "") for s, k in zip(sections, keep, strict=True)
    )
    out, truncated = truncate(selected, cap_tokens)
    return out, True, truncated
