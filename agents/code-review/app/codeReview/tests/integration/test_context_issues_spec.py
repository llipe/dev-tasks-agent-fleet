"""
S-207 L2 — linked issue and spec on the recorded ``issue-315`` fixture
(TC-207-22, AC-6).

PR #330 (``story/S-170-webhook-routing`` into an ``integration/*`` branch,
body ``Closes #315``) links issue #315. The real ``GitHubClient`` reads the PR,
the issue, and the spec over ``StubTransport``. The issue reaches the prompt
input with its title and labels and without its ``## Task Checklist``; the
title rule resolves ``workstream/specification-prd-webhook-triggers.md`` at the
head SHA, and its §8.1 survives trimming.
"""

from __future__ import annotations

import json

from context.issues import linked_issues
from context.spec import resolve_specs, spec_cap
from context.tokens import estimate
from github_client import GitHubClient
from tests.helpers.github_stub import FIXTURES, load_fixture

FIXTURE = "issue-315"
SPEC_PATH = "workstream/specification-prd-webhook-triggers.md"
SPEC_TEXT = (FIXTURES / FIXTURE / "specification-prd-webhook-triggers.md").read_text()
RAW_BODY = json.loads((FIXTURES / FIXTURE / "issue_315.json").read_text())["body"]
SECTION_8_1 = "### 8.1 Routing engine (pure, bounded)"
REVIEWED = ("panel/lib/domain/webhook-routing.ts", "panel/tests/unit/webhook-routing.test.ts")


def _client(stub) -> GitHubClient:
    return GitHubClient(
        "ghs_fixture", "llipe", "dev-tasks-agent-fleet", 330, transport=stub, sleep=lambda _s: None
    )


def _run(max_context_tokens: int):
    stub = load_fixture(FIXTURE)
    client = _client(stub)
    pull = client.get_pull()
    issues = linked_issues(client, pull)
    specs = resolve_specs(
        client,
        issues.issues,
        pull.head_sha,
        reviewed_paths=REVIEWED,
        max_context_tokens=max_context_tokens,
    )
    return stub, pull, issues, specs


def test_issue_315_is_linked_without_its_task_checklist():
    stub, _pull, ctx, _specs = _run(150_000)
    assert ctx.numbers == (315,)  # "llipe/other-repo#12" is ignored
    assert ctx.issues_unavailable is False and ctx.skipped == ()
    (issue,) = ctx.issues
    assert issue.title == (
        "[PRD-webhook-triggers] Story S-170: pure routing engine + safe condition language"
        " + bot guard"
    )
    assert "prd:webhook-triggers" in issue.labels
    assert issue.checklist_stripped is True
    assert "## Task Checklist" in RAW_BODY
    assert "Task Checklist" not in issue.body
    assert "6.1 `[T]`" not in issue.body and "verifier` audit" not in issue.body
    assert "Spec §8.1" in issue.body
    assert RAW_BODY.startswith(issue.body)


def test_spec_resolves_by_title_at_the_head_sha_and_is_whole_within_budget():
    stub, pull, _ctx, specs = _run(150_000)
    spec = specs.spec
    assert spec is not None
    assert spec.path == SPEC_PATH and spec.issue == 315
    assert spec.text == SPEC_TEXT
    assert (spec.trimmed, spec.truncated) == (False, False)
    (call,) = [c for c in stub.calls if "/contents/" in c.path]
    assert call.path.endswith("/contents/" + SPEC_PATH)
    assert call.params == {"ref": pull.head_sha}
    assert SECTION_8_1 in spec.text


def test_over_budget_spec_keeps_the_outline_and_section_8_1():
    budget = 20_000  # 30% = 6,000 tokens, below the fixture spec's size
    assert estimate(SPEC_TEXT) > spec_cap(budget)
    _stub, _pull, _ctx, specs = _run(budget)
    spec = specs.spec
    assert spec is not None
    assert spec.trimmed is True and spec.truncated is False
    assert estimate(spec.text) <= spec_cap(budget)
    assert specs.citations == ("8.1",) and specs.story_ids == ("S-170",)
    # §8.1 is kept whole: heading and body.
    start = SPEC_TEXT.index(SECTION_8_1)
    end = SPEC_TEXT.index("### 8.2 Route resolution")
    assert SPEC_TEXT[start:end] in spec.text
    # The outline: every heading line outside code fences.
    for heading in ("# Specification — Webhook Triggers", "## 13. Error Handling & Logging"):
        assert heading in spec.text
    # A section neither cited nor naming S-170 or a reviewed path is dropped.
    assert "Agent: `getAgentById`, must be enabled" not in spec.text
