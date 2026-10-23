"""
S-209 hostile budget fit (qa-engineer completion gate; spec §8.4, D-27, D-37).

Adversarial complements to ``test_budget_fit.py`` and RT-07. The guarantee
under attack is spec §8.4 step 3: ``estimate(fallback system) +
estimate(user) <= max_context_tokens`` for every input, with ``OverBudget``
exactly when ``I + D > B`` and never a false ``BudgetInvariantError``.

Probed here: budgets at and around ``I + D``; the 20,000 minimum with every
reader at its contract maximum (5 issues, 5 specs, 10 reports, 60 files);
huge counts of candidates, files and name-only paths; multi-byte and astral
text (``len`` counts code points); CRLF and CR-only text; cuts that leave
nothing; empty strings; the placeholder-nonce overhead against the real nonce;
the ``include_full_files=False`` path; and a seeded property tactic
(``tactic_seed(411, 3)``) that mixes all of them.

Real defects are pinned with ``xfail(strict=True)``: the fix turns them red
and the marker is removed in the same change.
"""

from __future__ import annotations

import dataclasses
import random

import pytest

import budget
from budget import BLOCK_DIFF, NAME_ONLY_TOKEN_CAP, BlockNote, BudgetInvariantError, prompt_tokens
from context.diff import OVER_TOKENS, NameOnlyFile, OverBudget
from context.repo_conventions import ConventionsContext
from context.spec import ResolvedSpec
from context.tokens import TRUNCATION_MARKER, estimate
from prompt import Prompt, build_prompt, render_file_block
from tests.helpers.prng import Tactic, tactic_seed
from tests.helpers.prompt_inputs import (
    NONCE,
    OTHER_NONCE,
    candidate,
    diff_ctx,
    file_diff,
    inputs,
    issue,
    issues_ctx,
    parse_blocks,
    report,
    spec_ctx,
    verifier_ctx,
)

BIG = 10_000_000
NOTED_KINDS = ("pr", "issue", "spec", "verifier", "conventions")


def _build(ins, max_context_tokens: int = BIG, **kw):
    kw.setdefault("nonce", NONCE)
    return build_prompt(ins, max_context_tokens=max_context_tokens, max_diff_lines=2000, **kw)


def _prompt(ins, max_context_tokens: int = BIG, **kw) -> Prompt:
    result = _build(ins, max_context_tokens, **kw)
    assert isinstance(result, Prompt), result
    return result


def _mandatory(ins) -> int:
    """``I + D`` for ``ins``, read from an unconstrained build."""
    return _prompt(ins).context.mandatory_tokens


