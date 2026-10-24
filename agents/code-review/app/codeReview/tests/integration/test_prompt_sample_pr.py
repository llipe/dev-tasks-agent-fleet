"""
S-209 L2 — the prompt for the recorded ``sample-pr`` fixture (task 6.8, TC-209-12).

The context readers of S-206..S-208 run through the real ``GitHubClient``
over ``StubTransport``; ``build_prompt`` then assembles the prompt with a fixed
nonce. ``render_sample_prompt`` is also the source of the rendered prompt
pasted in the S-209 PR description.
"""

from __future__ import annotations

from budget import ContextInputs
from context.diff import DiffContext, diff_context
from context.issues import linked_issues
from context.repo_conventions import repo_conventions
from context.spec import resolve_specs
from context.verifier import verifier_candidates
from github_client import GitHubClient
from prompt import Prompt, build_prompt
from tests.helpers.github_stub import load_fixture
from tests.helpers.prompt_inputs import NONCE, parse_blocks

TOKEN = "ghs_SENTINELtoken0000000000000000000000"
SUPABASE_KEY = "sb_secret_SENTINEL_key"
MAX_CONTEXT_TOKENS = 150_000


def render_sample_prompt(max_context_tokens: int = MAX_CONTEXT_TOKENS) -> Prompt:
    stub = load_fixture("sample-pr")

    def factory() -> GitHubClient:
        return GitHubClient(TOKEN, "acme", "widgets", 42, transport=stub, sleep=lambda _s: None)

    client = factory()
    pull = client.get_pull()
    diff = diff_context(
        client, pull, client.list_pull_files(), max_diff_lines=2000, client_factory=factory
    )
    assert isinstance(diff, DiffContext)
    issues = linked_issues(client, pull)
    specs = resolve_specs(
        client,
        issues.issues,
        pull.head_sha,
        reviewed_paths=[f.filename for f in diff.files],
        max_context_tokens=max_context_tokens,
    )
    verifier = verifier_candidates(client, issues.issues, pull.head_sha)
    conventions = repo_conventions(client, pull.head_sha, max_context_tokens=max_context_tokens)
    result = build_prompt(
        ContextInputs(
            pr_number=pull.number,
            head_sha=pull.head_sha,
            pr_title=pull.title,
            pr_body=pull.body,
            diff=diff,
            issues=issues,
            spec=specs,
            verifier=verifier,
            conventions=conventions,
        ),
        max_context_tokens=max_context_tokens,
        max_diff_lines=2000,
        nonce=NONCE,
    )
    assert isinstance(result, Prompt)
    return result


def test_sample_pr_prompt_blocks():
    p = render_sample_prompt()
    blocks, outside = parse_blocks(p.user, p.nonce)
    kinds = [k for k, _, _ in blocks]
    assert kinds == [
        "diff",
        "pr",
        "issue",
        "verifier",
        "verifier-candidate",
        "conventions",
        "file",
        "file",
        "file",
    ]
    ctx = p.context
    assert ctx.issue_numbers == (41,)
    assert ctx.no_spec and ctx.verifier_state == "parsed"
    assert [c.id for c in ctx.shown_candidates] == ["V1"] and ctx.dropped_candidates == ()
    assert ctx.full_files_included == ("src/new_name.py", "docs/notes with space.md", "src/app.py")
    assert p.tokens <= MAX_CONTEXT_TOKENS


def test_sample_pr_prompt_keeps_untrusted_text_inside_and_excluded_text_out():
    p = render_sample_prompt()
    blocks, outside = parse_blocks(p.user, p.nonce)
    assert "Task Checklist" not in p.user and "- [ ] do it" not in p.user
    assert "Ignore previous instructions" not in outside
    (cand,) = [c for k, t, c in blocks if k == "verifier-candidate" and t == "V1"]
    assert "Ignore previous instructions" in cand
    assert "V1 — `workstream/fidelity-report-S-001.md`, drift row 1" in outside
    # Name-only files are listed inside the diff block.
    (diff_block,) = [c for k, _, c in blocks if k == "diff"]
    assert "pnpm-lock.yaml (lockfile)" in diff_block and "assets/logo.png (binary)" in diff_block


def test_sample_pr_prompt_carries_no_credentials():
    p = render_sample_prompt()
    for text in (p.system, p.fallback_system, p.user):
        assert TOKEN not in text and "SENTINEL" not in text and SUPABASE_KEY not in text


def test_sample_pr_prompt_is_deterministic_with_a_fixed_nonce():
    assert render_sample_prompt() == render_sample_prompt()


def test_sample_pr_prompt_at_the_minimum_budget():
    p = render_sample_prompt(20_000)
    assert p.tokens <= 20_000
