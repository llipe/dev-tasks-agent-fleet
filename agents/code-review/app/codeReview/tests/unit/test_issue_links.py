"""
S-207 AC1, AC3, AC6 — linked issues (TC-207-01..06, -10, -21; spec §8.3 step 2, §13).

Links come from the PR body (closing-keyword regex, same repository only) and
the head ref (``issue/<N>-``), deduped and capped at 5 in order of appearance,
body first (D-22). Each is read with ``GET issue``; a PR, a 404/410, or a 403
is skipped without failing the run. A 403 also sets ``issues_unavailable``.
"""

from __future__ import annotations

import pytest

from context.conventions import ISSUE_TOKEN_CAP, MAX_LINKED_ISSUES
from context.issues import IssuesContext, fetch_issues, linked_issue_numbers, linked_issues
from context.tokens import TRUNCATION_MARKER, estimate
from github_client import GitHubApiError, GitHubClient, GitHubPermissionDenied, PullRequest
from tests.helpers.github_stub import StubTransport, json_response

ISSUES = "/repos/acme/widgets/issues"
HEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d"


def _issue(number: int, *, title: str = "An issue", body: str | None = "Body", **extra) -> dict:
    return {"number": number, "title": title, "body": body, "labels": [], **extra}


def _client(stub: StubTransport) -> GitHubClient:
    return GitHubClient("ghs_test", "acme", "widgets", 42, transport=stub, sleep=lambda _s: None)


def _pull(body: str = "", head_ref: str = "feature/x") -> PullRequest:
    return PullRequest(42, "open", False, False, "t", body, HEAD, head_ref, "a" * 40, "main")


def _routes(*issues: dict) -> StubTransport:
    return StubTransport({("GET", f"{ISSUES}/{i['number']}"): json_response(i) for i in issues})


class _Events:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def __call__(self, message: str, **data) -> None:
        self.events.append((message, data))


# -- TC-207-01: closing keywords ---------------------------------------------


@pytest.mark.parametrize(
    "keyword",
    ["close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved"],
)
def test_every_closing_keyword_links(keyword):
    assert linked_issue_numbers(f"{keyword} #7", "main") == (7,)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Closes #1", (1,)),
        ("FIXES #2", (2,)),
        ("Fixes: #3", (3,)),
        ("resolved #3", (3,)),
        ("ReSoLvEs    #9", (9,)),
        ("fix :  #10", (10,)),
        ("Done.\nCloses #11.\n", (11,)),
        ("(fixes #12)", (12,)),
        ("closes\t#13", (13,)),
    ],
)
def test_closing_links_are_case_insensitive_with_optional_colon(body, expected):
    assert linked_issue_numbers(body, "main") == expected


# -- TC-207-02: not linked ---------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "closes owner/repo#4",
        "#5",
        "closes#6",
        "see #7",
        "unclosed #8",
        "fixes #12abc",
        "closes https://github.com/o/r/issues/9",
        "closes:#5",
        "closing #14",
        "fixes # 15",
        "prefixes #16",
        "closes #0",
    ],
)
def test_non_links_are_ignored(body):
    assert linked_issue_numbers(body, "main") == ()


def test_cross_repo_reference_is_ignored_next_to_a_same_repo_link():
    assert linked_issue_numbers("Fixes acme/other#4 and closes #5", "main") == (5,)


def test_issue_numbers_the_client_would_refuse_are_dropped():
    body = "closes #12345678901 closes #" + "9" * 5000 + " closes #3"
    assert linked_issue_numbers(body, "main") == (3,)


# -- TC-207-03: branch rule --------------------------------------------------


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("issue/5-x", (5,)),
        ("issue/05-x", (5,)),
        ("issue/409-linked-issues", (409,)),
        ("issue/5", ()),
        ("feature/issue/5-x", ()),
        ("Issue/5-x", ()),
        ("issue/x-5", ()),
        ("issue/0-x", ()),
        ("story/S-207-issues-spec", ()),
    ],
)
def test_branch_rule(ref, expected):
    assert linked_issue_numbers("", ref) == expected


