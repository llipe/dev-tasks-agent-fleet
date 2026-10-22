"""
dev-tasks conventions the context reader depends on (spec §8.3, §16 R3).

Every regex and name mapping tied to a dev-tasks convention lives here, so a
change in the conventions (issue titles, the ``## Task Checklist`` heading,
spec file names) is a one-file change pinned by the L1 tests:

- closing links in a PR body and the ``issue/<N>-`` branch (D-22);
- the task checklist the ``plan`` skill appends to a story issue (D-23), and
  the other forms GitHub renders as that heading (D-43);
- spec resolution: explicit path, ``[PRD-<name>]`` title, ``prd:<name>`` label
  (D-24), and ``Spec §<n>`` citations used to trim the spec;
- the story ID in a story issue title (``Story S-<id>``; S-208 reuses it);
- verifier fidelity-report names, the drift heading, and the candidate words
  (D-25, D-33; S-208);
- the repository conventions sources: ``AGENTS.md``/``CLAUDE.md`` and the ADR
  title and ``Status`` line forms (PRD FR-11; S-208).

Name groups are restricted to ``[A-Za-z0-9._-]``, so no extracted name can
contain ``/`` and every derived path stays one file directly under
``workstream/``.
"""

from __future__ import annotations

import re

__all__ = [
    "ADR_DIR",
    "ADR_NAME_RE",
    "ADR_STATUS_HEADING_RE",
    "ADR_STATUS_LINE_RE",
    "BRANCH_ISSUE_RE",
    "CANDIDATE_TOKEN_CAP",
    "CONVENTIONS_SHARE_DENOMINATOR",
    "CONVENTIONS_SHARE_NUMERATOR",
    "CONVENTION_FILES",
    "DRIFT_CRITICAL_RE",
    "DRIFT_HEADING_RE",
    "DRIFT_SECTION_TOKEN_CAP",
    "DRIFT_UNINTENDED_RE",
    "ISSUE_LINK_RE",
    "ISSUE_TOKEN_CAP",
    "MAX_ISSUE_NUMBER",
    "LINE_END_RE",
    "MAX_ADRS",
    "MAX_ADR_FIELD_CHARS",
    "MAX_LINKED_ISSUES",
    "MAX_SPEC_CITATIONS",
    "PRD_LABEL_RE",
    "PRD_TITLE_RE",
    "SPEC_CITATION_RE",
    "SPEC_PATH_RE",
    "SPEC_SHARE_DENOMINATOR",
    "SPEC_SHARE_NUMERATOR",
    "STORY_TITLE_RE",
    "SETEXT_UNDERLINE_RE",
    "TASK_CHECKLIST_RE",
    "TASK_CHECKLIST_SETEXT_RE",
    "ZERO_WIDTH_RE",
    "issue_report_path",
    "spec_path_for_prd",
    "story_report_path",
]

# -- linked issues (spec §8.3 step 2, D-22) ---------------------------------

# Over the PR body, case-insensitive. ``#`` must follow whitespace, so a
# cross-repository ``owner/repo#N`` and a full issue URL never match.
# ``(?:\s*:\s+|\s+)`` is the language of ``\s*:?\s+`` without its quadratic
# backtracking over a long whitespace run not followed by ``#``. ``re.ASCII``
# keeps ``\d`` to 0-9 and the case fold to ASCII, as GitHub links (no ``#\u0663``,
# no ``clo\u017fes``).
ISSUE_LINK_RE = re.compile(
    r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)(?:\s*:\s+|\s+)#(\d+)\b",
    re.IGNORECASE | re.ASCII,
)
# Over the head ref, case-sensitive.
BRANCH_ISSUE_RE = re.compile(r"^issue/(\d+)-", re.ASCII)
MAX_LINKED_ISSUES = 5
# The issue numbers ``GitHubClient`` accepts (``[1-9][0-9]{0,9}``).
MAX_ISSUE_NUMBER = 9_999_999_999
ISSUE_TOKEN_CAP = 8_000

# -- task checklist (D-23, D-43) ---------------------------------------------

# The body is split into lines on ``\r\n``, ``\r`` or ``\n`` (the CommonMark line
# endings), and each line has ``ZERO_WIDTH_RE`` removed before matching.
LINE_END_RE = re.compile(r"\r\n|\r|\n")
# U+200B-U+200D, U+2060, U+FEFF: invisible when rendered.
ZERO_WIDTH_RE = re.compile("[\u200b-\u200d\u2060\ufeff]")
# Applied with ``fullmatch`` to each line. Case-sensitive. An ATX heading
# indented 0-3 spaces, levels 1-6, an optional closing ``#`` sequence; the words
# separated or surrounded by any whitespace run (``\s``, so NBSP too). Linear in
# the line length: each whitespace run is bounded by a literal it cannot match.
TASK_CHECKLIST_RE = re.compile(r" {0,3}#{1,6}\s+Task\s+Checklist(?:\s+#+)?\s*")
# A setext heading: this line, then a line matching ``SETEXT_UNDERLINE_RE``; the
# cut starts at this line. 0-3 spaces of indentation (4 is a code block), then
# any whitespace that is not a space or tab (NBSP), as for the ATX form.
TASK_CHECKLIST_SETEXT_RE = re.compile(r" {0,3}(?![ \t])\s*Task\s+Checklist\s*")
SETEXT_UNDERLINE_RE = re.compile(r" {0,3}(?:=+|-+)\s*")

