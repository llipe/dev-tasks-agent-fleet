"""
RT-12 (S-207) — task-checklist strip property tactic, seed 409003, 2,000 iterations.

Random issue bodies mix headings at levels 1–7, ``Task Checklist`` variants
(case, spacing, suffixes, level 7), and valid headings (levels 1–6, trailing
spaces or tabs). Every line carries a unique sentinel. Properties:

- the output is a prefix of the input;
- every line above the first valid heading survives, none at or below it;
- with no valid heading the output equals the input;
- the function is idempotent.
"""

from __future__ import annotations

import random
import re

from context.issues import strip_task_checklist
from tests.helpers.prng import Tactic, tactic_seed

SEED = tactic_seed(409, 3)
ITERATIONS = 2000

# Oracle, written independently of the implementation: only spaces and tabs are
# generated, so this is the spec regex restricted to that alphabet.
_VALID = re.compile(r"#{1,6}[ \t]+Task Checklist[ \t]*\r?")

NEAR_MISSES = [
    "task checklist",
    "TASK CHECKLIST",
    "Task Checklist (v2)",
    "Task checklist",
    "Task  Checklist",
    "Task Checklists",
    "The Task Checklist",
]


def _line(rng: random.Random, k: int) -> str:
    roll = rng.random()
    tag = f"<L{k}>"
    if roll < 0.08:
        level = rng.randint(1, 6)
        pad = rng.choice(["", " ", "\t", "  "])
        return "#" * level + rng.choice([" ", "\t", "  "]) + "Task Checklist" + pad
    if roll < 0.25:
        level = rng.randint(1, 7)
        gap = rng.choice([" ", "", "\t"])
        return "#" * level + gap + rng.choice(NEAR_MISSES) + " " + tag
    if roll < 0.32:
        return "####### Task Checklist"
    if roll < 0.36:
        return rng.choice(["Task Checklist", " ## Task Checklist", "x ## Task Checklist"])
    if roll < 0.5:
        return "#" * rng.randint(1, 7) + " Heading " + tag
    return rng.choice(["text", "- [ ] item", "```", "", "  indented"]) + " " + tag


def _case(rng: random.Random) -> list[str]:
    return [_line(rng, k) for k in range(rng.randint(0, 25))]


def test_rt12_strip_properties():
    tactic = Tactic.from_env(SEED, ITERATIONS)
    rng = tactic.rng()
    for i in range(tactic.iterations):
        lines = _case(rng)
        eol = rng.choice(["\n", "\r\n"])
        trailing = rng.choice(["", eol])
        if not tactic.selected(i):
            continue
        body = eol.join(lines) + (trailing if lines else "")
        ctx = tactic.context(i, body)
        out = strip_task_checklist(body)
        assert body.startswith(out), ctx
        assert strip_task_checklist(out) == out, ctx
        cut = next((k for k, line in enumerate(lines) if _VALID.fullmatch(line)), None)
        if cut is None:
            assert out == body, ctx
            continue
        assert out == "".join(line + eol for line in lines[:cut]), ctx
        for k in range(cut, len(lines)):
            assert f"<L{k}>" not in out, ctx
