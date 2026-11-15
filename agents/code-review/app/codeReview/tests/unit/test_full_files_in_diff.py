"""
#464 — no full copy of a file whose diff already shows every head line (D-69).

An added file is sent as an all-``+`` diff; sending its head content again as
a full file doubles its cost (``llipe/riel#632``: 19,348 of 27,717 full-file
tokens were added files). D-67 already made documentation diff-only; this
covers code: a file whose diff hunks span every head line (always true for an
added file and for a base-withheld rename, sometimes for a short modified
file) gets no full-file piece. It is neither included nor dropped, so the
comment never calls it "too large". Its head line numbers stay in the diff
header, and its changed ranges are unchanged, so findings still locate.
"""

from __future__ import annotations

import random
import re

from context.diff import (
    CONTEXT_LINES,
    PROSE_CONTEXT_LINES,
    diff_covers_head,
    split_lines,
    unified_diff,
)
from prompt import Prompt, build_prompt
from tests.helpers.prng import Tactic, tactic_seed
from tests.helpers.prompt_inputs import NONCE, diff_ctx, file_diff, inputs, parse_blocks
from tests.unit.test_diff import HEAD, MB, Repo, _expand, _f, _lines


def _files(blobs: dict, files: list) -> dict:
    return {f.filename: f for f in _expand(Repo(blobs), files).files}


# -- when the diff covers the head (expanded_diff) ------------------------------


def test_diff_covers_head_rule():
    base = _lines(200)
    assert diff_covers_head("", "a\nb\n", 50)  # added
    assert diff_covers_head(_lines(20), _lines(20).replace("line 5\n", "X\n"), 50)  # short file
    assert not diff_covers_head(base, base.replace("line 100\n", "X\n"), 50)  # long file
    assert diff_covers_head(base, base.replace("line 100\n", "X\n"), 150)  # wide context
    assert not diff_covers_head(base, base, 50)  # no change: no hunk
    assert not diff_covers_head("a\n", "", 50)  # empty head: nothing to cover


def test_expanded_diff_marks_covered_files():
    long = _lines(200)
    out = _files(
        {
            ("src/new.py", HEAD): "a\nb\n",
            ("src/short.py", MB): _lines(20),
            ("src/short.py", HEAD): _lines(20).replace("line 5\n", "X\n"),
            ("src/long.py", MB): long,
            ("src/long.py", HEAD): long.replace("line 100\n", "X\n"),
            ("src/moved.py", HEAD): "kept\n",
            ("gone.py", MB): "x\n",
        },
        [
            _f("src/new.py", "added", add=2, dele=0),
            _f("src/short.py"),
            _f("src/long.py"),
            _f("src/moved.py", "renamed", prev="dist/moved.py"),  # base withheld: diffed as added
            _f("gone.py", "removed", add=0, dele=1),
        ],
    )
    assert out["src/new.py"].diff_covers_head
    assert out["src/short.py"].diff_covers_head
    assert not out["src/long.py"].diff_covers_head
    assert out["src/moved.py"].base_withheld and out["src/moved.py"].diff_covers_head
    assert not out["gone.py"].diff_covers_head


def test_an_added_file_keeps_its_head_line_numbers_and_changed_ranges():
    out = _files({("src/new.py", HEAD): _lines(7)}, [_f("src/new.py", "added", add=7, dele=0)])
    f = out["src/new.py"]
    assert "@@ -0,0 +1,7 @@" in f.diff
    assert f.changed_ranges == ((1, 7),)  # findings on any line still locate (§8.6)


# -- no second copy in the prompt --------------------------------------------------


def _build(ins, budget: int = 10_000_000, **kw) -> Prompt:
    out = build_prompt(ins, max_context_tokens=budget, max_diff_lines=2000, nonce=NONCE, **kw)
    assert isinstance(out, Prompt), out
    return out


def _file_blocks(p: Prompt) -> list[str]:
    blocks, _ = parse_blocks(p.user, p.nonce)
    return [c.split("\n", 1)[0].removeprefix("path: ") for k, _, c in blocks if k == "file"]


def _covered(name: str, head: str = "new = 1\n"):
    from dataclasses import replace

    return replace(file_diff(name, head=head, status="added"), diff_covers_head=True)


def test_a_covered_file_is_neither_included_nor_dropped():
    p = _build(inputs(diff=diff_ctx([_covered("src/new.py"), file_diff("src/app.py")])))
    assert _file_blocks(p) == ["src/app.py"]
    assert p.context.full_files_included == ("src/app.py",)
    assert p.context.full_files_dropped == ()


def test_a_covered_file_is_not_counted_on_the_retry():
    p = _build(
        inputs(diff=diff_ctx([_covered("src/new.py"), file_diff("src/app.py")])),
        include_full_files=False,
    )
    assert p.context.full_files_dropped == ("src/app.py",)


