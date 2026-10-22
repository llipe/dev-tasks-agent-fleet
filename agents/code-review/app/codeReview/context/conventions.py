"""
dev-tasks conventions the context reader depends on (spec §8.3, §16 R3).

Every regex and name mapping tied to a dev-tasks convention lives here, so a
change in the conventions (issue titles, the ``## Task Checklist`` heading,
spec file names) is a one-file change pinned by the L1 tests:

- closing links in a PR body and the ``issue/<N>-`` branch (D-22);
- the task checklist the ``plan`` skill appends to a story issue (D-23);
- spec resolution: explicit path, ``[PRD-<name>]`` title, ``prd:<name>`` label
  (D-24), and ``Spec §<n>`` citations used to trim the spec;
- the story ID in a story issue title (``Story S-<id>``; S-208 reuses it).

Name groups are restricted to ``[A-Za-z0-9._-]``, so no extracted name can
contain ``/`` and every derived path stays one file directly under
``workstream/``.
"""

from __future__ import annotations

import re

__all__ = [
    "BRANCH_ISSUE_RE",
    "ISSUE_LINK_RE",
    "ISSUE_TOKEN_CAP",
    "MAX_ISSUE_NUMBER",
    "MAX_LINKED_ISSUES",
    "PRD_LABEL_RE",
    "PRD_TITLE_RE",
    "SPEC_CITATION_RE",
    "SPEC_PATH_RE",
    "SPEC_SHARE_DENOMINATOR",
    "SPEC_SHARE_NUMERATOR",
    "STORY_TITLE_RE",
    "TASK_CHECKLIST_RE",
    "spec_path_for_prd",
]

# -- linked issues (spec §8.3 step 2, D-22) ---------------------------------

# Over the PR body, case-insensitive. ``#`` must follow whitespace, so a
# cross-repository ``owner/repo#N`` and a full issue URL never match.
ISSUE_LINK_RE = re.compile(
    r"\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)\b", re.IGNORECASE
)
# Over the head ref, case-sensitive.
BRANCH_ISSUE_RE = re.compile(r"^issue/(\d+)-")
MAX_LINKED_ISSUES = 5
# The issue numbers ``GitHubClient`` accepts (``[1-9][0-9]{0,9}``).
MAX_ISSUE_NUMBER = 9_999_999_999
ISSUE_TOKEN_CAP = 8_000

# -- task checklist (D-23) -----------------------------------------------------

# Applied with ``fullmatch`` to each line of the body (split on ``\n``), so
# ``\s`` never spans lines; a trailing ``\r`` from CRLF bodies is whitespace.
TASK_CHECKLIST_RE = re.compile(r"#{1,6}\s+Task Checklist\s*")

# -- spec (spec §8.3 step 3, D-24) --------------------------------------------

SPEC_PATH_RE = re.compile(r"workstream/specification-[A-Za-z0-9._-]+\.md")
PRD_TITLE_RE = re.compile(r"^\[PRD-([A-Za-z0-9._-]+)\]")
# Applied with ``fullmatch`` to each label name.
PRD_LABEL_RE = re.compile(r"prd:([A-Za-z0-9._-]+)")
# ``Spec §8``, ``Spec §8.1``, ``Spec §8.3.2`` (the issue-body citation form).
SPEC_CITATION_RE = re.compile(r"\bSpec\s*§\s*(\d+(?:\.\d+)*)")
# ``Story S-170`` in a story issue title.
STORY_TITLE_RE = re.compile(r"\bStory (S-\d+)\b")
# The spec block's share of ``max_context_tokens``: 30% (spec §8.3, §8.4).
SPEC_SHARE_NUMERATOR = 3
SPEC_SHARE_DENOMINATOR = 10


def spec_path_for_prd(name: str) -> str:
    """``workstream/specification-prd-<name>.md`` (D-24; corrects PRD FR-8)."""
    return f"workstream/specification-prd-{name}.md"
