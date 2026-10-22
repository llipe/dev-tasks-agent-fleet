"""
S-207 hostile-input probes (qa-engineer pass; SN-02, SN-04, SN-10, EC-10..15).

Issue bodies, titles, labels, the PR body, and the spec at ``head_sha`` are
untrusted repository text. This module probes the S-207 context readers with
inputs the plan-level cases (TC-207-*) do not enumerate:

- FR-10: can any part of the developer's ``## Task Checklist`` reach a
  returned field (body, stripped body, title, labels, citations, story IDs,
  spec requests) through Markdown or Unicode tricks;
- regex cost on hostile bodies (time-bounded);
- cross-repository link forms (never fetched);
- spec path traversal through the title, label, and body rules;
- dedupe and the 5 cap with PRs and 404/410s mixed; the 30% cap with several
  specs; which HTTP statuses degrade and which propagate.

Tests marked ``xfail(strict=True)`` pin a defect that needs a source change
(reported to ``developer``); they flip to a hard failure once fixed, so the
marker is removed deliberately. Tests named ``*_spec_literal`` pin behavior
that follows the spec §8.3 regex literally but leaves an FR-10 gap; they are
routed to ``product-engineer`` as spec findings, not source defects.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest

from context.issues import (
    LinkedIssue,
    fetch_issues,
    linked_issue_numbers,
    linked_issues,
    strip_task_checklist,
)
from context.spec import _split_sections, resolve_specs, spec_candidates, spec_cap, trim_spec
from context.tokens import estimate
from github_client import GitHubApiError, GitHubClient, GitHubPermissionDenied, PullRequest
from tests.helpers.github_stub import StubTransport, json_response, text_response

REPO = "/repos/acme/widgets"
ISSUES = f"{REPO}/issues"
CONTENTS = f"{REPO}/contents/"
HEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d"
SENTINEL = "SENTINEL-c4e9"
ABOVE = "Intent paragraph.\n\n"
BELOW = f"\n- [ ] 1.1 {SENTINEL} see Spec §9 and workstream/specification-prd-secret.md\n"

# GitHub caps PR and issue bodies at 65,536 characters.
GITHUB_BODY_MAX = 65_536


def _client(stub: StubTransport) -> GitHubClient:
    return GitHubClient("ghs_test", "acme", "widgets", 42, transport=stub, sleep=lambda _s: None)


def _pull(body: str = "", head_ref: str = "feature/x") -> PullRequest:
    return PullRequest(42, "open", False, False, "t", body, HEAD, head_ref, "a" * 40, "main")


def _issue_json(number: int, *, title: str = "An issue", body: str = "Body", **extra) -> dict:
    return {"number": number, "title": title, "body": body, "labels": [], **extra}


def _issue(
    number: int = 1, *, title: str = "An issue", body: str = "", labels: tuple[str, ...] = ()
) -> LinkedIssue:
    return LinkedIssue(number, title, labels, body, body, False, False)


# A spec well over any share used here, with numbered sections and S-170.
SPEC = (
    "# Spec\n## 1. Intro\n"
    + ("lorem ipsum dolor sit amet " * 40 + "\n")
    + "## 8. Logic\n### 8.1 Routing\nrouting body S-170\n### 8.10 Ten\nten\n## 9. Nine\nnine\n"
)


def _best_of(fn: Callable[[], object], runs: int = 3) -> float:
    best = float("inf")
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best


def _scales_linearly(make: Callable[[int], Callable[[], object]], n: int) -> bool:
    """Linear-ish growth from ``n`` to ``4n``: fast in absolute terms, or ratio < 8.

    Linear work grows ~4x and quadratic ~16x; the absolute floor keeps a
    fixed implementation (microseconds, noisy ratios) from flaking.
    """
    small = _best_of(make(n))
    large = _best_of(make(4 * n))
    return large < 0.05 or large / max(small, 1e-6) < 8


# ---------------------------------------------------------------------------
# FR-10: the checklist never reaches a returned field
# ---------------------------------------------------------------------------


def _all_returned_text(body: str, title: str = "[PRD-real] Story S-9: t") -> list[str]:
    """Every string S-207 returns for one issue with ``body``, plus spec requests."""
    stub = StubTransport(
        {
            ("GET", f"{ISSUES}/5"): json_response(
                {"number": 5, "title": title, "body": body, "labels": [{"name": "prd:real"}]}
            ),
        },
        default=text_response("# Spec\n## 9. Nine\nnine\n"),
    )
    client = _client(stub)
    ctx = fetch_issues(client, (5,))
    (issue,) = ctx.issues
    specs = resolve_specs(client, ctx.issues, HEAD, reviewed_paths=(), max_context_tokens=20_000)
    return [
        issue.title,
        issue.body,
        issue.stripped_body,
        *issue.labels,
        *specs.citations,
        *specs.story_ids,
        *(s.path for s in specs.specs),
        *(c.path for c in stub.calls),
    ]


@pytest.mark.parametrize(
    "heading",
    [
        "## Task Checklist",
        "## Task Checklist\r",  # CRLF
        "## Task Checklist",  # NBSP after the hashes: Python \s matches, so it cuts
        "## Task Checklist ",
        "## Task Checklist\x0b",
    ],
)
def test_checklist_variants_that_cut_leak_nothing(heading):
    body = ABOVE + heading + "\n" + BELOW
    for value in _all_returned_text(body):
        assert SENTINEL not in value
        assert "specification-prd-secret" not in value
        assert value != "9"  # the "Spec §9" below the cut is no citation


def test_second_checklist_heading_after_the_first_is_cut_too():
    body = ABOVE + "## Task Checklist\nfirst\n" + ABOVE + "## Task Checklist" + BELOW
    assert strip_task_checklist(body) == ABOVE
    assert all(SENTINEL not in v for v in _all_returned_text(body))


def test_near_miss_before_the_real_heading_does_not_shield_the_checklist():
    body = ABOVE + "## task checklist\nnote\n## Task Checklist\n" + BELOW
    assert strip_task_checklist(body) == ABOVE + "## task checklist\nnote\n"
    assert all(SENTINEL not in v for v in _all_returned_text(body))


def test_checklist_text_in_the_title_is_only_the_title():
    """The title is never cut; a title is not part of the developer's plan."""
    values = _all_returned_text(ABOVE + "## Task Checklist" + BELOW, title="## Task Checklist")
    assert values[0] == "## Task Checklist"
    assert all(SENTINEL not in v for v in values)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT (FR-10): strip_task_checklist splits on '\\n' only. A body with "
        "CR-only line endings (CommonMark line ending; GitHub renders the heading) "
        "is one line, never matches, and the whole checklist reaches body, "
        "stripped_body, citations, and the spec rule (a) request. Fix in "
        "context/issues.py (split on \\r\\n|\\r|\\n)."
    ),
)
def test_cr_only_line_endings_cut_the_checklist():
    body = "Intent.\r\r## Task Checklist\r" + BELOW.replace("\n", "\r")
    assert strip_task_checklist(body) == "Intent.\r\r"
    assert all(SENTINEL not in v for v in _all_returned_text(body))


