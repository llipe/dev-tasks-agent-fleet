"""
PRD v1.4 FR-9 — broadened verifier report names (D-64).

Per linked issue: ``fidelity-report-issue-<N>.md`` and, when the head tree lists
one, ``fidelity-report-issue-<N>-<slug>.md``; for each story ID
``[A-Z]{1,4}-\\d+`` in the issue title (``S-170``, ``GC-08``),
``fidelity-report-<ID>.md`` and a listed ``fidelity-report-<ID>-<slug>.md``.
Suffixed names come from the tree listing only, so they cost no blind reads.
Documents the selection call picks as ``verifier_report`` are read after these,
deduplicated. Riel's real names (``llipe/riel#889``) are the fixtures.
"""

from __future__ import annotations

from context.issues import LinkedIssue
from context.verifier import REPORT_PARSED, report_paths, title_story_ids, verifier_candidates
from github_client import GitHubClient
from tests.helpers.github_stub import StubTransport, text_response

HEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d"
PREFIX = "/repos/acme/widgets/contents/"

REPORT = """# Fidelity report

## 4. Drift catalog

| # | Item | Severity | Kind |
|---|------|----------|------|
| 1 | Missing refund path | Critical | Unintended |
"""


def _issue(number: int, title: str) -> LinkedIssue:
    return LinkedIssue(number, title, (), "", "", False, False)


def test_title_story_ids():
    assert title_story_ids("GC-08: gift card compensation") == ("GC-08",)
    assert title_story_ids("[PRD-x] Story S-170: routing") == ("S-170",)
    assert title_story_ids("ABCDE-1 and AB-2 and AB-2") == ("AB-2",)
    assert title_story_ids("lower gc-08") == ()
    assert title_story_ids("A-1 B-2 C-3 D-4 E-5") == ("A-1", "B-2", "C-3")


def test_exact_names_without_a_tree():
    assert report_paths(_issue(889, "GC-08: compensation")) == (
        "workstream/fidelity-report-GC-08.md",
        "workstream/fidelity-report-issue-889.md",
    )


def test_suffixed_names_come_from_the_tree_listing():
    tree = {
        "workstream/fidelity-report-issue-734-staff-auth-contracts.md",
        "workstream/fidelity-report-issue-7345-other.md",
        "workstream/fidelity-report-issue-73-other.md",
        "workstream/fidelity-report-GC-08-gift-card.md",
        "workstream/fidelity-report-GC-080-x.md",
        "workstream/fidelity-report-GC-08-rollup.md",
        "workstream/sub/fidelity-report-issue-734-nested.md",
        "workstream/fidelity-report-issue-734-bad slug.md",
        "docs/fidelity-report-issue-734-elsewhere.md",
    }
    paths = report_paths(_issue(734, "GC-08: compensation"), tree)
    assert paths == (
        "workstream/fidelity-report-GC-08.md",
        "workstream/fidelity-report-GC-08-gift-card.md",
        "workstream/fidelity-report-issue-734.md",
        "workstream/fidelity-report-issue-734-staff-auth-contracts.md",
    )


def test_suffix_matches_are_bounded_per_name():
    tree = {f"workstream/fidelity-report-issue-1-s{k:03d}.md" for k in range(50)}
    paths = report_paths(_issue(1, "chore"), tree)
    assert len(paths) == 1 + 3
    assert paths[1:] == tuple(f"workstream/fidelity-report-issue-1-s{k:03d}.md" for k in range(3))


def _client(routes: dict[str, str]) -> tuple[GitHubClient, StubTransport]:
    from urllib.parse import quote

    stub = StubTransport(default=text_response("", status=404))
    for path, text in routes.items():
        encoded = "/".join(quote(s, safe="") for s in path.split("/"))
        stub.add(("GET", PREFIX + encoded, (("ref", HEAD),)), text_response(text))
    return GitHubClient("ghs_x", "acme", "widgets", 42, transport=stub, sleep=lambda s: None), stub


def test_riel_issue_report_with_a_slug_is_found():
    name = "workstream/fidelity-report-issue-734-staff-auth-contracts.md"
    client, _ = _client({name: REPORT})
    ctx = verifier_candidates(
        client, [_issue(734, "Staff auth contracts")], HEAD, tree_paths={name}
    )
    parsed = [r.path for r in ctx.reports if r.state == REPORT_PARSED]
    assert parsed == [name]
    assert [c.report_path for c in ctx.candidates] == [name]


def test_riel_story_id_report_is_found():
    name = "workstream/fidelity-report-GC-08.md"
    client, _ = _client({name: REPORT})
    ctx = verifier_candidates(client, [_issue(889, "GC-08: compensation")], HEAD)
    assert [r.path for r in ctx.reports if r.state == REPORT_PARSED] == [name]


def test_selected_reports_are_read_after_the_rules_and_deduplicated():
    audit = "workstream/audit-gift-card-compensation-gc08.md"
    rule = "workstream/fidelity-report-issue-889.md"
    client, stub = _client({audit: REPORT, rule: REPORT})
    ctx = verifier_candidates(
        client,
        [_issue(889, "Compensation")],
        HEAD,
        extra_paths=(rule, audit, audit),
    )
    assert [r.path for r in ctx.reports] == [rule, audit]
    assert [c.id for c in ctx.candidates] == ["V1", "V2"]
    assert [c.report_path for c in ctx.candidates] == [rule, audit]
    reads = [c.path for c in stub.calls]
    assert len(reads) == len(set(reads)) == 2


def test_selected_reports_without_linked_issues():
    audit = "workstream/audit-gc08.md"
    client, _ = _client({audit: REPORT})
    ctx = verifier_candidates(client, [], HEAD, extra_paths=(audit,))
    assert [r.path for r in ctx.reports] == [audit]
    assert ctx.reports[0].issue == 0


def test_with_a_tree_a_bare_id_counts_only_when_its_report_is_listed():
    # Verifier DR-02: "UTF-8" and "SHA-256" must not crowd out "GC-08".
    title = "Story S-170: fix UTF-8 and SHA-256 for GC-08"
    tree = {"workstream/fidelity-report-GC-08-gift.md"}
    assert title_story_ids(title, tree) == ("S-170", "GC-08")
    assert report_paths(_issue(5, title), tree) == (
        "workstream/fidelity-report-S-170.md",
        "workstream/fidelity-report-GC-08.md",
        "workstream/fidelity-report-GC-08-gift.md",
        "workstream/fidelity-report-issue-5.md",
    )


def test_with_an_empty_listing_only_story_titles_count():
    assert title_story_ids("Story S-1: GC-08 UTF-8", frozenset()) == ("S-1",)


def test_without_a_tree_every_id_is_read_blind():
    assert title_story_ids("GC-08 UTF-8") == ("GC-08", "UTF-8")
