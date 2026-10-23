"""
S-209 AC2/AC3 — spec §8.4 priority fill and the budget invariant (D-27, D-37).

TC-209-02..08: the mandatory part (instructions + diff) and the optional
blocks a–g, each given ``min(cap, remaining)``, truncated at a line boundary or
omitted and named; full files smallest first; a diff over budget is
``OverBudget`` (PRD FR-6); ``estimate(prompt) <= max_context_tokens`` for
every input, asserted, and ``INTERNAL_ERROR`` on a violation; candidates
dropped for budget are reported, never lost.

The budget counts the whole serialized prompt: the system prompt with the
output schema (the fallback form, the larger of the two the adapter can send),
the preamble, every label and marker line, and the notes.
"""

from __future__ import annotations

import pytest

import budget
from budget import (
    FILL_ORDER,
    PR_TOKEN_CAP,
    BudgetInvariantError,
    ContextData,
    assert_within_budget,
    prompt_tokens,
)
from context.diff import OVER_TOKENS, NameOnlyFile, OverBudget
from context.tokens import TRUNCATION_MARKER, estimate
from prompt import Prompt, build_prompt
from tests.helpers.prompt_inputs import (
    NONCE,
    candidate,
    conventions_ctx,
    diff_ctx,
    file_diff,
    inputs,
    issue,
    issues_ctx,
    parse_blocks,
    report,
    spec,
    spec_ctx,
    verifier_ctx,
)

BIG = 10_000_000