# -- TC-207-04: order, dedupe, cap ------------------------------------------


def test_body_order_first_then_branch_deduped():
    body = "closes #3, fixes #1, closes #3"
    assert linked_issue_numbers(body, "issue/2-x") == (3, 1, 2)


def test_branch_number_already_in_the_body_is_not_repeated():
    assert linked_issue_numbers("fixes #2", "issue/2-x") == (2,)


def test_six_distinct_links_keep_the_first_five():
    body = " ".join(f"closes #{n}" for n in (10, 11, 12, 13, 14, 15))
    assert linked_issue_numbers(body, "issue/16-x") == (10, 11, 12, 13, 14)
    assert MAX_LINKED_ISSUES == 5


# -- TC-207-05: a linked PR is skipped (DF-18 pinned: cap first, then skip) ---


def test_a_linked_pull_request_is_skipped_and_not_passed():
    stub = _routes(
        _issue(40, pull_request={"url": "https://api.github.com/repos/acme/widgets/pulls/40"}),
        _issue(41),
    )
    events = _Events()
    ctx = fetch_issues(_client(stub), (40, 41), warn=events)
    assert [i.number for i in ctx.issues] == [41]
    assert [(s.number, s.reason) for s in ctx.skipped] == [(40, "pull_request")]
    assert ctx.issues_unavailable is False
    assert events.events == [("linked issue skipped", {"issue": 40, "reason": "pull_request"})]


def test_a_linked_pull_request_uses_one_of_the_five_slots():
    """DF-18, spec order read literally: keep the first 5, then skip PRs."""
    numbers = (1, 2, 3, 4, 5, 6)
    body = " ".join(f"closes #{n}" for n in numbers)
    stub = _routes(_issue(1, pull_request={}), *(_issue(n) for n in numbers[1:]))
    ctx = linked_issues(_client(stub), _pull(body))
    assert ctx.numbers == (1, 2, 3, 4, 5)
    assert [i.number for i in ctx.issues] == [2, 3, 4, 5]
    assert all(c.path != f"{ISSUES}/6" for c in stub.calls)


# -- TC-207-06: a 404/410 issue is skipped (carry-forward 1, DF-13) ----------


@pytest.mark.parametrize(("status", "reason"), [(404, "not_found"), (410, "not_found")])
def test_a_missing_issue_is_skipped_without_failing_or_flagging_permission(status, reason):
    stub = StubTransport(
        {
            ("GET", f"{ISSUES}/7"): json_response({"message": "Not Found"}, status=status),
            ("GET", f"{ISSUES}/8"): json_response(_issue(8)),
        }
    )
    events = _Events()
    ctx = fetch_issues(_client(stub), (7, 8), warn=events)
    assert [i.number for i in ctx.issues] == [8]
    assert [(s.number, s.reason) for s in ctx.skipped] == [(7, reason)]
    assert ctx.issues_unavailable is False
    assert events.events == [("linked issue skipped", {"issue": 7, "reason": reason})]


# -- TC-207-21: 403 → skipped, issues_unavailable (AC6, spec §13) ------------


def test_issue_403_skips_that_issue_and_sets_issues_unavailable():
    stub = StubTransport(
        {
            ("GET", f"{ISSUES}/1"): json_response(_issue(1)),
            ("GET", f"{ISSUES}/2"): json_response({"message": "Resource not accessible"}, 403),
            ("GET", f"{ISSUES}/3"): json_response(_issue(3)),
        }
    )
    events = _Events()
    ctx = fetch_issues(_client(stub), (1, 2, 3), warn=events)
    assert [i.number for i in ctx.issues] == [1, 3]
    assert [(s.number, s.reason) for s in ctx.skipped] == [(2, "permission")]
    assert ctx.issues_unavailable is True
    assert events.events == [("linked issue skipped", {"issue": 2, "reason": "permission"})]