def test_cr_only_line_endings_currently_leak_through_every_field():
    """Evidence for the defect above: the leak reaches the spec request too."""
    body = "Intent.\r\r## Task Checklist\r" + BELOW.replace("\n", "\r")
    values = _all_returned_text(body)
    assert any(SENTINEL in v for v in values)
    assert any("specification-prd-secret" in v for v in values)


@pytest.mark.parametrize(
    "heading",
    [
        "   ## Task Checklist",  # indented 1-3 spaces: still an ATX heading in CommonMark
        "## Task Checklist ##",  # closing sequence: still the heading "Task Checklist"
        "Task Checklist\n--------------",  # setext H2
        "Task Checklist\n==============",  # setext H1
        "> ## Task Checklist",  # heading inside a blockquote
        "<h2>Task Checklist</h2>",  # raw HTML heading
        "## **Task Checklist**",
        "## Task  Checklist",  # two spaces render the same
        "## Task Checklist",  # NBSP between the words
        "## Task​Checklist",  # zero-width space
        "​## Task Checklist",
        "﻿## Task Checklist",  # BOM
    ],
)
def test_rendered_checklist_headings_outside_the_regex_are_not_cut_spec_literal(heading):
    """SPEC GAP (route to product-engineer): spec §8.3 step 2 defines the cut as
    ``^#{1,6}\\s+Task Checklist\\s*$`` and the implementation follows it, so these
    forms, which GitHub renders as a "Task Checklist" heading, are kept. The
    dev-tasks ``plan`` skill only writes ``## Task Checklist``, so the gap needs a
    hand-edited or hostile issue body to leak."""
    body = ABOVE + heading + "\n" + BELOW
    assert strip_task_checklist(body) == body


# ---------------------------------------------------------------------------
# Regex cost on hostile bodies
# ---------------------------------------------------------------------------

