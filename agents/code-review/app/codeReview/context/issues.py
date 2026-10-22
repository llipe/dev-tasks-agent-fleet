"""
Linked issues (S-207; spec §8.3 step 2, §13; D-22, D-23).

``linked_issues`` finds the issues a PR implements and reads them:

1. ``linked_issue_numbers``: the closing-keyword regex over the PR body (same
   repository only), then ``issue/<N>-`` on the head ref; deduped, first 5 in
   order of appearance. Story PRs into ``integration/*`` have no GitHub closing
   link, hence text rules instead of ``closingIssuesReferences`` (D-22).
2. ``fetch_issues``: ``GET issue`` for each number, in order. The cap is
   applied before this, so a linked PR uses one of the 5 slots (DF-18, the spec
   order read literally). Skipped without failing the run, each with a
   ``warn`` event: a PR (``pull_request``); a deleted, transferred or hidden
   issue, 404, 410 or 301 (``not_found``); a 403 (``permission``, which also sets
   ``issues_unavailable`` for the "issues unavailable (permission)" context
   line). A 401, a rate limit after retries, or a 5xx still propagates.
3. Each body is cut at the first ``Task Checklist`` heading (ATX or setext,
   as GitHub renders it, D-43), inclusive to the end (``strip_task_checklist``,
   the developer's plan is excluded, FR-10),
   then capped at 8,000 estimated tokens with a ``[truncated]`` marker.

Issue titles, labels, and bodies are untrusted repository text. Nothing here
interprets them beyond the regexes in ``context.conventions``; they are kept
verbatim for the prompt builder (S-209) to fence. ``warn`` events carry only
the issue number and a fixed reason, never issue text.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from context.conventions import (
    BRANCH_ISSUE_RE,
    ISSUE_LINK_RE,
    ISSUE_TOKEN_CAP,
    LINE_END_RE,
    MAX_ISSUE_NUMBER,
    MAX_LINKED_ISSUES,
    SETEXT_UNDERLINE_RE,
    TASK_CHECKLIST_RE,
    TASK_CHECKLIST_SETEXT_RE,
    ZERO_WIDTH_RE,
)
from context.tokens import truncate
from github_client import (
    GitHubApiError,
    GitHubClient,
    GitHubNotFound,
    GitHubPermissionDenied,
    PullRequest,
)

__all__ = [
    "SKIP_NOT_FOUND",
    "SKIP_PERMISSION",
    "SKIP_PULL_REQUEST",
    "IssuesContext",
    "LinkedIssue",
    "SkippedIssue",
    "Warn",
    "fetch_issues",
    "linked_issue_numbers",
    "linked_issues",
    "strip_task_checklist",
]

SKIP_PULL_REQUEST = "pull_request"
SKIP_NOT_FOUND = "not_found"
SKIP_PERMISSION = "permission"

# ``RunReporter.warn(message, **data)`` fits; tests pass a recorder.
Warn = Callable[..., Any]

_MAX_DIGITS = len(str(MAX_ISSUE_NUMBER))
# 410 Gone (deleted) and 301 Moved Permanently (transferred to another
# repository; the client never follows redirects, and the new home is outside
# the bound repository anyway).
_GONE = frozenset({301, 410})


@dataclass(frozen=True)
class LinkedIssue:
    """An issue as the prompt receives it.

    ``body`` is checklist-stripped and capped (``truncated``); ``stripped_body``
    is checklist-stripped only, for spec resolution and ``Spec §`` citations.
    """

    number: int
    title: str
    labels: tuple[str, ...]
    body: str
    stripped_body: str
    checklist_stripped: bool
    truncated: bool


@dataclass(frozen=True)
class SkippedIssue:
    number: int
    reason: str  # SKIP_PULL_REQUEST | SKIP_NOT_FOUND | SKIP_PERMISSION


@dataclass(frozen=True)
class IssuesContext:
    numbers: tuple[int, ...]  # the linked numbers, after dedupe and the cap
    issues: tuple[LinkedIssue, ...]
    skipped: tuple[SkippedIssue, ...]
    issues_unavailable: bool  # at least one issue was skipped on a 403


def _to_number(digits: str) -> int | None:
    """The issue number, or ``None`` for 0 or one the client would refuse.

    Checked on the digit string first: ``int()`` of a very long digit string
    raises ``ValueError`` (the int max-str-digits limit).
    """
    digits = digits.lstrip("0")
    if not digits or len(digits) > _MAX_DIGITS:
        return None
    number = int(digits)
    return number if number <= MAX_ISSUE_NUMBER else None


def linked_issue_numbers(body: str, head_ref: str) -> tuple[int, ...]:
    """Body links in order, then the branch number; deduped; first 5."""
    found: list[int] = []
    for match in ISSUE_LINK_RE.finditer(body):
        number = _to_number(match.group(3))
        if number is not None:
            found.append(number)
    branch = BRANCH_ISSUE_RE.match(head_ref)
    if branch is not None:
        number = _to_number(branch.group(1))
        if number is not None:
            found.append(number)
    return tuple(dict.fromkeys(found))[:MAX_LINKED_ISSUES]


def _lines(body: str) -> list[tuple[int, str]]:
    """``(offset, line)`` pairs, split on ``\\r\\n``, ``\\r`` or ``\\n``, endings dropped."""
    lines: list[tuple[int, str]] = []
    start = 0
    for end in LINE_END_RE.finditer(body):
        lines.append((start, body[start : end.start()]))
        start = end.end()
    lines.append((start, body[start:]))
    return lines


def strip_task_checklist(body: str) -> str:
    """``body`` up to the first ``Task Checklist`` heading line, exclusive.

    Line-based: lines end at ``\\r\\n``, ``\\r`` or ``\\n``, and zero-width
    characters are removed from a line before matching. A heading is an ATX line
    (``TASK_CHECKLIST_RE``) or a setext text line followed by its underline, the
    cut starting at the text line (D-43). Case-sensitive. Blockquotes, HTML and
    bold lines are not headings. A matching line inside a code fence also cuts
    (EC-13). With no match the body is returned unchanged.
    """
    lines = [(offset, ZERO_WIDTH_RE.sub("", line)) for offset, line in _lines(body)]
    for k, (offset, line) in enumerate(lines):
        if TASK_CHECKLIST_RE.fullmatch(line):
            return body[:offset]
        if (
            k + 1 < len(lines)
            and TASK_CHECKLIST_SETEXT_RE.fullmatch(line)
            and SETEXT_UNDERLINE_RE.fullmatch(lines[k + 1][1])
        ):
            return body[:offset]
    return body


def _warn_skip(warn: Warn | None, number: int, reason: str) -> None:
    if warn is not None:
        warn("linked issue skipped", issue=number, reason=reason)


def fetch_issues(
    client: GitHubClient, numbers: Iterable[int], *, warn: Warn | None = None
) -> IssuesContext:
    """``GET issue`` for each number; skip PRs, gone issues, and 403 (see module doc)."""
    numbers = tuple(numbers)
    issues: list[LinkedIssue] = []
    skipped: list[SkippedIssue] = []
    unavailable = False
    for number in numbers:
        reason: str | None = None
        try:
            raw = client.get_issue(number)
        except GitHubNotFound:
            reason = SKIP_NOT_FOUND
        except GitHubPermissionDenied as exc:
            if exc.status != 403:
                raise
            reason = SKIP_PERMISSION
            unavailable = True
        except GitHubApiError as exc:
            if exc.status not in _GONE:
                raise
            reason = SKIP_NOT_FOUND
        else:
            if raw.is_pull_request:
                reason = SKIP_PULL_REQUEST
        if reason is not None:
            skipped.append(SkippedIssue(number, reason))
            _warn_skip(warn, number, reason)
            continue
        stripped = strip_task_checklist(raw.body)
        body, truncated = truncate(stripped, ISSUE_TOKEN_CAP)
        issues.append(
            LinkedIssue(
                number=number,
                title=raw.title,
                labels=raw.labels,
                body=body,
                stripped_body=stripped,
                checklist_stripped=stripped != raw.body,
                truncated=truncated,
            )
        )
    return IssuesContext(numbers, tuple(issues), tuple(skipped), unavailable)


def linked_issues(
    client: GitHubClient, pull: PullRequest, *, warn: Warn | None = None
) -> IssuesContext:
    """The PR's linked issues: ``linked_issue_numbers`` then ``fetch_issues``."""
    numbers = linked_issue_numbers(pull.body, pull.head_ref)
    return fetch_issues(client, numbers, warn=warn)
