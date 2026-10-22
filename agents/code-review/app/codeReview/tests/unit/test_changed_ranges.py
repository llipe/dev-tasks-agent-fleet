"""
S-206 AC5 — changed head line ranges (TC-206-15, EC-07).

``changed_ranges(base, head)`` returns 1-based, inclusive ``(start, end)``
ranges of head lines touched by the change, from the same matcher as the
0-context diff. S-211 uses them for the location check.

EC-07 decision (pure deletion): a deletion has no head line of its own, so it
is anchored to the head line just after the deletion point, or to the last
head line when the deletion is at the end of the file. A deletion that leaves
the head empty has no range. Overlapping or touching ranges are merged.
"""

from __future__ import annotations

import difflib
import re

import pytest

from context.diff import changed_ranges, split_lines


def _lines(n: int) -> str:
    return "".join(f"l{i}\n" for i in range(1, n + 1))


def test_modified_line_is_a_single_line_range():
    base = _lines(10)
    assert changed_ranges(base, base.replace("l4\n", "L4\n")) == ((4, 4),)


def test_inserted_block_is_its_head_range():
    base = _lines(10)
    head = base.replace("l5\n", "l5\nn1\nn2\nn3\n")
    assert changed_ranges(base, head) == ((6, 8),)


def test_added_file_is_the_whole_file():
    assert changed_ranges("", _lines(7)) == ((1, 7),)


def test_empty_head_has_no_range():
    assert changed_ranges(_lines(3), "") == ()
    assert changed_ranges("", "") == ()


def test_unchanged_has_no_range():
    assert changed_ranges(_lines(5), _lines(5)) == ()


def test_pure_deletion_is_anchored_to_the_next_head_line():
    base = _lines(10)
    head = base.replace("l4\nl5\n", "")  # head line 4 is now "l6"
    assert changed_ranges(base, head) == ((4, 4),)


def test_pure_deletion_at_end_of_file_is_anchored_to_the_last_head_line():
    base = _lines(10)
    head = _lines(8)
    assert changed_ranges(base, head) == ((8, 8),)


def test_pure_deletion_at_start_is_anchored_to_line_one():
    assert changed_ranges(_lines(5), "l3\nl4\nl5\n") == ((1, 1),)


def test_touching_ranges_are_merged_and_sorted():
    base = _lines(20)
    head = base.replace("l3\n", "L3\n").replace("l4\n", "L4\n").replace("l15\n", "L15\n")
    assert changed_ranges(base, head) == ((3, 4), (15, 15))


def test_deletion_anchor_merges_with_an_adjacent_edit():
    base = _lines(10)
    head = base.replace("l4\n", "").replace("l5\n", "L5\n")
    assert changed_ranges(base, head) == ((4, 4),)


def test_crlf_and_missing_eof_newline():
    assert changed_ranges("a\r\nb\r\n", "a\r\nB\r\n") == ((2, 2),)
    assert changed_ranges("a\nb", "a\nb\n") == ((2, 2),)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", []),
        ("a", ["a"]),
        ("a\n", ["a\n"]),
        ("a\nb", ["a\n", "b"]),
        ("a\r\nb\r\n", ["a\r\n", "b\r\n"]),
        ("a b\n", ["a b\n"]),
        ("\n\n", ["\n", "\n"]),
    ],
)
def test_split_lines_splits_on_newline_only(text, expected):
    assert split_lines(text) == expected
    assert "".join(split_lines(text)) == text


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _ranges_from_zero_context_diff(base: str, head: str) -> set[int]:
    """Head lines named by ``difflib.unified_diff(n=0)`` hunks (non-empty ones)."""
    touched: set[int] = set()
    for line in difflib.unified_diff(split_lines(base), split_lines(head), n=0):
        m = _HUNK.match(line)
        if m:
            start, length = int(m.group(1)), int(m.group(2) or "1")
            touched.update(range(start, start + length))
    return touched


def test_non_deletion_ranges_match_the_zero_context_diff():
    base = _lines(60)
    head = base.replace("l2\n", "X\n").replace("l30\n", "l30\nY\nZ\n").replace("l50\n", "W\n")
    covered = {n for a, b in changed_ranges(base, head) for n in range(a, b + 1)}
    assert covered == _ranges_from_zero_context_diff(base, head)