_LINEAR_BODIES: dict[str, str] = {
    "many keywords": "fixes " * (GITHUB_BODY_MAX // 6),
    "many hashes": "closes " + "#" * GITHUB_BODY_MAX,
    "huge number": "closes #" + "9" * GITHUB_BODY_MAX + "a",
    "huge number then link": "closes #" + "1" * GITHUB_BODY_MAX + " closes #3",
    "colon and tabs": ("resolved" + " \t" * 40 + ":") * (GITHUB_BODY_MAX // 90),
    "hash lines": "#\n" * (GITHUB_BODY_MAX // 2),
    "checklist near misses": "## Task Checklistx\n" * (GITHUB_BODY_MAX // 19),
    "long heading line": "## " + " " * GITHUB_BODY_MAX + "Task Checklist x",
    "citations": "Spec §" + "1." * (GITHUB_BODY_MAX // 2),
    "spec paths": "workstream/specification-" + "a" * GITHUB_BODY_MAX,
}


@pytest.mark.parametrize("name", sorted(_LINEAR_BODIES))
def test_hostile_issue_and_pr_bodies_are_processed_quickly(name):
    body = _LINEAR_BODIES[name]
    stub = StubTransport(
        {("GET", f"{ISSUES}/3"): json_response(_issue_json(3, body=body))},
        default=json_response({"message": "Not Found"}, 404),
    )
    client = _client(stub)
    start = time.perf_counter()
    numbers = linked_issue_numbers(body, "issue/" + "7" * 1_000 + "-x")
    strip_task_checklist(body)
    ctx = fetch_issues(client, (3,))
    resolve_specs(client, ctx.issues, HEAD, reviewed_paths=(), max_context_tokens=20_000)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"{name}: {elapsed:.2f}s"
    assert len(numbers) <= 5


def test_hostile_spec_outline_is_trimmed_quickly():
    spec = "".join(f"{'#' * (1 + i % 6)} {i}.{i % 7} h\nx\n" for i in range(20_000))
    spec += "```\n" * 2_000 + "# " + "1." * 10_000 + "x\n"
    start = time.perf_counter()
    text, trimmed, _ = trim_spec(
        spec, citations=("1", "2.3"), story_ids=("S-1",), reviewed_paths=("a.py",), cap_tokens=500
    )
    assert time.perf_counter() - start < 2.0
    assert trimmed and estimate(text) <= 500


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT (DoS): ISSUE_LINK_RE `\\s*:?\\s+` backtracks quadratically over a "
        "whitespace run after a closing keyword that is not followed by '#'. "
        "'closes' + 65,536 spaces (GitHub's PR body maximum) took ~3.4 s locally. "
        "Fix in context/conventions.py with an equivalent linear form, e.g. "
        "`(?:\\s*:\\s+|\\s+)#` (same language)."
    ),
)
def test_link_regex_is_linear_on_whitespace_runs():
    assert _scales_linearly(lambda n: lambda: linked_issue_numbers("closes" + " " * n, ""), 4_000)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT (DoS): context/spec.py _HEADING_RE `(?:[ \\t]+(.*?))?[ \\t]*\\r?` "
        "is quadratic on a heading line with a long inner whitespace run. "
        "'# x' + 65,536 spaces + 'y' took ~24 s locally; the spec at head_sha is "
        "PR-author controlled and has no size limit, and trim_spec runs whenever "
        "the spec is over its cap. Fix: match greedily and rstrip the title."
    ),
)
def test_spec_heading_split_is_linear_on_whitespace_runs():
    assert _scales_linearly(lambda n: lambda: _split_sections("# x" + " " * n + "y\n"), 2_000)


# ---------------------------------------------------------------------------
# Cross-repository link forms are never fetched (SN-02, EC-10)
# ---------------------------------------------------------------------------

_CROSS_REPO = (
    "closes other/repo#11\n"
    "fixes other/widgets#12\n"
    "resolves acme/other#13\n"
    "closes https://github.com/other/repo/issues/14\n"
    "closes https://github.com/acme/widgets/issues/15\n"  # full URL: not linked (EC-10)
    "closes github.com/other/repo/issues/16\n"
    "fixes GH-17\n"
    "closes other/repo #18x\n"
    "closes [#19](https://github.com/other/repo/issues/19)\n"
    "closes\n#20\n"  # a newline is whitespace: links #20 in the bound repository
)


def test_cross_repo_link_forms_are_never_fetched():
    stub = StubTransport(default=json_response(_issue_json(20)))
    ctx = linked_issues(_client(stub), _pull(_CROSS_REPO))
    assert ctx.numbers == (20,)
    assert [c.path for c in stub.calls] == [f"{ISSUES}/20"]
    assert all(c.url.startswith("https://api.github.com/repos/acme/widgets/") for c in stub.calls)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT (low): ISSUE_LINK_RE and BRANCH_ISSUE_RE use Unicode `\\d` and "
        "IGNORECASE folding, so non-ASCII digits ('#\\u0663' -> 3, '#\\uff15' -> 5, "
        "'issue/\\u0664-x' -> 4) and 'clo\\u017fes' (long s) link issues GitHub "
        "does not link. Same repository only. Fix: re.ASCII on both regexes."
    ),
)
def test_non_ascii_digits_and_case_folds_do_not_link():
    body = "closes #٣ fixes #５ cloſes #6"
    assert linked_issue_numbers(body, "issue/٤-x") == ()


