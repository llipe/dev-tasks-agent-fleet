"""
RT-10 (S-207) — spec trimming property tactic, seed 409002, 1,000 iterations.

Random heading trees with dotted numbers (``8``, ``8.1``, ``8.10``, ``80``…),
random ``Spec §<n>`` citations, random body sizes, and a random cap.
Properties:

- the output estimate never exceeds the cap;
- a spec within the cap is returned unchanged;
- when trimmed but not truncated, every heading is present (the outline) and
  a section's body is kept exactly when a citation is a dotted prefix of its
  number (``8`` keeps ``8.10`` but not ``80``; ``8.1`` keeps ``8.1.2`` but not
  ``8.10``).
"""

from __future__ import annotations

import random

from context.spec import trim_spec
from context.tokens import estimate
from tests.helpers.prng import Tactic, tactic_seed

SEED = tactic_seed(409, 2)
ITERATIONS = 1000

TOP = ["1", "2", "8", "9", "10", "80", "81"]
CHILD = ["1", "2", "3", "10", "11"]


def _tree(rng: random.Random) -> list[tuple[int, str]]:
    """(level, number) in document order; children extend their parent number."""
    out: list[tuple[int, str]] = []

    def grow(prefix: str, level: int, depth: int) -> None:
        if depth == 0 or level > 6:
            return
        for c in rng.sample(CHILD, rng.randint(0, 3)):
            num = f"{prefix}.{c}"
            out.append((level, num))
            grow(num, level + 1, depth - 1)

    for top in rng.sample(TOP, rng.randint(1, len(TOP))):
        out.append((2, top))
        grow(top, 3, rng.randint(0, 2))
    return out


def _case(rng: random.Random):
    tree = _tree(rng)
    parts = ["# Title\n"]
    headings: list[tuple[str, str]] = []
    for idx, (level, num) in enumerate(tree):
        dot = "." if rng.random() < 0.5 and "." not in num else ""
        heading = f"{'#' * level} {num}{dot} Section\n"
        headings.append((heading, num))
        parts.append(heading)
        parts.append(f"<B{idx}> " + "filler " * rng.randint(0, 120) + "\n")
    text = "".join(parts)
    pool = [num for _, num in tree] + ["8", "8.1", "80", "3", "8.1.2", "10.1"]
    citations = tuple(dict.fromkeys(rng.sample(pool, rng.randint(0, 3))))
    cap = rng.choice([0, 5, 50, 200, 1_000, 5_000, estimate(text) + rng.randint(0, 10)])
    return headings, text, citations, cap


def _cited(num: str, citations: tuple[str, ...]) -> bool:
    return any(num == c or num.startswith(c + ".") for c in citations)


def test_rt10_trim_properties():
    tactic = Tactic.from_env(SEED, ITERATIONS)
    rng = tactic.rng()
    exact_checks = 0
    for i in range(tactic.iterations):
        headings, text, citations, cap = _case(rng)
        if not tactic.selected(i):
            continue
        ctx = tactic.context(i, (text, citations, cap))
        out, trimmed, truncated = trim_spec(
            text, citations=citations, story_ids=(), reviewed_paths=(), cap_tokens=cap
        )
        assert estimate(out) <= cap, ctx
        if estimate(text) <= cap:
            assert (out, trimmed, truncated) == (text, False, False), ctx
            continue
        assert trimmed, ctx
        if truncated:
            continue
        exact_checks += 1
        assert "# Title\n" in out, ctx
        for idx, (heading, num) in enumerate(headings):
            assert heading in out, ctx
            assert (f"<B{idx}> " in out) == _cited(num, citations), ctx
    if not tactic.replaying:
        assert exact_checks > 50
