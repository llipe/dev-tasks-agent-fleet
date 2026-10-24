"""
D-27 / spec §8.4 — the one token estimator and line-boundary truncation (S-207).

``estimate(text) = ceil(len(text) / 3.5)``. ``truncate`` cuts at a line
boundary and appends ``[truncated]`` so the result never exceeds the allowance.
S-209's budget fit reuses both from ``context/tokens.py``.
"""

from __future__ import annotations

import pytest

from context.tokens import TRUNCATION_MARKER, estimate, max_chars, truncate


@pytest.mark.parametrize(
    ("chars", "tokens"),
    [(0, 0), (1, 1), (3, 1), (4, 2), (7, 2), (8, 3), (28_000, 8_000), (28_001, 8_001)],
)
def test_estimate_is_ceil_of_chars_over_3_5(chars, tokens):
    assert estimate("x" * chars) == tokens


def test_estimate_counts_code_points_not_bytes():
    assert estimate("é" * 7) == 2


@pytest.mark.parametrize("tokens", [0, 1, 2, 3, 8_000])
def test_max_chars_is_the_largest_length_within_the_estimate(tokens):
    n = max_chars(tokens)
    assert estimate("x" * n) <= tokens
    assert estimate("x" * (n + 1)) > tokens


def test_truncate_keeps_text_within_the_allowance_whole():
    text = "a\nb\n"
    assert truncate(text, estimate(text)) == (text, False)


def test_truncate_cuts_at_a_line_boundary_and_appends_the_marker():
    text = "".join(f"line {i:03d}\n" for i in range(100))
    out, cut = truncate(text, 50)
    assert cut is True
    assert estimate(out) <= 50
    assert out.endswith(TRUNCATION_MARKER + "\n")
    kept = out[: -len(TRUNCATION_MARKER) - 1]
    assert text.startswith(kept) and kept.endswith("\n")


def test_truncate_hard_cuts_a_single_long_line():
    out, cut = truncate("y" * 1_000, 20)
    assert cut is True
    assert estimate(out) <= 20
    assert out.startswith("y") and out.endswith(TRUNCATION_MARKER + "\n")


def test_truncate_to_less_than_the_marker_returns_empty():
    assert truncate("z" * 100, 1) == ("", True)


def test_truncate_rejects_a_negative_allowance():
    with pytest.raises(ValueError):
        truncate("x", -1)