# ---------------------------------------------------------------------------
# Spec path traversal (SN-04, TC-207-16)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "[PRD-..%2F..%2Fetc] t",
        "[PRD-%2e%2e] t",
        "[PRD-..\\..\\etc] t",
        "[PRD-a∕b] t",  # DIVISION SLASH
        "[PRD-a／b] t",  # FULLWIDTH SOLIDUS
        "[PRD-a\x00b] t",
        "[PRD-а] t",  # Cyrillic a
        "[PRD-a\nb] t",
    ],
)
def test_hostile_prd_titles_yield_no_candidate(title):
    assert spec_candidates(_issue(title=title)) == ()


@pytest.mark.parametrize(
    "label",
    ["prd:..%2F..", "prd:%2e%2e", "prd:a\\b", "prd:a∕b", "prd:x\n", " prd:x", "PRD:x"],
)
def test_hostile_prd_labels_yield_no_candidate(label):
    assert spec_candidates(_issue(labels=(label,))) == ()


def test_every_hostile_request_is_one_file_under_workstream_at_head_sha():
    issues = [
        _issue(1, title="[PRD-...] t", labels=("prd:..",)),
        _issue(2, body="../../workstream/specification-a.md/../../../etc/passwd"),
        _issue(3, body="workstream/specification-%2e%2e%2fsecret.md workstream/specification-b.md"),
        _issue(4, body="https://evil.example/workstream/specification-c.md?ref=main"),
        _issue(5, title="[PRD-x?ref=main] t", labels=("prd:y#frag", "prd:z")),
    ]
    stub = StubTransport(default=json_response({"message": "Not Found"}, 404))
    resolve_specs(_client(stub), issues, HEAD, reviewed_paths=(), max_context_tokens=20_000)
    paths = [c.path.removeprefix(CONTENTS) for c in stub.calls]
    assert paths == [
        "workstream/specification-prd-....md",  # name "..." from the title
        "workstream/specification-prd-...md",  # name ".." from the label
        "workstream/specification-a.md",
        "workstream/specification-b.md",
        "workstream/specification-c.md",
        "workstream/specification-prd-z.md",
    ]
    for call in stub.calls:
        assert call.path.startswith(CONTENTS + "workstream/specification-")
        assert call.path.count("/") == CONTENTS.count("/") + 1
        assert call.params == {"ref": HEAD}


# ---------------------------------------------------------------------------
# Dedupe and the 5 cap with PRs and 404/410s mixed (EC-11, EC-12, DF-18)
# ---------------------------------------------------------------------------


def test_dedupe_and_cap_with_prs_and_missing_issues_mixed():
    body = "closes #3 fixes #1 resolves #3 closes #7 fixes #2 closes #9 closes #8 fixes #1"
    stub = StubTransport(
        {
            ("GET", f"{ISSUES}/3"): json_response(_issue_json(3)),
            ("GET", f"{ISSUES}/1"): json_response(_issue_json(1, pull_request={})),
            ("GET", f"{ISSUES}/7"): json_response({"message": "Not Found"}, 404),
            ("GET", f"{ISSUES}/2"): json_response(_issue_json(2)),
            ("GET", f"{ISSUES}/9"): json_response({"message": "Gone"}, 410),
        }
    )
    events: list[tuple[str, dict]] = []
    ctx = linked_issues(
        _client(stub), _pull(body, "issue/4-x"), warn=lambda m, **d: events.append((m, d))
    )
    assert ctx.numbers == (3, 1, 7, 2, 9)  # 8 and the branch's 4 fall outside the cap
    assert [i.number for i in ctx.issues] == [3, 2]
    assert [(s.number, s.reason) for s in ctx.skipped] == [
        (1, "pull_request"),
        (7, "not_found"),
        (9, "not_found"),
    ]
    assert ctx.issues_unavailable is False
    assert [c.path for c in stub.calls] == [f"{ISSUES}/{n}" for n in (3, 1, 7, 2, 9)]
    assert [d["issue"] for _m, d in events] == [1, 7, 9]
    assert all(set(d) == {"issue", "reason"} for _m, d in events)


