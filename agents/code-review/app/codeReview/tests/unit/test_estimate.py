"""
S-209 AC1 — ``estimate(text) = ceil(len(text) / 3.5)`` (D-27, TC-209-01).

The budget fit has one token estimator, ``context/tokens.estimate``. ``budget``
re-exports that function and never defines its own, so these tests exercise
the one implementation through both names.
"""

from __future__ import annotations

import math

import pytest

import budget
from context import tokens
from context.tokens import estimate, estimate_len


def test_budget_reexports_the_one_estimator():
    assert budget.estimate is tokens.estimate
    assert budget.estimate_len is tokens.estimate_len


@pytest.mark.parametrize(
    ("chars", "expected"),
    [(0, 0), (1, 1), (7, 2), (8, 3), (3_500, 1_000), (3_501, 1_001)],
)
def test_estimate_values_from_the_test_plan(chars, expected):
    assert estimate("x" * chars) == expected
    assert budget.estimate("x" * chars) == expected


def test_estimate_of_the_empty_string_is_zero():
    assert estimate("") == 0


def test_multi_byte_characters_count_by_code_point():
    # 7 code points, 14 UTF-8 bytes, 1 emoji of 4 bytes: still len() based.
    assert estimate("é" * 7) == 2
    assert estimate("\U0001f600" * 7) == 2
    assert estimate("é" * 8) == 3


@pytest.mark.parametrize("n", [0, 1, 2, 3, 4, 5, 6, 7, 99, 1_000, 28_001, 1_400_000])
def test_estimate_is_the_exact_ceiling(n):
    assert estimate("a" * n) == math.ceil(n / 3.5)
    assert estimate_len(n) == estimate("a" * n)


def test_estimate_len_rejects_a_negative_length():
    with pytest.raises(ValueError):
        estimate_len(-1)


@pytest.mark.parametrize(("a", "b"), [(0, 0), (1, 1), (3, 4), (5, 9), (100, 3), (7, 7)])
def test_estimate_is_subadditive(a, b):
    # The fit charges each block separately; the prompt is their concatenation.
    assert estimate_len(a + b) <= estimate_len(a) + estimate_len(b)
