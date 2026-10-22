"""
RT-09 (S-206) — diff round-trip property tactic, seed 408002, 1,000 iterations.

Random base texts are mutated by insert, delete, and replace runs, with CRLF,
a missing EOF newline, and Unicode mixed in. Properties:

- every line changed in the 0-context diff appears as ``+`` or ``-`` in the
  ``n=50`` diff (nothing the reviewer must see is lost to context selection);
- each hunk carries at most 50 context lines before its first change and after
  its last change;
- applying the ``n=50`` diff to the base reproduces the head (round trip);
- changed ranges are within ``[1, len(head lines)]``;
- the output is deterministic.
"""

from __future__ import annotations

import difflib
import random
import re

from context.diff import CONTEXT_LINES, changed_ranges, split_lines, unified_diff
from tests.helpers.prng import Tactic, tactic_seed

SEED = tactic_seed(408, 2)
ITERATIONS = 1000

POOL = ["alpha", "beta", "gamma", "δέλτα", "日本語", "", "    indent", "x = 1", "\t tab", "}", "{"]
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@$")
NO_EOL = "\\ No newline at end of file"


def _text(rng: random.Random) -> list[str]:
    return [
        rng.choice(POOL) + (str(rng.randint(0, 9)) if rng.random() < 0.5 else "")
        for _ in range(rng.randint(0, 220))
    ]


def _mutate(rng: random.Random, lines: list[str]) -> list[str]:
    out = list(lines)
    for _ in range(rng.randint(0, 5)):
        op = rng.choice(["insert", "delete", "replace"])
        at = rng.randint(0, len(out))
        run = rng.randint(1, 8)
        if op == "insert":
            out[at:at] = [f"new{rng.randint(0, 999)}" for _ in range(run)]
        elif op == "delete":
            del out[at : at + run]
        else:
            out[at : at + run] = [f"rep{rng.randint(0, 999)}" for _ in range(run)]
    return out


def _join(rng: random.Random, lines: list[str], eol: str) -> str:
    if not lines:
        return ""
    text = eol.join(lines)
    return text if rng.random() < 0.2 else text + eol


def _parse(diff: str) -> list[tuple[int, int, int, int, list[str]]]:
    """Hunks as (a_start, a_len, b_start, b_len, body lines with eol restored)."""
    hunks: list[tuple[int, int, int, int, list[str]]] = []
    raw = diff.split("\n")
    i = 2  # skip the two file headers
    while i < len(raw) and raw[i]:
        m = _HUNK.match(raw[i])
        assert m, raw[i]
        a, al, b, bl = (
            int(m.group(1)),
            int(m.group(2) or 1),
            int(m.group(3)),
            int(m.group(4) or 1),
        )
        body: list[str] = []
        i += 1
        while i < len(raw) and raw[i] and not raw[i].startswith("@@ "):
            line = raw[i]
            if line == NO_EOL:
                body[-1] = body[-1][:-1]  # the previous line had no newline
            else:
                body.append(line + "\n")
            i += 1
        hunks.append((a, al, b, bl, body))
    return hunks


def _apply(base: list[str], diff: str) -> list[str]:
    out: list[str] = []
    pos = 0
    for a, al, _b, _bl, body in _parse(diff):
        start = a - 1 if al else a
        out.extend(base[pos:start])
        pos = start
        for line in body:
            tag, content = line[0], line[1:]
            if tag in " -":
                assert base[pos] == content
                pos += 1
            if tag in " +":
                out.append(content)
    out.extend(base[pos:])
    return out


def test_rt09_diff_properties():
    tactic = Tactic.from_env(SEED, ITERATIONS)
    rng = tactic.rng()
    for i in range(tactic.iterations):
        eol = "\r\n" if rng.random() < 0.25 else "\n"
        base_lines = _text(rng)
        base = _join(rng, base_lines, eol)
        head = _join(rng, _mutate(rng, base_lines), eol)
        if not tactic.selected(i):
            continue
        ctx = tactic.context(i, (base, head))
        b, h = split_lines(base), split_lines(head)

        diff = unified_diff("f.txt", "f.txt", base, head, "modified")
        assert diff == unified_diff("f.txt", "f.txt", base, head, "modified"), ctx
        assert _apply(b, diff) == h, ctx

        zero = [
            ln
            for ln in difflib.unified_diff(b, h, n=0)
            if ln[:1] in "+-" and ln[:3] not in ("---", "+++")
        ]
        signed = []
        for _a, _al, _b, _bl, body in _parse(diff):
            signed.extend(ln for ln in body if ln[0] in "+-")
            tags = [ln[0] for ln in body]
            changes = [k for k, t in enumerate(tags) if t != " "]
            assert changes, ctx
            assert changes[0] <= CONTEXT_LINES, ctx
            assert len(tags) - 1 - changes[-1] <= CONTEXT_LINES, ctx
        assert [ln.rstrip("\n") for ln in zero] == [ln.rstrip("\n") for ln in signed], ctx

        for start, end in changed_ranges(base, head):
            assert 1 <= start <= end <= len(h), ctx
        assert changed_ranges(base, head) == changed_ranges(base, head), ctx