def test_branch_number_fills_a_slot_freed_by_dedupe():
    body = "closes #1 closes #1 fixes #2 fixes #2 resolves #3 resolves #4"
    assert linked_issue_numbers(body, "issue/5-x") == (1, 2, 3, 4, 5)
    assert linked_issue_numbers(body + " closes #6", "issue/5-x") == (1, 2, 3, 4, 6)


# ---------------------------------------------------------------------------
# Status handling: degrade vs propagate (spec §13, EC-12, EC-24)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [404, 410, 301])
def test_gone_issues_never_surface_through_linked_issues(status):
    stub = StubTransport(
        {
            ("GET", f"{ISSUES}/1"): json_response({"message": "x"}, status),
            ("GET", f"{ISSUES}/2"): json_response(_issue_json(2)),
        }
    )
    ctx = linked_issues(_client(stub), _pull("closes #1 closes #2"))
    assert [i.number for i in ctx.issues] == [2]
    assert ctx.skipped[0].number == 1


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, GitHubPermissionDenied), (500, GitHubApiError), (503, GitHubApiError)],
)
def test_401_and_5xx_propagate_after_earlier_skips(status, error):
    stub = StubTransport(
        {
            ("GET", f"{ISSUES}/1"): json_response({"message": "x"}, 404),
            ("GET", f"{ISSUES}/2"): json_response(_issue_json(2, pull_request={})),
            ("GET", f"{ISSUES}/3"): json_response({"message": "no"}, 403),
            ("GET", f"{ISSUES}/4"): json_response({"message": "boom"}, status),
        }
    )
    with pytest.raises(error) as exc:
        linked_issues(_client(stub), _pull("closes #1 closes #2 closes #3 closes #4"))
    assert exc.value.status == status


@pytest.mark.parametrize("status", [302, 307, 400, 422])
def test_other_statuses_are_not_treated_as_gone(status):
    stub = StubTransport({("GET", f"{ISSUES}/1"): json_response({"message": "x"}, status)})
    with pytest.raises(GitHubApiError):
        fetch_issues(_client(stub), (1,))


# ---------------------------------------------------------------------------
# The 30% cap with several specs (DF-20, EC-15)
# ---------------------------------------------------------------------------


def test_three_specs_with_a_miss_and_a_duplicate_share_the_cap_in_thirds():
    big = SPEC * 200
    stub = StubTransport(
        {
            ("GET", CONTENTS + "workstream/specification-prd-a.md"): text_response(big),
            ("GET", CONTENTS + "workstream/specification-prd-b.md"): text_response(big),
            ("GET", CONTENTS + "workstream/specification-prd-c.md"): text_response(big + big),
        },
        default=json_response({"message": "Not Found"}, 404),
    )
    issues = [
        _issue(1, title="[PRD-a] Story S-170: t", body="Spec §8.1"),
        _issue(2, title="[PRD-gone] u", labels=("prd:b",)),
        _issue(3, labels=("prd:a",)),  # duplicate of issue 1's spec
        _issue(4, body="workstream/specification-prd-c.md"),
    ]
    budget = 20_000
    ctx = resolve_specs(_client(stub), issues, HEAD, reviewed_paths=(), max_context_tokens=budget)
    assert [(s.path, s.issue) for s in ctx.specs] == [
        ("workstream/specification-prd-a.md", 1),
        ("workstream/specification-prd-b.md", 2),
        ("workstream/specification-prd-c.md", 4),
    ]
    assert ctx.misses == ("workstream/specification-prd-gone.md",)
    share = spec_cap(budget) // 3
    assert all(s.trimmed and estimate(s.text) <= share for s in ctx.specs)
    assert sum(estimate(s.text) for s in ctx.specs) <= spec_cap(budget)
    assert len(stub.calls) == 4  # a, gone, b, c; the duplicate is not refetched


@pytest.mark.parametrize("budget", [0, 1, 9, 10, 33, 1_000, 200_000])
def test_spec_share_never_exceeds_the_cap_for_any_budget(budget):
    stub = StubTransport(default=text_response(SPEC * 50))
    issues = [_issue(n, title=f"[PRD-s{n}] t") for n in range(1, 6)]
    ctx = resolve_specs(_client(stub), issues, HEAD, reviewed_paths=(), max_context_tokens=budget)
    assert len(ctx.specs) == 5
    assert sum(estimate(s.text) for s in ctx.specs) <= spec_cap(budget)