def _text(tokens: int, tag: str = "x") -> str:
    """About ``tokens`` estimated tokens of 34-char lines (plus a newline)."""
    line = (tag * 34)[:34] + "\n"
    return line * max(1, (tokens * 7 // 2) // len(line))


def _build(ins, max_context_tokens: int = BIG, **kw) -> Prompt:
    result = build_prompt(
        ins, max_context_tokens=max_context_tokens, max_diff_lines=2000, nonce=NONCE, **kw
    )
    assert isinstance(result, Prompt), result
    return result


def _ctx(ins, max_context_tokens: int = BIG, **kw) -> ContextData:
    return _build(ins, max_context_tokens, **kw).context


def _mandatory(ins) -> int:
    return _ctx(ins).mandatory_tokens


def _note(ctx: ContextData, block: str, ref: str | None = None):
    found = [n for n in ctx.notes if n.block == block and (ref is None or n.ref == ref)]
    return found


# ---------------------------------------------------------------------------
# Constants and order (TC-209-02)
# ---------------------------------------------------------------------------


def test_fill_order_is_spec_a_to_g():
    assert FILL_ORDER == (
        "pr",
        "verifier-candidate",
        "issue",
        "verifier",
        "spec",
        "conventions",
        "file",
    )
    assert PR_TOKEN_CAP == 4_000


def test_block_tokens_report_every_block_and_sum_to_at_least_the_total():
    ins = inputs(
        issues=issues_ctx(issue(41)),
        specs=spec_ctx(spec()),
        verifier=verifier_ctx(report(candidates=[candidate(1)])),
        conventions=conventions_ctx(),
    )
    p = _build(ins)
    tokens = p.context.block_tokens
    for kind in ("instructions", "diff", *FILL_ORDER):
        assert tokens[kind] > 0, kind
    # Each part is charged separately and ceil is subadditive.
    assert sum(tokens.values()) >= p.context.total_tokens
    assert p.context.total_tokens == prompt_tokens(p) == p.tokens


def test_blocks_render_in_a_fixed_order():
    ins = inputs(
        issues=issues_ctx(issue(41), issue(43)),
        specs=spec_ctx(spec()),
        verifier=verifier_ctx(report(candidates=[candidate(1), candidate(2)])),
        conventions=conventions_ctx(),
        diff=diff_ctx([file_diff("a.py"), file_diff("b.py")]),
    )
    p = _build(ins)
    blocks, _ = parse_blocks(p.user, p.nonce)
    kinds = [k for k, _, _ in blocks]
    assert kinds == [
        "diff",
        "pr",
        "issue",
        "issue",
        "spec",
        "verifier",
        "verifier-candidate",
        "verifier-candidate",
        "conventions",
        "file",
        "file",
    ]


def test_the_total_counts_the_whole_serialized_prompt():
    p = _build(inputs())
    assert p.context.total_tokens == estimate(p.fallback_system) + estimate(p.user)
    # The fallback system prompt carries the schema, so it is the larger form.
    assert p.fallback_system.startswith(p.system)
    assert estimate(p.fallback_system) > estimate(p.system)
    # Markers and labels are charged: the diff block costs more than its text.
    assert p.context.diff_tokens > estimate(inputs().diff.diff_text)


# ---------------------------------------------------------------------------
# Mandatory part and OverBudget (TC-209-04)
# ---------------------------------------------------------------------------


def test_diff_over_budget_is_over_budget_with_the_counts():
    files = [file_diff(f"f{i}.py", diff=_text(3_000, str(i))) for i in range(10)]
    ins = inputs(diff=diff_ctx(files, changed_lines=12_345))
    m = _mandatory(ins)
    assert m > 30_000
    result = build_prompt(ins, max_context_tokens=m - 1, max_diff_lines=2000, nonce=NONCE)
    assert isinstance(result, OverBudget)
    assert result.reason == OVER_TOKENS
    assert result.tokens == m and result.max_context_tokens == m - 1
    assert result.lines == 12_345 and result.files == 10 and result.max_diff_lines == 2000
    assert 0 < result.diff_tokens < m


def test_diff_exactly_at_the_limit_fits_with_every_optional_block_omitted():
    files = [file_diff(f"f{i}.py", head=_text(100), diff=_text(3_000, str(i))) for i in range(10)]
    ins = inputs(
        diff=diff_ctx(files),
        issues=issues_ctx(issue(41)),
        specs=spec_ctx(spec()),
        verifier=verifier_ctx(report(candidates=[candidate(1)])),
        conventions=conventions_ctx(),
    )
    m = _mandatory(ins)
    p = _build(ins, m)
    ctx = p.context
    assert ctx.remaining_tokens == 0 and p.tokens <= m
    assert [k for k, _, _ in parse_blocks(p.user, p.nonce)[0]] == ["diff"]
    assert {n.block for n in ctx.omitted} == {"pr", "issue", "spec", "verifier", "conventions"}
    assert ctx.dropped_candidates == (candidate(1),)
    assert ctx.full_files_included == ()
    assert len(ctx.full_files_dropped) == 10


def test_over_budget_does_not_call_the_sink():
    calls = []
    files = [file_diff("f.py", diff=_text(30_000))]
    result = build_prompt(
        inputs(diff=diff_ctx(files)),
        max_context_tokens=20_000,
        max_diff_lines=2000,
        nonce=NONCE,
        sink=calls.append,
    )
    assert isinstance(result, OverBudget) and calls == []


def test_instructions_alone_over_a_tiny_budget_is_over_budget():
    result = build_prompt(inputs(), max_context_tokens=100, max_diff_lines=2000, nonce=NONCE)
    assert isinstance(result, OverBudget) and result.reason == OVER_TOKENS


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "20000"])
def test_max_context_tokens_must_be_a_positive_int(bad):
    with pytest.raises(ValueError):
        build_prompt(inputs(), max_context_tokens=bad, max_diff_lines=2000, nonce=NONCE)


def test_name_only_files_are_listed_inside_the_diff_block():
    name_only = [NameOnlyFile("pnpm-lock.yaml", "modified", "lockfile")]
    p = _build(inputs(diff=diff_ctx(name_only=name_only)))
    (diff_block,) = [c for k, _, c in parse_blocks(p.user, p.nonce)[0] if k == "diff"]
    assert "pnpm-lock.yaml (lockfile)" in diff_block