# -- spec (spec §8.3 step 3, D-24) --------------------------------------------

SPEC_PATH_RE = re.compile(r"workstream/specification-[A-Za-z0-9._-]+\.md")
PRD_TITLE_RE = re.compile(r"^\[PRD-([A-Za-z0-9._-]+)\]")
# Applied with ``fullmatch`` to each label name.
PRD_LABEL_RE = re.compile(r"prd:([A-Za-z0-9._-]+)")
# ``Spec §8``, ``Spec §8.1``, ``Spec §8.3.2`` (the issue-body citation form).
SPEC_CITATION_RE = re.compile(r"\bSpec\s*§\s*(\d+(?:\.\d+)*)", re.ASCII)
# Distinct citations used to trim a spec; later ones are ignored and counted
# (``SpecContext.citations_ignored``), so trimming costs at most 200 x sections.
MAX_SPEC_CITATIONS = 200
# ``Story S-170`` in a story issue title.
STORY_TITLE_RE = re.compile(r"\bStory (S-\d+)\b", re.ASCII)
# The spec block's share of ``max_context_tokens``: 30% (spec §8.3, §8.4).
SPEC_SHARE_NUMERATOR = 3
SPEC_SHARE_DENOMINATOR = 10


def spec_path_for_prd(name: str) -> str:
    """``workstream/specification-prd-<name>.md`` (D-24; corrects PRD FR-8)."""
    return f"workstream/specification-prd-{name}.md"


# -- verifier reports (spec §8.3 step 4, D-25, D-33, D-38) --------------------

# Per linked issue: ``fidelity-report-S-<id>.md`` (``<id>`` from
# ``STORY_TITLE_RE``, so ``S-`` plus ASCII digits) and
# ``fidelity-report-issue-<N>.md`` (``<N>`` the issue number). Rollups
# (``*-rollup.md``) are never built, so never requested.


def story_report_path(story_id: str) -> str:
    """``workstream/fidelity-report-S-<id>.md`` for ``story_id`` ``S-<id>`` (D-25)."""
    return f"workstream/fidelity-report-{story_id}.md"


def issue_report_path(number: int) -> str:
    """``workstream/fidelity-report-issue-<N>.md`` (D-25)."""
    return f"workstream/fidelity-report-issue-{number}.md"


# Applied with ``match`` to each line (the spec's ``^`` anchor), outside code
# fences. Case-sensitive; ``re.ASCII`` keeps ``\s`` to ASCII whitespace, so
# ``##\u00a0Drift`` is not a drift heading. ``## 4. Drift catalog`` does not
# match (DF-05, the spec regex as written). Linear: ``\s+`` is followed by a
# literal it cannot match.
DRIFT_HEADING_RE = re.compile(r"#{2,3}\s+(Drift|Drift catalog)\b", re.ASCII)
# Whole, case-sensitive words, searched in a table data row. ``re.ASCII``: a
# word character is ``[A-Za-z0-9_]``, so ``Non-critical``, ``CRITICAL`` and
# ``Critical_1`` miss and ``Non-Critical`` and ``**Critical**`` hit (DF-05).
DRIFT_CRITICAL_RE = re.compile(r"\bCritical\b", re.ASCII)
DRIFT_UNINTENDED_RE = re.compile(r"\bUnintended\b", re.ASCII)
# A candidate's row text is cut to this estimate (spec §8.3, §8.4 b).
CANDIDATE_TOKEN_CAP = 300
# The drift section passed as context, per report (spec §8.3, §8.4 d).
DRIFT_SECTION_TOKEN_CAP = 4_000

# -- repository conventions (spec §8.3 step 5, PRD FR-11) ---------------------

# Read at head in this order; the first present file wins.
CONVENTION_FILES = ("AGENTS.md", "CLAUDE.md")
ADR_DIR = "docs/adr"
# Applied with ``fullmatch`` to each listed name: only these names are
# requested, as ``docs/adr/<name>``, so no listed name can add a path segment.
ADR_NAME_RE = re.compile(r"[A-Za-z0-9._-]+\.md", re.ASCII)
MAX_ADRS = 50
# An ADR's title and Status line are each cut to this many characters.
MAX_ADR_FIELD_CHARS = 200
# ``Status: Accepted``, ``**Status:** Accepted``, ``- Status: Accepted``: applied
# with ``match`` to a line. Case-sensitive. Linear: each optional part starts
# with a character the part before it cannot match.
ADR_STATUS_LINE_RE = re.compile(r"[ \t]*(?:[-*+][ \t]+)?(?:\*\*|__)?Status(?:\*\*|__)?[ \t]*:")
# ``## Status`` (any level, optional closing hashes): applied with ``fullmatch``;
# the status is the next non-blank line when it is not a heading.
ADR_STATUS_HEADING_RE = re.compile(r"[ \t]{0,3}#{1,6}[ \t]+Status[ \t]*(?:#+[ \t]*)?")
# The conventions block's share of ``max_context_tokens``: 10% (spec §8.3, §8.4 f).
CONVENTIONS_SHARE_NUMERATOR = 1
CONVENTIONS_SHARE_DENOMINATOR = 10
