"""
PRD v1.4 FR-8 — spec documents the selection call picks (FR-32).

They are read at the head SHA after the rule-based specs, deduplicated, and
share the 30% spec cap with them. A pick that is gone (404) is skipped with a
warning; it never fails the run.
"""

from __future__ import annotations

from urllib.parse import quote

from context.issues import LinkedIssue
from context.spec import resolve_specs, spec_cap
from github_client import GitHubClient
from tests.helpers.github_stub import StubTransport, text_response

HEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d"
PREFIX = "/repos/acme/widgets/contents/"


def _client(routes: dict[str, str]) -> tuple[GitHubClient, StubTransport]:
    stub = StubTransport(default=text_response("", status=404))
    for path, text in routes.items():
        encoded = "/".join(quote(s, safe="") for s in path.split("/"))
        stub.add(("GET", PREFIX + encoded, (("ref", HEAD),)), text_response(text))
    return GitHubClient("ghs_x", "acme", "widgets", 42, transport=stub, sleep=lambda s: None), stub


def _issue(title: str = "[PRD-gift] Story S-1: x") -> LinkedIssue:
    return LinkedIssue(1, title, (), "", "", False, False)


def test_selected_specs_follow_the_rule_based_one():
    rule = "workstream/specification-prd-gift.md"
    picked = "docs/requirements/prd-gift-cards.md"
    client, _ = _client({rule: "# Spec\n", picked: "# PRD\n"})
    ctx = resolve_specs(
        client,
        [_issue()],
        HEAD,
        reviewed_paths=(),
        max_context_tokens=100_000,
        extra_paths=(picked, rule),
    )
    assert [s.path for s in ctx.specs] == [rule, picked]
    assert ctx.specs[1].issue == 0


def test_selected_specs_without_linked_issues():
    picked = "docs/design.md"
    client, _ = _client({picked: "# Design\n"})
    ctx = resolve_specs(
        client, [], HEAD, reviewed_paths=(), max_context_tokens=100_000, extra_paths=(picked,)
    )
    assert [s.path for s in ctx.specs] == [picked]


def test_a_missing_pick_is_skipped_with_a_warning():
    warnings: list[tuple[str, dict]] = []
    client, _ = _client({})
    ctx = resolve_specs(
        client,
        [],
        HEAD,
        reviewed_paths=(),
        max_context_tokens=100_000,
        warn=lambda m, **d: warnings.append((m, d)),
        extra_paths=("docs/gone.md",),
    )
    assert ctx.specs == ()
    assert warnings == [("spec not found", {"path": "docs/gone.md"})]


def test_picked_specs_share_the_spec_cap():
    a, b = "docs/a.md", "docs/b.md"
    big = "# A\n" + "word " * 200_000
    client, _ = _client({a: big, b: big})
    budget = 100_000
    ctx = resolve_specs(
        client, [], HEAD, reviewed_paths=(), max_context_tokens=budget, extra_paths=(a, b)
    )
    from context.tokens import estimate

    assert sum(estimate(s.text) for s in ctx.specs) <= spec_cap(budget)


def test_each_path_is_read_once():
    rule = "workstream/specification-prd-gift.md"
    client, stub = _client({rule: "# Spec\n"})
    resolve_specs(
        client,
        [_issue(), _issue()],
        HEAD,
        reviewed_paths=(),
        max_context_tokens=100_000,
        extra_paths=(rule, rule),
    )
    assert len(stub.calls) == 1