def test_a_huge_name_only_list_is_capped():
    name_only = [NameOnlyFile(f"dist/{i:05d}.js", "added", "generated") for i in range(20_000)]
    p = _build(inputs(diff=diff_ctx(name_only=name_only)))
    (diff_block,) = [c for k, _, c in parse_blocks(p.user, p.nonce)[0] if k == "diff"]
    assert (
        estimate(diff_block) <= budget.NAME_ONLY_TOKEN_CAP + estimate(inputs().diff.diff_text) + 50
    )
    assert TRUNCATION_MARKER in diff_block


# ---------------------------------------------------------------------------
# a. PR title and body: min(4,000, R_left) (TC-209-05)
# ---------------------------------------------------------------------------


def test_pr_body_is_capped_at_4000_tokens_with_a_marker():
    p = _build(inputs(body=_text(10_000)))
    (pr,) = [c for k, _, c in parse_blocks(p.user, p.nonce)[0] if k == "pr"]
    assert estimate(pr) <= PR_TOKEN_CAP
    assert pr.endswith(TRUNCATION_MARKER + "\n")
    assert pr.startswith("Title: Add widget sizes\n")
    (note,) = _note(p.context, "pr")
    assert (note.state, note.reason) == ("truncated", "cap")


def test_pr_body_truncated_by_the_remaining_budget_is_named_budget():
    ins = inputs(body=_text(10_000))
    m = _mandatory(ins)
    p = _build(ins, m + 1_000)
    (pr,) = [c for k, _, c in parse_blocks(p.user, p.nonce)[0] if k == "pr"]
    assert estimate(pr) < 1_000
    (note,) = _note(p.context, "pr")
    assert (note.state, note.reason) == ("truncated", "budget")
    assert p.tokens <= m + 1_000


def test_pr_before_files_even_when_a_file_is_smaller():
    ins = inputs(body=_text(3_000), diff=diff_ctx([file_diff("small.py", head="x\n")]))
    m = _mandatory(ins)
    p = _build(ins, m + 2_000)
    assert _note(p.context, "pr")[0].reason == "budget"
    assert p.context.full_files_included == ()
    assert p.context.full_files_dropped == ("small.py",)


# ---------------------------------------------------------------------------
# b. Verifier candidates: whole, dropped from the end, reported (D-37)
# ---------------------------------------------------------------------------