def test_issue_403_is_not_retried():
    stub = StubTransport({("GET", f"{ISSUES}/2"): json_response({"message": "no"}, 403)})
    fetch_issues(_client(stub), (2,))
    assert len(stub.calls) == 1


def test_issue_401_still_fails_the_run():
    """Only 403 degrades (spec §13); a 401 means the token itself is bad."""
    stub = StubTransport({("GET", f"{ISSUES}/2"): json_response({"message": "Bad"}, 401)})
    with pytest.raises(GitHubPermissionDenied):
        fetch_issues(_client(stub), (2,))


def test_issue_rate_limit_after_retries_still_fails_the_run():
    limited = json_response({"message": "API rate limit exceeded"}, 403, {"retry-after": "1"})
    stub = StubTransport({("GET", f"{ISSUES}/2"): limited})
    with pytest.raises(GitHubApiError):
        fetch_issues(_client(stub), (2,))


def test_issue_5xx_still_fails_the_run():
    stub = StubTransport({("GET", f"{ISSUES}/2"): json_response({}, 502)})
    with pytest.raises(GitHubApiError):
        fetch_issues(_client(stub), (2,))


# -- passed fields -----------------------------------------------------------


def test_issue_fields_are_title_labels_and_trimmed_body():
    raw = _issue(
        9,
        title="[PRD-x] Story S-1: thing",
        body="Intent.\n\n## Task Checklist\n- [ ] 1.1 plan\n",
        labels=[{"name": "prd:x"}, {"name": "story"}],
    )
    ctx = fetch_issues(_client(_routes(raw)), (9,))
    (issue,) = ctx.issues
    assert issue.title == "[PRD-x] Story S-1: thing"
    assert issue.labels == ("prd:x", "story")
    assert issue.body == "Intent.\n\n"
    assert issue.checklist_stripped is True
    assert issue.truncated is False


def test_null_body_is_empty():
    ctx = fetch_issues(_client(_routes(_issue(9, body=None))), (9,))
    assert ctx.issues[0].body == ""


def test_no_links_fetches_nothing():
    stub = StubTransport()
    ctx = linked_issues(_client(stub), _pull("No links here.", "feature/x"))
    assert ctx == IssuesContext(numbers=(), issues=(), skipped=(), issues_unavailable=False)
    assert stub.calls == []


def test_linked_issues_reads_body_then_branch():
    stub = _routes(_issue(3), _issue(2))
    ctx = linked_issues(_client(stub), _pull("closes #3", "issue/2-x"))
    assert ctx.numbers == (3, 2)
    assert [c.path for c in stub.calls] == [f"{ISSUES}/3", f"{ISSUES}/2"]


# -- TC-207-10: 8,000-token cap (AC3) ----------------------------------------


def test_body_of_exactly_8000_tokens_is_kept_whole():
    body = "x" * 28_000
    assert estimate(body) == ISSUE_TOKEN_CAP == 8_000
    (issue,) = fetch_issues(_client(_routes(_issue(9, body=body))), (9,)).issues
    assert issue.body == body
    assert issue.truncated is False


def test_body_one_char_over_is_truncated_with_the_marker():
    body = "x" * 28_001
    (issue,) = fetch_issues(_client(_routes(_issue(9, body=body))), (9,)).issues
    assert issue.truncated is True
    assert issue.body.endswith(TRUNCATION_MARKER + "\n")
    assert estimate(issue.body) <= 8_000


def test_long_multiline_body_is_truncated_at_a_line_boundary():
    body = "".join(f"line {i}\n" for i in range(10_000))
    (issue,) = fetch_issues(_client(_routes(_issue(9, body=body))), (9,)).issues
    kept = issue.body[: -len(TRUNCATION_MARKER) - 1]
    assert body.startswith(kept) and kept.endswith("\n")
    assert estimate(issue.body) <= 8_000