def _lines(tokens: int, unit: str = "x") -> str:
    """About ``tokens`` estimated tokens of 34-code-point lines."""
    line = (unit * 34)[:34] + "\n"
    return line * max(1, (tokens * 7 // 2) // len(line))


def _rich(text: str = "") -> object:
    """Every reader present, each block well over its cap."""
    body = text or _lines(50_000)
    issues = [dataclasses.replace(issue(1000 + k, body=body), truncated=True) for k in range(5)]
    specs = [
        ResolvedSpec(f"workstream/specification-prd-w{k}.md", body, True, True, 0, 1000)
        for k in range(5)
    ]
    reports = []
    k = 0
    for r in range(10):
        cands = []
        for _ in range(5):
            k += 1
            cands.append(
                candidate(
                    k,
                    text="| D | Critical | Unintended | " + "y" * 900 + " |",
                    path=f"workstream/fidelity-report-S-{r:03d}.md",
                )
            )
        rep = report(
            path=f"workstream/fidelity-report-S-{r:03d}.md", section=body, candidates=cands
        )
        reports.append(dataclasses.replace(rep, section_truncated=True))
    conv = ConventionsContext("AGENTS.md", (), 0, body, True, 0)
    files = [file_diff(f"src/f{k:02d}.py", head=_lines(200 * (k + 1))) for k in range(60)]
    return inputs(
        diff=diff_ctx(files),
        body=body,
        issues=issues_ctx(*issues),
        specs=spec_ctx(*specs),
        verifier=verifier_ctx(*reports),
        conventions=conv,
    )


def _check_prompt(p: Prompt, ins, max_context_tokens: int) -> None:
    """Every property the budget fit promises for a built prompt."""
    ctx = p.context
    # The invariant, on the real strings (spec §8.4 step 3).
    assert prompt_tokens(p) == estimate(p.fallback_system) + estimate(p.user)
    assert prompt_tokens(p) == p.tokens <= max_context_tokens
    # The fill never under-counts what it rendered.
    assert ctx.mandatory_tokens + sum(u.tokens for u in ctx.placed) >= p.tokens
    blocks, outside = parse_blocks(p.user, p.nonce)
    # Candidates: shown + dropped is every candidate, in order; shown is
    # exactly the set rendered, in order (D-37).
    every = tuple(ins.verifier.candidates) if ins.verifier is not None else ()
    assert ctx.shown_candidates + ctx.dropped_candidates == every
    rendered = [tag for kind, tag, _ in blocks if kind == "verifier-candidate"]
    assert rendered == [c.id for c in ctx.shown_candidates]
    # Full files: included + dropped is every reviewed, non-removed file.
    heads = [f.filename for f in ins.diff.files if f.head_content is not None]
    assert sorted(ctx.full_files_included + ctx.full_files_dropped) == sorted(heads)
    assert sum(1 for kind, _, _ in blocks if kind == "file") == len(ctx.full_files_included)
    # Every cut or omission of a noted kind is named (spec §8.4 step 4).
    named = {(n.block, n.ref, n.state) for n in ctx.notes}
    for use in ctx.placed:
        if use.block in NOTED_KINDS and use.truncated:
            assert (use.block, use.ref, "truncated") in named, use
    # The closing notes are never cut by their own reserve.
    notes = p.user[p.user.rindex("Context notes:") :]
    assert TRUNCATION_MARKER not in notes, notes
    if ctx.dropped_candidates:
        assert "were not included (budget)" in notes


# ---------------------------------------------------------------------------
# The I + D boundary (PRD FR-6, TC-209-04)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("delta", [-1, 0, 1, 2, 20, 200])
def test_budgets_around_the_mandatory_part(delta):
    ins = _rich()
    mand = _mandatory(ins)
    sink: list[Prompt] = []
    result = _build(ins, mand + delta, sink=sink.append)
    if delta < 0:
        assert isinstance(result, OverBudget)
        assert result.reason == OVER_TOKENS
        assert result.tokens == mand
        assert result.max_context_tokens == mand + delta
        assert sink == []
        return
    assert isinstance(result, Prompt)
    _check_prompt(result, ins, mand + delta)
    assert sink == [result]
    if delta == 0:
        # R = 0: nothing optional fits; every candidate and file is dropped.
        assert result.context.remaining_tokens == 0
        assert result.context.placed == ()
        assert result.context.shown_candidates == ()


def test_exactly_at_i_plus_d_names_every_omitted_block():
    ins = _rich()
    p = _prompt(ins, _mandatory(ins))
    omitted = {(n.block, n.ref) for n in p.context.omitted}
    assert ("pr", None) in omitted
    assert {("issue", f"#{1000 + k}") for k in range(5)} <= omitted
    assert {r for b, r in omitted if b == "spec"} == {
        f"workstream/specification-prd-w{k}.md" for k in range(5)
    }
    assert len([b for b, _ in omitted if b == "verifier"]) == 10
    assert ("conventions", "AGENTS.md") in omitted


def test_the_20000_minimum_with_every_reader_at_its_contract_maximum():
    ins = _rich()
    p = _prompt(ins, 20_000)
    _check_prompt(p, ins, 20_000)
    assert p.context.dropped_candidates  # 50 candidates of ~270 tokens cannot all fit


def test_a_tiny_budget_below_the_instructions_is_over_budget_not_an_error():
    ins = inputs(body="")
    for b in (1, 100, 2_000):
        result = _build(ins, b)
        assert isinstance(result, OverBudget) and result.reason == OVER_TOKENS


# ---------------------------------------------------------------------------
# Huge counts
# ---------------------------------------------------------------------------


def test_ten_thousand_candidates_stay_within_budget_and_partition_in_order():
    cands = [
        candidate(k, text=f"| D{k} | Critical | Unintended | row {k} |") for k in range(1, 10_001)
    ]
    ins = inputs(verifier=verifier_ctx(report(candidates=cands)))
    for b in (20_000, 60_000):
        p = _prompt(ins, b)
        _check_prompt(p, ins, b)
        assert p.context.dropped_candidates
        assert p.context.dropped_candidates[0].id == f"V{len(p.context.shown_candidates) + 1}"


def test_three_thousand_full_files_stay_within_budget():
    files = [file_diff(f"src/m{k:04d}.py", head="v = 1\n" * (k % 50 + 1)) for k in range(3_000)]
    ins = inputs(diff=diff_ctx(files, changed_lines=3_000))
    mand = _mandatory(ins)
    for b in (mand, mand + 5_000, 400_000):
        p = _prompt(ins, b)
        _check_prompt(p, ins, b)


def test_a_hundred_thousand_name_only_paths_cannot_push_the_diff_over_budget():
    name_only = [NameOnlyFile(f"dist/{k:06d}.js", "added", "generated") for k in range(100_000)]
    ins = inputs(diff=diff_ctx(name_only=name_only))
    p = _prompt(ins, 20_000)
    _check_prompt(p, ins, 20_000)
    assert p.context.diff_tokens <= NAME_ONLY_TOKEN_CAP + 200


def test_huge_name_only_paths_with_control_characters_are_capped():
    name_only = [NameOnlyFile("\n" * 50_000 + str(k), "added", "lockfile") for k in range(20)]
    ins = inputs(diff=diff_ctx(name_only=name_only))
    p = _prompt(ins, 20_000)
    _check_prompt(p, ins, 20_000)
    assert p.context.diff_tokens <= NAME_ONLY_TOKEN_CAP + 200


def test_a_cut_name_only_listing_is_named_in_the_context_data():
    name_only = [NameOnlyFile(f"dist/{k:05d}.js", "added", "generated") for k in range(20_000)]
    p = _prompt(inputs(diff=diff_ctx(name_only=name_only)))
    (diff_block,) = [c for k, _, c in parse_blocks(p.user, p.nonce)[0] if k == "diff"]
    assert TRUNCATION_MARKER in diff_block  # the cut happened
    assert [n for n in p.context.notes if n.block == BLOCK_DIFF] == [
        BlockNote(BLOCK_DIFF, "name-only", "truncated", "cap")
    ]


# ---------------------------------------------------------------------------
# Characters: multi-byte, astral, CRLF, CR-only, empty
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unit",
    ["é", "漢", "\U0001f600", "\U0001f468‍\U0001f469‍\U0001f467", "\r\n", "\r", " "],
    ids=["latin1", "cjk", "astral", "zwj-sequence", "crlf", "cr-only", "line-separator"],
)
def test_hostile_characters_at_every_cap_stay_within_budget(unit):
    body = unit * 400_000
    ins = _rich(body)
    for b in (20_000, _mandatory(ins) + 3_000, 150_000):
        p = _prompt(ins, b)
        _check_prompt(p, ins, b)


def test_estimate_counts_code_points_for_every_block():
    # One astral code point is one unit of len(); four UTF-8 bytes do not count four times.
    p = _prompt(inputs(body="\U0001f600" * 7_000), 150_000)
    (pr,) = [c for k, _, c in parse_blocks(p.user, p.nonce)[0] if k == "pr"]
    (use,) = [u for u in p.context.placed if u.block == "pr"]
    assert use.content_tokens == estimate(pr) == (len(pr) * 2 + 6) // 7


def test_a_cr_only_body_over_its_cap_is_hard_cut_within_the_cap():
    p = _prompt(inputs(body=("word " * 10 + "\r") * 20_000), 150_000)
    (pr,) = [c for k, _, c in parse_blocks(p.user, p.nonce)[0] if k == "pr"]
    assert pr.endswith("\n" + TRUNCATION_MARKER + "\n")
    assert estimate(pr) <= budget.PR_TOKEN_CAP


def test_a_crlf_body_is_cut_after_a_whole_crlf_pair():
    p = _prompt(inputs(body="line of text\r\n" * 20_000), 150_000)
    (pr,) = [c for k, _, c in parse_blocks(p.user, p.nonce)[0] if k == "pr"]
    head = pr[: -len(TRUNCATION_MARKER) - 1]
    assert head.endswith("\r\n") and "\r\r" not in head


@pytest.mark.parametrize("filler", ["\n", " \n", "\r\n", "\t\n"])
def test_whitespace_only_cuts_are_omitted_and_named(filler):
    path = "workstream/specification-prd-blank.md"
    ins = inputs(specs=spec_ctx(ResolvedSpec(path, filler * 500_000, False, False, 0, 1)))
    p = _prompt(ins, 20_000)
    _check_prompt(p, ins, 20_000)
    assert "spec" not in [k for k, _, _ in parse_blocks(p.user, p.nonce)[0]]
    assert [(n.block, n.ref, n.state, n.reason) for n in p.context.notes] == [
        ("spec", path, "omitted", "budget")
    ]
    assert p.context.spec_paths == ()


def test_empty_strings_everywhere_build_a_valid_prompt():
    ins = dataclasses.replace(
        inputs(
            title="",
            body="",
            issues=issues_ctx(dataclasses.replace(issue(1, body="", title=""), labels=())),
            specs=spec_ctx(
                ResolvedSpec("workstream/specification-prd-x.md", "", False, False, 0, 1)
            ),
            verifier=verifier_ctx(report(section="")),
            conventions=ConventionsContext(None, (), 0, "", False, 0),
            diff=diff_ctx([file_diff("", head="", diff="")]),
        ),
        head_sha="",
    )
    for b in (20_000, 150_000):
        p = _prompt(ins, b)
        _check_prompt(p, ins, b)


# ---------------------------------------------------------------------------
# Overhead: the placeholder nonce versus the real one
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("nonce", [NONCE, OTHER_NONCE, "0" * 16, "f" * 16])
def test_the_charged_tokens_do_not_depend_on_the_nonce(nonce):
    ins = _rich()
    base = _prompt(ins, 40_000)
    p = _prompt(ins, 40_000, nonce=nonce)
    assert p.nonce == nonce
    assert len(p.user) == len(base.user)
    assert p.context.placed == base.context.placed
    assert p.tokens == base.tokens <= 40_000


def test_a_rendered_file_block_has_the_same_length_for_every_nonce():
    lengths = {
        len(render_file_block("src/\n a.py", "x\n" * 10, n)) for n in (NONCE, OTHER_NONCE, "0" * 16)
    }
    assert len(lengths) == 1


def test_a_regenerated_nonce_keeps_the_prompt_within_budget():
    # The first nonce collides; the fill was measured once, the render repeats.
    ins = _rich(NONCE + "\n" + _lines(50_000))
    p = _prompt(ins, 20_000, nonce_factory=lambda: OTHER_NONCE)
    assert p.nonce == OTHER_NONCE
    _check_prompt(p, ins, 20_000)


# ---------------------------------------------------------------------------
# include_full_files=False (spec §16 R4)
# ---------------------------------------------------------------------------


def test_the_context_length_retry_prompt_has_no_file_and_fits():
    ins = _rich()
    for b in (20_000, 150_000):
        full = _prompt(ins, b)
        retry = _prompt(ins, b, include_full_files=False)
        _check_prompt(retry, ins, b)
        assert "file" not in [k for k, _, _ in parse_blocks(retry.user, retry.nonce)[0]]
        assert retry.context.full_files_included == ()
        assert retry.tokens <= full.tokens or not full.context.full_files_included


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Defect (Low): with include_full_files=False, ContextData.full_files_dropped is in "
        "files-list order (prompt._context_data uses pieces.all_files), but ContextData's "
        "docstring and PR #432 pinned decision 5 say included/dropped are smallest-first."
    ),
)
def test_the_context_length_retry_reports_dropped_files_smallest_first():
    files = [file_diff("big.py", head="x\n" * 5_000), file_diff("small.py", head="x\n")]
    p = _prompt(inputs(diff=diff_ctx(files)), include_full_files=False)
    assert p.context.full_files_dropped == ("small.py", "big.py")