def _candidates(n: int, tokens: int = 250):
    return [
        candidate(k, "| D | Critical | Unintended | " + "y" * (tokens * 7 // 2 - 40) + " |")
        for k in range(1, n + 1)
    ]


def test_candidates_are_whole_and_dropped_from_the_end():
    cands = _candidates(10)
    ins = inputs(title="t", body="b", verifier=verifier_ctx(report(section="", candidates=cands)))
    m = _mandatory(ins)
    p = _build(ins, m + 1_200)
    ctx = p.context
    shown, dropped = ctx.shown_candidates, ctx.dropped_candidates
    assert 1 <= len(shown) < 10
    assert shown + dropped == tuple(cands)  # never silently lost
    blocks, outside = parse_blocks(p.user, p.nonce)
    texts = {t: c for k, t, c in blocks if k == "verifier-candidate"}
    assert list(texts) == [c.id for c in shown]
    for c in shown:
        assert texts[c.id] == c.text + "\n"  # never truncated inside a candidate
    for c in dropped:
        assert c.text not in p.user
    # Candidates come before issues: with candidates over budget, issues are omitted.


def test_candidates_before_issues():
    cands = _candidates(10)
    ins = inputs(
        title="t",
        body="b",
        issues=issues_ctx(issue(41, "short\n")),
        verifier=verifier_ctx(report(section="", candidates=cands)),
    )
    m = _mandatory(ins)
    p = _build(ins, m + 1_200)
    assert p.context.dropped_candidates
    assert _note(p.context, "issue", "#41")[0].state == "omitted"


def test_dropped_candidates_are_named_in_the_notes_by_id_only():
    cands = _candidates(5)
    ins = inputs(title="t", body="b", verifier=verifier_ctx(report(section="", candidates=cands)))
    m = _mandatory(ins)
    p = _build(ins, m + 600)
    dropped = p.context.dropped_candidates
    assert dropped
    _, outside = parse_blocks(p.user, p.nonce)
    assert f"{dropped[0].id}" in outside
    assert "Critical" not in outside


# ---------------------------------------------------------------------------
# c. Issues: min(8,000 x n, 30% of R), split equally
# ---------------------------------------------------------------------------


def test_issues_share_30_percent_of_r_equally():
    big = [issue(n, _text(8_000, str(n % 10))) for n in (41, 43)]
    ins = inputs(title="t", body="b", issues=issues_ctx(*big))
    m = _mandatory(ins)
    b = m + 20_000
    ctx = _ctx(ins, b)
    r = ctx.remaining_tokens
    assert r == b - m
    share = (r * 3 // 10) // 2
    uses = [u for u in ctx.placed if u.block == "issue"]
    assert [u.ref for u in uses] == ["#41", "#43"]
    for u in uses:
        assert u.truncated
        assert u.content_tokens <= share
    assert {(n.ref, n.state) for n in _note(ctx, "issue")} == {
        ("#41", "truncated"),
        ("#43", "truncated"),
    }


def test_issues_within_their_cap_are_whole():
    ins = inputs(issues=issues_ctx(issue(41, "one\n"), issue(43, "two\n")))
    p = _build(ins)
    contents = [c for k, _, c in parse_blocks(p.user, p.nonce)[0] if k == "issue"]
    assert len(contents) == 2 and contents[0].endswith("one\n") and contents[1].endswith("two\n")
    assert contents[0].startswith("Title: [PRD-widgets] Story S-041: title\nLabels: prd:widgets\n")
    assert p.context.issue_numbers == (41, 43)


def test_upstream_issue_truncation_is_named_cap():
    i = issue(41)
    i = type(i)(**{**i.__dict__, "truncated": True})
    ctx = _ctx(inputs(issues=issues_ctx(i)))
    assert [(n.state, n.reason) for n in _note(ctx, "issue", "#41")] == [("truncated", "cap")]


# ---------------------------------------------------------------------------
# d. Verifier drift sections: min(4,000 per report, 10% of R)
# ---------------------------------------------------------------------------


def test_drift_sections_share_10_percent_of_r():
    reps = [
        report(f"workstream/fidelity-report-S-{n:03d}.md", "## Drift\n" + _text(4_000, str(n)))
        for n in range(1, 4)
    ]
    ins = inputs(title="t", body="b", verifier=verifier_ctx(*reps))
    m = _mandatory(ins)
    b = m + 30_000
    ctx = _ctx(ins, b)
    share = min(4_000 * 3, ctx.remaining_tokens // 10) // 3
    uses = [u for u in ctx.placed if u.block == "verifier"]
    assert len(uses) == 3
    for u in uses:
        assert u.content_tokens <= share


def test_drift_section_whole_when_room():
    rep = report(section="## Drift\n| a | b |\n| - | - |\n")
    p = _build(inputs(verifier=verifier_ctx(rep)))
    (sec,) = [c for k, _, c in parse_blocks(p.user, p.nonce)[0] if k == "verifier"]
    assert sec == rep.section


# ---------------------------------------------------------------------------
# e/f. Spec 30% of B, conventions 10% of B
# ---------------------------------------------------------------------------


def test_spec_takes_the_rest_and_starves_conventions_and_files():
    s = spec(text=_text(50_000))
    ins = inputs(
        title="t",
        body="b",
        specs=spec_ctx(s),
        conventions=conventions_ctx(),
        diff=diff_ctx([file_diff("a.py", head="x\n")]),
    )
    m = _mandatory(ins)
    b = max(m + 5_000, 20_000)
    ctx = _ctx(ins, b)
    assert b * 3 // 10 > b - m  # the spec cap exceeds what is left
    assert _note(ctx, "spec")[-1].reason == "budget"
    assert _note(ctx, "conventions")[0].state == "omitted"
    assert ctx.full_files_included == ()


def test_spec_capped_at_30_percent_of_b_and_split_among_specs():
    specs = [spec(f"workstream/specification-prd-{n}.md", _text(60_000, n)) for n in ("a", "b")]
    ctx = _ctx(inputs(specs=spec_ctx(*specs)), 100_000)
    uses = [u for u in ctx.placed if u.block == "spec"]
    assert len(uses) == 2
    for u in uses:
        assert u.content_tokens <= 30_000 // 2
    assert ctx.spec_paths == tuple(s.path for s in specs)


def test_conventions_capped_at_10_percent_of_b():
    ctx = _ctx(inputs(conventions=conventions_ctx(_text(30_000))), 100_000)
    (u,) = [u for u in ctx.placed if u.block == "conventions"]
    assert u.content_tokens <= 10_000
    assert _note(ctx, "conventions")[0].reason == "cap"


def test_empty_conventions_is_no_block_and_no_note():
    p = _build(inputs(conventions=conventions_ctx("")))
    assert "conventions" not in [k for k, _, _ in parse_blocks(p.user, p.nonce)[0]]
    assert _note(p.context, "conventions") == []


# ---------------------------------------------------------------------------
# g. Full files smallest first (TC-209-03, TC-209-07)
# ---------------------------------------------------------------------------


def test_three_smallest_of_five_files_fit():
    sizes = {"e.py": 60_000, "a.py": 1_000, "d.py": 50_000, "b.py": 2_000, "c.py": 3_000}
    files = [file_diff(name, head=_text(t, name[0])) for name, t in sizes.items()]
    ins = inputs(title="t", body="b", diff=diff_ctx(files))
    m = _mandatory(ins)
    ctx = _ctx(ins, m + 6_500)
    assert ctx.full_files_included == ("a.py", "b.py", "c.py")
    assert ctx.full_files_dropped == ("d.py", "e.py")
    assert len(ctx.full_files_included) == 3 and len(ctx.full_files_dropped) == 2


def test_one_huge_file_and_a_hundred_small_ones():
    files = [file_diff("huge.bin.txt", head="z" * 1_000_000)]
    files += [file_diff(f"small/{i:03d}.py", head=f"value = {i}\n") for i in range(100)]
    ctx = _ctx(inputs(diff=diff_ctx(files)), 150_000)
    assert len(ctx.full_files_included) == 100
    assert ctx.full_files_dropped == ("huge.bin.txt",)


def test_full_files_are_whole_or_absent():
    files = [file_diff(f"{i}.py", head=_text(500 * (i + 1), str(i))) for i in range(6)]
    ins = inputs(title="t", body="b", diff=diff_ctx(files))
    m = _mandatory(ins)
    p = _build(ins, m + 4_000)
    for _, _, content in parse_blocks(p.user, p.nonce)[0]:
        assert TRUNCATION_MARKER not in content


def test_ties_keep_the_files_list_order():
    files = [file_diff(n, head="same\n") for n in ("b.py", "a.py", "c.py")]
    ctx = _ctx(inputs(diff=diff_ctx(files)))
    assert ctx.full_files_included == ("b.py", "a.py", "c.py")


def test_removed_files_have_no_full_file():
    files = [file_diff("gone.py", head=None, status="removed"), file_diff("kept.py")]
    ctx = _ctx(inputs(diff=diff_ctx(files)))
    assert ctx.full_files_included == ("kept.py",) and ctx.full_files_dropped == ()


def test_full_files_can_be_left_out_for_the_context_length_retry():
    files = [file_diff("a.py"), file_diff("b.py")]
    p = _build(inputs(diff=diff_ctx(files)), include_full_files=False)
    assert "file" not in [k for k, _, _ in parse_blocks(p.user, p.nonce)[0]]
    assert p.context.full_files_dropped == ("a.py", "b.py")


# ---------------------------------------------------------------------------
# Edge matrix (TC-209-05, TC-209-06, TC-209-08)
# ---------------------------------------------------------------------------


def test_no_issues_no_spec_no_reports_no_conventions():
    p = _build(inputs(body=""))
    ctx = p.context
    assert ctx.no_issues and ctx.no_spec
    assert ctx.verifier_state == "none"
    assert ctx.shown_candidates == () and ctx.dropped_candidates == ()
    kinds = [k for k, _, _ in parse_blocks(p.user, p.nonce)[0]]
    assert kinds == ["diff", "pr", "file"]
    _, outside = parse_blocks(p.user, p.nonce)
    assert "No linked issues." in outside and "No spec found." in outside
    assert "No verifier report." in outside


def _every_block_at_cap(n_reports: int = 10):
    issues = [issue(n, _text(8_000, str(n % 10))) for n in (41, 43, 45, 47, 49)]
    reps = [
        report(
            f"workstream/fidelity-report-S-{n:03d}.md",
            "## Drift\n" + _text(4_000, str(n % 10)),
            [
                candidate(
                    n,
                    "| D | Critical | Unintended | " + "w" * 900 + " |",
                    f"workstream/fidelity-report-S-{n:03d}.md",
                )
            ],
        )
        for n in range(1, n_reports + 1)
    ]
    files = [file_diff(f"src/f{i}.py", head=_text(2_000, str(i))) for i in range(20)]
    return inputs(
        body=_text(4_500),
        issues=issues_ctx(*issues),
        specs=spec_ctx(spec(text=_text(60_000))),
        verifier=verifier_ctx(*reps),
        conventions=conventions_ctx(_text(15_000)),
        diff=diff_ctx(files),
    )


def test_every_block_at_its_cap_still_assembles():
    p = _build(_every_block_at_cap(), 150_000)
    assert p.tokens <= 150_000
    assert len(p.context.shown_candidates) == 10


def test_tc_209_08_capped_blocks_past_the_remaining_budget_at_20000():
    p = _build(_every_block_at_cap(), 20_000)
    ctx = p.context
    assert p.tokens <= 20_000
    assert ctx.total_tokens == estimate(p.fallback_system) + estimate(p.user)
    # Blocks 3-4 (issues, drift sections) alone exceed what remains.
    assert ctx.remaining_tokens < 5 * 8_000 + 10 * 4_000
    assert ctx.omitted or ctx.dropped_candidates or ctx.full_files_dropped


# ---------------------------------------------------------------------------
# Invariant (AC3): asserted, INTERNAL_ERROR on violation
# ---------------------------------------------------------------------------


def test_assert_within_budget():
    assert_within_budget(20_000, 20_000)
    with pytest.raises(BudgetInvariantError) as exc:
        assert_within_budget(20_001, 20_000)
    assert exc.value.code == "INTERNAL_ERROR"
    assert "20001" in str(exc.value) and "20000" in str(exc.value)


def test_a_fill_that_miscounts_raises_internal_error_and_never_reaches_the_sink(monkeypatch):
    calls = []
    monkeypatch.setattr(budget, "_cost", lambda overhead, content: 0)
    with pytest.raises(BudgetInvariantError) as exc:
        build_prompt(
            _every_block_at_cap(),
            max_context_tokens=20_000,
            max_diff_lines=2000,
            nonce=NONCE,
            sink=calls.append,
        )
    assert exc.value.code == "INTERNAL_ERROR"
    assert calls == []


def test_the_invariant_survives_python_dash_o():
    # The check is an explicit raise, not an ``assert`` statement.
    import inspect

    src = inspect.getsource(budget.assert_within_budget)
    assert "raise BudgetInvariantError" in src
