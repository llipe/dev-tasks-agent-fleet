"""
S-207 AC2 — the developer's task checklist is cut from each issue body
(TC-207-07..09; spec §8.3 step 2, D-23, FR-10).

The cut is the first ``Task Checklist`` heading line (case-sensitive),
inclusive, to the end of the body: ``#{1,6}\\s+Task Checklist\\s*`` and, per
planner decision D-43, the other forms GitHub renders as that heading
(indentation, closing sequence, setext, whitespace and zero-width variants;
see ``test_context_hostile_inputs``). Matching is line by line, so a heading
inside a code fence also cuts (EC-13).
"""

from __future__ import annotations

import pytest

from context.issues import fetch_issues, strip_task_checklist
from context.spec import resolve_specs
from github_client import GitHubClient
from tests.helpers.github_stub import StubTransport, json_response, text_response

ABOVE = "Intent paragraph.\n\n- [ ] AC one\n\n"
BELOW = "\n- [ ] 1.1 write tests\n- [ ] 1.2 implement\n"
HEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d"


# -- TC-207-07: cut --------------------------------------------------------


@pytest.mark.parametrize(
    "heading",
    [
        "## Task Checklist",
        "# Task Checklist",
        "###### Task Checklist  ",
        "### Task Checklist\t",
        "##\tTask Checklist",
        "## Task Checklist\r",
    ],
)
def test_cut_at_the_heading_inclusive_to_the_end(heading):
    body = ABOVE + heading + "\n" + BELOW
    out = strip_task_checklist(body)
    assert out == ABOVE
    assert body.startswith(out)


def test_cut_at_a_final_heading_without_newline():
    assert strip_task_checklist(ABOVE + "## Task Checklist") == ABOVE


def test_cut_at_the_first_line():
    assert strip_task_checklist("## Task Checklist\n- [ ] x\n") == ""


def test_crlf_body_is_cut_and_the_kept_part_is_unchanged():
    body = "Intent.\r\n\r\n## Task Checklist\r\n- [ ] 1.1\r\n"
    assert strip_task_checklist(body) == "Intent.\r\n\r\n"


@pytest.mark.parametrize("eol", ["\n", "\r\n", "\r"])
def test_every_line_ending_cuts_and_keeps_the_part_above(eol):
    body = eol.join(["Intent.", "", "## Task Checklist", "- [ ] 1.1", ""])
    assert strip_task_checklist(body) == "Intent." + eol + eol


def test_mixed_line_endings_cut_at_the_first_heading():
    body = "Intent.\r\nmore\r\rTask Checklist\n---\r- [ ] 1.1\n"
    assert strip_task_checklist(body) == "Intent.\r\nmore\r\r"


def test_a_heading_inside_a_code_fence_also_cuts():
    """EC-13 pinned: the match is line-based, fences are not parsed."""
    body = "Intent.\n```md\n## Task Checklist\n```\nafter\n"
    assert strip_task_checklist(body) == "Intent.\n```md\n"


# -- TC-207-08: not cut ------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "## task checklist",  # lowercase: headings are case-sensitive in the template
        "## TASK CHECKLIST",
        "## Task Checklist (v2)",
        "##Task Checklist",
        "####### Task Checklist",
        "Task Checklist",
        "  text ## Task Checklist",
        "## Task Checklists",
        "## My Task Checklist",
    ],
)
def test_near_misses_are_not_cut(line):
    body = ABOVE + line + "\n" + BELOW
    assert strip_task_checklist(body) == body


def test_heading_split_across_lines_is_not_a_heading():
    body = "Intent.\n##\nTask Checklist\nrest\n"
    assert strip_task_checklist(body) == body


def test_only_the_first_matching_heading_cuts():
    body = ABOVE + "## Task Checklist\nfirst\n## Task Checklist\nsecond\n"
    assert strip_task_checklist(body) == ABOVE


def test_body_without_checklist_is_unchanged():
    assert strip_task_checklist(ABOVE) == ABOVE
    assert strip_task_checklist("") == ""


# -- TC-207-09: strip before cap and before spec citation extraction --------


def test_checklist_content_never_reaches_any_returned_field():
    sentinel = "SENTINEL-7f3a"
    body = (
        "Intent only.\n\n## Task Checklist\n"
        f"- [ ] {sentinel} see Spec §9 and workstream/specification-prd-secret.md\n"
        + ("filler line\n" * 5_000)
    )
    issue_json = {
        "number": 5,
        "title": "[PRD-real] Story S-9: x",
        "body": body,
        "labels": [{"name": "prd:real"}],
    }
    spec = "# Spec\n## 1. One\none\n## 9. Nine\nnine body\n"
    stub = StubTransport(
        {
            ("GET", "/repos/acme/widgets/issues/5"): json_response(issue_json),
            (
                "GET",
                "/repos/acme/widgets/contents/workstream/specification-prd-real.md",
            ): text_response(spec),
        }
    )
    client = GitHubClient("ghs_t", "acme", "widgets", 42, transport=stub, sleep=lambda _s: None)
    ctx = fetch_issues(client, (5,))
    (issue,) = ctx.issues
    assert issue.checklist_stripped is True
    assert issue.truncated is False  # stripped first, so the filler never counts
    for value in (issue.title, issue.body, issue.stripped_body, *issue.labels):
        assert sentinel not in value
    specs = resolve_specs(client, ctx.issues, HEAD, reviewed_paths=(), max_context_tokens=20_000)
    # The path below the cut is never tried; the title rule resolves instead.
    assert [c.path for c in stub.calls][-1].endswith("specification-prd-real.md")
    assert all("specification-prd-secret" not in c.path for c in stub.calls)
    # "Spec §9" below the cut is not a citation.
    assert specs.citations == ()
