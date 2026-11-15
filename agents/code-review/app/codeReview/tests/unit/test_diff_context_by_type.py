"""
#463 — ±3 diff context for documentation files, ±50 for everything else (D-68).

The expanded diff is the mandatory budget block. Documentation written one
paragraph per line made ±50 lines of context cost tens of thousands of tokens
for a two-line edit (``llipe/riel#632``: ``TESTING.md`` +4/−2 cost 67,204
tokens), pushing the run over budget so nothing was reviewed. The context is
chosen by the **head** path's extension (``DOC_EXTENSIONS``, any case); code
keeps ±50. Which lines count as changed never depends on the context.
"""

from __future__ import annotations

import pytest

from context.diff import (
    CONTEXT_LINES,
    PROSE_CONTEXT_LINES,
    changed_ranges,
    context_lines_for,
    unified_diff,
)
from context.tokens import estimate
from prompt import LABEL_DIFF, system_prompt
from tests.unit.test_diff import HEAD, MB, Repo, _expand, _f, _lines


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("TESTING.md", 3),
        ("docs/roadmap.md", 3),
        ("README.MD", 3),
        ("guide.mdx", 3),
        ("notes.markdown", 3),
        ("api.rst", 3),
        ("notes.txt", 3),
        ("manual.adoc", 3),
        ("src/app.py", 50),
        ("src/app.ts", 50),
        ("docs/conf.py", 50),  # code under docs/ is code: the extension decides
        ("Makefile", 50),
        ("md", 50),
    ],
)
def test_context_lines_for(path, expected):
    assert context_lines_for(path) == expected
    assert (PROSE_CONTEXT_LINES, CONTEXT_LINES) == (3, 50)


def test_unified_diff_takes_the_context():
    base = _lines(200)
    head = base.replace("line 100\n", "LINE 100\n")
    out = unified_diff("a.md", "a.md", base, head, "modified", context=3)
    lines = out.splitlines()
    assert lines[2] == "@@ -97,7 +97,7 @@"
    assert lines[3] == " line 97" and lines[-1] == " line 103"


def _md_and_py(repo_files: dict, files: list) -> dict:
    ctx = _expand(Repo(repo_files), files)
    return {f.filename: f for f in ctx.files}


def test_a_doc_file_gets_3_lines_and_code_gets_50():
    base, head = _lines(200), _lines(200).replace("line 100\n", "LINE 100\n")
    out = _md_and_py(
        {
            ("TESTING.md", MB): base,
            ("TESTING.md", HEAD): head,
            ("app.py", MB): base,
            ("app.py", HEAD): head,
        },
        [_f("TESTING.md"), _f("app.py")],
    )
    assert out["TESTING.md"].diff.splitlines()[2] == "@@ -97,7 +97,7 @@"
    assert out["app.py"].diff.splitlines()[2] == "@@ -50,101 +50,101 @@"


def test_the_head_path_decides_on_a_rename():
    base, head = _lines(200), _lines(200).replace("line 100\n", "LINE 100\n")
    out = _md_and_py(
        {
            ("old.md", MB): base,
            ("new.ts", HEAD): head,
            ("old.ts", MB): base,
            ("new.md", HEAD): head,
        },
        [_f("new.ts", "renamed", prev="old.md"), _f("new.md", "renamed", prev="old.ts")],
    )
    assert out["new.ts"].diff.splitlines()[2] == "@@ -50,101 +50,101 @@"
    assert out["new.md"].diff.splitlines()[2] == "@@ -97,7 +97,7 @@"


def test_added_and_removed_doc_files_are_whole_as_before():
    text = _lines(30)
    out = _md_and_py(
        {("new.md", HEAD): text, ("gone.md", MB): text},
        [_f("new.md", "added", add=30, dele=0), _f("gone.md", "removed", add=0, dele=30)],
    )
    added = out["new.md"].diff.splitlines()[3:]
    removed = out["gone.md"].diff.splitlines()[3:]
    assert len(added) == 30 and all(ln.startswith("+") for ln in added)
    assert len(removed) == 30 and all(ln.startswith("-") for ln in removed)


def test_changed_ranges_do_not_depend_on_the_context():
    base = _lines(300)
    head = (
        base.replace("line 10\n", "X\n").replace("line 150\n", "Y\nZ\n").replace("line 290\n", "")
    )
    out = _md_and_py(
        {("a.md", MB): base, ("a.md", HEAD): head, ("a.py", MB): base, ("a.py", HEAD): head},
        [_f("a.md"), _f("a.py")],
    )
    assert out["a.md"].changed_ranges == out["a.py"].changed_ranges == changed_ranges(base, head)


def test_riel_632_shaped_long_line_doc_costs_under_40_percent():
    # TESTING.md-like: 300 paragraph-per-line rows of ~1,500 characters, a 4-line edit.
    rows = [f"| row {k} | " + ("lorem ipsum " * 125) + "|\n" for k in range(300)]
    base = "".join(rows)
    head = base.replace(rows[150], "| row 150 | changed |\n").replace(
        rows[151], "| row 151 | changed |\n"
    )
    wide = unified_diff("TESTING.md", "TESTING.md", base, head, "modified", context=CONTEXT_LINES)
    narrow = unified_diff(
        "TESTING.md", "TESTING.md", base, head, "modified", context=PROSE_CONTEXT_LINES
    )
    assert estimate(narrow) < 0.4 * estimate(wide)
    # Plus code, as on riel#632: the code keeps ±50, and the PR's whole diff
    # still costs under 40% of what ±50 everywhere did (#463 AC-5).
    code_base = _lines(300)
    code_head = code_base.replace("line 150\n", "LINE 150\n")
    out = _md_and_py(
        {
            ("TESTING.md", MB): base,
            ("TESTING.md", HEAD): head,
            ("src/app.py", MB): code_base,
            ("src/app.py", HEAD): code_head,
        },
        [_f("TESTING.md"), _f("src/app.py")],
    )
    assert out["TESTING.md"].diff == narrow
    code_wide = unified_diff("src/app.py", "src/app.py", code_base, code_head, "modified")
    assert out["src/app.py"].diff == code_wide
    before = estimate(wide) + estimate(code_wide)
    after = estimate(out["TESTING.md"].diff) + estimate(out["src/app.py"].diff)
    assert after < 0.4 * before


def test_the_prompt_states_both_widths():
    """The model is told the context it gets: ±50 for code, ±3 for documentation (qa gate)."""
    assert (
        f"±{CONTEXT_LINES} lines of context for code, ±{PROSE_CONTEXT_LINES} for documentation"
        in (LABEL_DIFF)
    )
    flat = " ".join(system_prompt().split())
    assert (
        f"with {CONTEXT_LINES} lines of context for code and {PROSE_CONTEXT_LINES} for documentation"
        in flat
    )
