"""
RT-03 (S-207) — issue-link extraction property tactic, seed 409001, 3,000 iterations.

PR bodies plant N valid links (random keyword, random case, optional colon,
random whitespace) among decoys (``owner/repo#N``, ``#N`` alone,
``unclosed #N``, ``#12abc``, issue URLs, ``closes#N``) and noise. Properties:

- the extracted list is the planted links, deduped, in order, cut to 5, then
  the branch number when the head ref has an ``issue/<N>-`` prefix;
- no decoy number is ever extracted (decoys use a disjoint number range);
- the output never has more than 5 entries.
"""

from __future__ import annotations

import random

from context.conventions import MAX_LINKED_ISSUES
from context.issues import linked_issue_numbers
from tests.helpers.prng import Tactic, tactic_seed

SEED = tactic_seed(409, 1)
ITERATIONS = 3000

KEYWORDS = ["close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved"]
NOISE = ["the", "and", "PR", "see", "issue", "123", "foo-bar", "`code`", "—", "ok.", "(x)"]
SPACES = [" ", "\t", "  ", " \t "]
SEPARATORS = [" ", "\n", "\n\n", " - ", "; "]


def _random_case(rng: random.Random, word: str) -> str:
    return "".join(c.upper() if rng.random() < 0.5 else c for c in word)


def _valid(rng: random.Random, n: int) -> str:
    keyword = _random_case(rng, rng.choice(KEYWORDS))
    colon = rng.choice(["", ":", " :"]) if rng.random() < 0.4 else ""
    return f"{keyword}{colon}{rng.choice(SPACES)}#{n}"


def _decoy(rng: random.Random, n: int) -> str:
    keyword = rng.choice(KEYWORDS)
    return rng.choice(
        [
            f"{keyword} owner/repo#{n}",
            f"#{n}",
            f"un{keyword} #{n}",
            f"{keyword} #{n}abc",
            f"{keyword} https://github.com/o/r/issues/{n}",
            f"{keyword}#{n}",
            f"{keyword}:#{n}",
            f"see #{n}",
            f"pre{keyword} #{n}",
        ]
    )


def _branch(rng: random.Random) -> tuple[str, int | None]:
    n = rng.randint(1, 99_999)
    return rng.choice(
        [
            (f"issue/{n}-x", n),
            (f"issue/{n:07d}-y", n),
            (f"issue/{n}", None),
            (f"Issue/{n}-x", None),
            (f"feature/issue/{n}-x", None),
            ("story/S-1-x", None),
            ("main", None),
        ]
    )


def _case(rng: random.Random) -> tuple[str, str, tuple[int, ...]]:
    planted: list[int] = []
    tokens: list[str] = []
    for _ in range(rng.randint(0, 14)):
        roll = rng.random()
        if roll < 0.35:
            n = rng.choice(planted) if planted and rng.random() < 0.25 else rng.randint(1, 99_999)
            planted.append(n)
            tokens.append(_valid(rng, n))
        elif roll < 0.7:
            tokens.append(_decoy(rng, rng.randint(100_000, 999_999)))
        else:
            tokens.append(rng.choice(NOISE))
    body = ""
    for t in tokens:
        body += t + rng.choice(SEPARATORS)
    ref, branch_n = _branch(rng)
    expected = list(dict.fromkeys(planted))
    if branch_n is not None and branch_n not in expected:
        expected.append(branch_n)
    return body, ref, tuple(expected[:MAX_LINKED_ISSUES])


def test_rt03_extraction_matches_the_planted_links():
    tactic = Tactic.from_env(SEED, ITERATIONS)
    rng = tactic.rng()
    for i in range(tactic.iterations):
        body, ref, expected = _case(rng)
        if not tactic.selected(i):
            continue
        ctx = tactic.context(i, (body, ref))
        got = linked_issue_numbers(body, ref)
        assert got == expected, ctx
        assert len(got) <= MAX_LINKED_ISSUES, ctx
        assert all(n < 100_000 for n in got), ctx
