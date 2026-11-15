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

from context.diff import diff_covers_head
from prompt import Prompt, build_prompt
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
    assert p.tokens <= 10_000_000  # the budget invariant (§8.4 step 3) still holds
