"""
RT-07 (S-209) — budget fit property tactic, seed 411002, 3,000 iterations.

Random block sizes (PR body, 0-5 issues, 0-4 reports with 0-3 candidates each,
0-3 specs, conventions), 0-60 full files of random size, a diff that is
sometimes over budget, and ``max_context_tokens`` in [20,000, 400,000].
Properties:

- ``OverBudget`` exactly when the mandatory part (instructions + diff) is over
  ``max_context_tokens``, and then with the token counts;
- otherwise ``estimate(prompt) <= max_context_tokens`` (D-37), counted over
  the whole serialized prompt (fallback system prompt + user message);
- the included full files are the maximal smallest-first prefix that fits:
  every included file costs no more than any dropped one, and the smallest
  dropped file does not fit in what is left (the same set as drop
  largest-first); included and dropped together are all reviewed, non-removed
  files;
- shown and dropped candidates together are all candidates, in order, and the
  dropped ones are a suffix (D-37).
"""

from __future__ import annotations

import random

from budget import prompt_tokens
from context.diff import OVER_TOKENS, OverBudget
from context.tokens import estimate
from prompt import Prompt, build_prompt, render_file_block
from tests.helpers.prng import Tactic, tactic_seed
from tests.helpers.prompt_inputs import (
    NONCE,
    candidate,
    conventions_ctx,
    diff_ctx,
    file_diff,
    inputs,
    issue,
    issues_ctx,
    report,
    spec,
    spec_ctx,
    verifier_ctx,
)

SEED = tactic_seed(411, 2)
ITERATIONS = 3000


def _blob(rng: random.Random, tokens: int, tag: str) -> str:
    """About ``tokens`` estimated tokens of lines of random width."""
    width = rng.choice([1, 20, 80, 400])
    line = tag[0] * width + "\n"
    n = max(0, tokens * 7 // 2 // len(line))
    return line * n + (tag if rng.random() < 0.3 else "")


def _size(rng: random.Random, scale: int) -> int:
    return int(scale * rng.random() ** 3)


def _case(rng: random.Random):
    b = rng.randint(20_000, 400_000)
    n_files = rng.randint(0, 60)
    diff_share = rng.choice([0.01, 0.1, 0.4, 0.9, 1.1])
    per_file_diff = int(b * diff_share / max(1, n_files) / 1)
    files = [
        file_diff(
            f"src/m{i:02d}.py",
            head=None if rng.random() < 0.05 else _blob(rng, _size(rng, b // 4), "h"),
            diff=_blob(rng, rng.randint(0, max(1, per_file_diff)), "d") or "@@\n",
            status="modified",
        )
        for i in range(n_files)
    ]
    if not files:
        files = [file_diff("only.py", diff=_blob(rng, int(b * diff_share), "d") or "@@\n")]
    issues = [issue(41 + k, _blob(rng, _size(rng, 8_000), "i")) for k in range(rng.randint(0, 5))]
    k = 0
    reps = []
    for r in range(rng.randint(0, 4)):
        cands = []
        for _ in range(rng.randint(0, 3)):
            k += 1
            cands.append(candidate(k, "| Critical | Unintended | " + "c" * rng.randint(0, 1_000)))
        reps.append(
            report(
                f"workstream/fidelity-report-S-{r:03d}.md",
                _blob(rng, _size(rng, 4_000), "v"),
                cands,
            )
        )
    specs = [
        spec(f"workstream/specification-prd-{j}.md", _blob(rng, _size(rng, b * 3 // 10), "s"))
        for j in range(rng.randint(0, 3))
    ]
    return b, inputs(
        body=_blob(rng, _size(rng, 6_000), "p"),
        issues=issues_ctx(*issues) if issues else None,
        specs=spec_ctx(*specs) if specs else None,
        verifier=verifier_ctx(*reps) if reps else None,
        conventions=conventions_ctx(_blob(rng, _size(rng, b // 10), "k"))
        if rng.random() < 0.7
        else None,
        diff=diff_ctx(files),
    )


def test_budget_fit_properties():
    tactic = Tactic.from_env(SEED, ITERATIONS)
    rng = tactic.rng()
    over = fitted = 0
    for i in range(tactic.iterations):
        b, ins = _case(rng)
        if not tactic.selected(i):
            continue
        ctx = tactic.context(i, f"max_context_tokens={b}")
        result = build_prompt(ins, max_context_tokens=b, max_diff_lines=10_000, nonce=NONCE)
        if isinstance(result, OverBudget):
            over += 1
            assert result.reason == OVER_TOKENS, ctx
            assert result.tokens is not None and result.tokens > b, ctx
            assert result.max_context_tokens == b, ctx
            continue
        fitted += 1
        assert isinstance(result, Prompt), ctx
        data = result.context
        assert data.mandatory_tokens <= b, ctx
        total = estimate(result.fallback_system) + estimate(result.user)
        assert total == data.total_tokens == prompt_tokens(result) <= b, ctx

        # Full files: maximal smallest-first prefix.
        heads = {f.filename: f.head_content for f in ins.diff.files if f.head_content is not None}
        included, dropped = data.full_files_included, data.full_files_dropped
        assert sorted(included + dropped) == sorted(heads), ctx
        cost = {p: estimate(render_file_block(p, heads[p], result.nonce)) for p in heads}
        if included and dropped:
            assert max(cost[p] for p in included) <= min(cost[p] for p in dropped), ctx
        if dropped:
            assert min(cost[p] for p in dropped) > data.unallocated_tokens, ctx

        # Candidates: shown + dropped = all, dropped a suffix.
        all_c = ins.verifier.candidates if ins.verifier else ()
        assert data.shown_candidates + data.dropped_candidates == all_c, ctx
    if not tactic.replaying:
        assert over > 100 and fitted > 1000