# ---------------------------------------------------------------------------
# Property tactic: hostile mixes at tight budgets (seed 411003)
# ---------------------------------------------------------------------------

SEED = tactic_seed(411, 3)
ITERATIONS = 150
POOL = [
    "a",
    "é",
    "漢",
    "\U0001f600",
    "\r\n",
    "\r",
    "\n",
    " ",
    " ",
    "​",
    "<<<END ",
    ">>>",
    "\t",
    "\x00",
    "[truncated]",
]


def _hostile(rng: random.Random, n: int) -> str:
    roll = rng.random()
    if roll < 0.1:
        return ""
    if roll < 0.2:
        return " \n" * rng.randint(0, n)
    if roll < 0.3:
        return rng.choice(POOL) * rng.randint(0, n)
    return "".join(rng.choice(POOL) for _ in range(rng.randint(0, n)))


def _random_inputs(rng: random.Random):
    size = rng.choice([30, 300, 3_000, 30_000])
    issues = [
        dataclasses.replace(
            issue(100 + k, body=_hostile(rng, size), title=_hostile(rng, 40)),
            labels=tuple(_hostile(rng, 8) for _ in range(rng.randint(0, 3))),
            truncated=rng.random() < 0.3,
        )
        for k in range(rng.randint(0, 5))
    ]
    specs = [
        ResolvedSpec(
            f"workstream/specification-p{k}.md",
            _hostile(rng, size),
            rng.random() < 0.3,
            rng.random() < 0.3,
            0,
            1,
        )
        for k in range(rng.randint(0, 5))
    ]
    reports = []
    k = 0
    for r in range(rng.randint(0, 10)):
        cands = []
        for _ in range(rng.randint(0, 6)):
            k += 1
            path = f"workstream/fidelity-report-S-{r}.md"
            cands.append(candidate(k, text=_hostile(rng, 1_050) or "x", path=path))
        rep = report(
            path=f"workstream/fidelity-report-S-{r}.md",
            section=_hostile(rng, size),
            candidates=cands,
        )
        reports.append(dataclasses.replace(rep, section_truncated=rng.random() < 0.3))
    conv = (
        ConventionsContext("AGENTS.md", (), 0, _hostile(rng, size), rng.random() < 0.3, 0)
        if rng.random() < 0.7
        else None
    )
    files = [
        file_diff(
            f"src/{_hostile(rng, 6)}{j}.py",
            head=_hostile(rng, rng.choice([10, 1_000, 20_000])) if rng.random() < 0.9 else None,
        )
        for j in range(rng.randint(1, 25))
    ]
    name_only = [
        NameOnlyFile(_hostile(rng, 30), "modified", "lockfile")
        for _ in range(rng.choice([0, 3, 500]))
    ]
    return inputs(
        diff=diff_ctx(files, name_only),
        title=_hostile(rng, 200),
        body=_hostile(rng, size),
        issues=issues_ctx(*issues) if rng.random() < 0.8 else None,
        specs=spec_ctx(*specs) if rng.random() < 0.8 else None,
        verifier=verifier_ctx(*reports) if rng.random() < 0.8 else None,
        conventions=conv,
    )


def test_hostile_budget_fit_properties():
    tactic = Tactic.from_env(SEED, ITERATIONS)
    rng = tactic.rng()
    for i in range(tactic.iterations):
        ins = _random_inputs(rng)
        offset = rng.choice([None, -1, 0, 1, rng.randint(2, 3_000)])
        fixed = rng.randint(20_000, 400_000)
        full = rng.random() < 0.8
        if not tactic.selected(i):
            continue
        mand = _mandatory(ins)
        b = fixed if offset is None else max(1, mand + offset)
        ctx = tactic.context(i, (b, mand, full))
        try:
            result = _build(ins, b, include_full_files=full)
        except BudgetInvariantError as exc:  # a false INTERNAL_ERROR is a defect too
            pytest.fail(f"BudgetInvariantError {exc} at {ctx}")
        if mand > b:
            assert isinstance(result, OverBudget), ctx
            assert result.tokens == mand, ctx
            continue
        assert isinstance(result, Prompt), ctx
        try:
            _check_prompt(result, ins, b)
        except AssertionError as exc:
            raise AssertionError(f"{exc} at {ctx}") from exc
        if not full:
            assert result.context.full_files_included == (), ctx