def test_riel_632_shape_puts_the_code_files_in_full_once():
    # 3 added docs and 3 added code files are already whole in the diff; 3 modified
    # code files get their full copy.
    files = [_covered(f"workstream/doc{k}.md", "d\n" * 50) for k in range(3)]
    files += [_covered(f"src/added{k}.ts", "a\n" * 50) for k in range(3)]
    files += [file_diff(f"src/mod{k}.ts", head=f"m{k}\n" * 40) for k in range(3)]
    p = _build(inputs(diff=diff_ctx(files)))
    assert sorted(_file_blocks(p)) == ["src/mod0.ts", "src/mod1.ts", "src/mod2.ts"]
    # A budget with room for exactly the three modified files: it only works
    # because the covered files (smaller, so first in the fill) take no room.
    room = sum(u.tokens for u in p.context.placed)  # the PR block is placed first too
    tight = _build(inputs(diff=diff_ctx(files)), p.context.mandatory_tokens + room + 5)
    assert sorted(_file_blocks(tight)) == ["src/mod0.ts", "src/mod1.ts", "src/mod2.ts"]
    assert tight.context.full_files_dropped == ()
    assert tight.tokens <= tight.context.max_context_tokens  # §8.4 step 3


# -- the flag agrees with the emitted diff (qa-engineer, #464 gate) ---------------


def _edit(n: int, *lines: int) -> tuple[str, str]:
    base = _lines(n)
    head = base
    for k in lines:
        head = head.replace(f"line {k}\n", f"LINE {k}\n")
    return base, head


def test_diff_covers_head_boundaries_at_50_lines():
    # One edit on line 1: the hunk reaches line 51. A 52nd line is left out.
    assert diff_covers_head(*_edit(51, 1), 50)
    assert not diff_covers_head(*_edit(52, 1), 50)
    # Edits on the first and last lines: 100 equal lines between them join the
    # hunks; 101 split them and leave exactly one head line (52) unshown.
    assert diff_covers_head(*_edit(102, 1, 102), 50)
    assert not diff_covers_head(*_edit(103, 1, 103), 50)
    assert "@@ -53,51 +53,51 @@" in unified_diff("f", "f", *_edit(103, 1, 103), "modified")


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)
_ALPHABET = ("a\n", "b\n", "c\n", "\n", "d\n")


def _shown_head_lines(diff: str) -> set[int]:
    """Head line numbers inside some hunk of a unified diff (``+start,count``)."""
    shown: set[int] = set()
    for m in _HUNK_RE.finditer(diff):
        start, count = int(m.group(1)), int(m.group(2) or 1)
        shown.update(range(start, start + count))
    return shown


def _random_pair(rng: random.Random) -> tuple[str, str]:
    # Small alphabet so lines repeat; long bases reach SequenceMatcher's autojunk
    # regime (200+ lines), where both difflib paths must still agree.
    size = rng.choice((0, rng.randint(1, 12), rng.randint(13, 199), rng.randint(200, 600)))
    base = [rng.choice(_ALPHABET) for _ in range(size)]
    head = list(base)
    for _ in range(rng.randint(0, 6)):
        pos = rng.randint(0, len(head))
        op = rng.random()
        if op < 0.4:
            head.insert(pos, rng.choice((*_ALPHABET, "e\n")))
        elif head and op < 0.7:
            head.pop(min(pos, len(head) - 1))
        elif head:
            head[min(pos, len(head) - 1)] = rng.choice((*_ALPHABET, "e\n", "x"))
    for lines in (base, head):
        if lines and rng.random() < 0.2:
            lines[-1] = lines[-1].rstrip("\n")  # no final newline
    return "".join(base), "".join(head)


def test_diff_covers_head_agrees_with_the_emitted_diff():
    """Covered iff every head line falls in a hunk ``unified_diff`` emits (seed 464001).

    ``diff_covers_head`` re-derives the hunks with ``get_grouped_opcodes``
    instead of reading ``unified_diff``'s output; a divergence would drop a
    full copy whose lines the model never sees, or send one it already has.
    """
    tactic = Tactic.from_env(tactic_seed(464, 1), 400)
    rng = tactic.rng()
    covered = 0
    for i in range(tactic.iterations):
        base, head = _random_pair(rng)
        context = rng.choice((0, 1, PROSE_CONTEXT_LINES, CONTEXT_LINES, rng.randint(0, 60)))
        if not tactic.selected(i):
            continue
        status = "added" if not base else "modified"
        diff = unified_diff("f.py", "f.py", base, head, status, context=context)
        n = len(split_lines(head))
        expected = n > 0 and set(range(1, n + 1)) <= _shown_head_lines(diff)
        got = diff_covers_head(base, head, context)
        assert got == expected, tactic.context(i, (base, head, context))
        covered += got
    if not tactic.replaying:
        assert 0 < covered < tactic.iterations  # both outcomes are exercised


def test_the_folders_fallback_is_the_default_not_empty():
    """``context_folders`` missing (a caller that skipped ``apply_defaults``) means
    ``docs,workstream``, not "no folders": selection is not silently turned off."""
    from types import SimpleNamespace

    from context.selection import SKIP_TREE_UNAVAILABLE
    from pipeline import Pipeline, PipelineDeps, ReviewRequest, _Gate

    reporter = SimpleNamespace(log=lambda *a, **k: None)
    request = ReviewRequest("r", "acme", "widgets", {"pr_number": 1}, settings=None)  # type: ignore[arg-type]
    pipe = Pipeline(reporter, request, [], PipelineDeps(resolve_token=lambda org: "t"))
    selection = pipe._select(SimpleNamespace(), (), (), None, _Gate())  # type: ignore[arg-type]
    assert selection.reason == SKIP_TREE_UNAVAILABLE  # "" would give no_folders
