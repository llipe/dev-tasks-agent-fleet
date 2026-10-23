"""
Token estimate and line-boundary truncation (D-27, spec §8.4).

The single place the agent counts tokens. There is no Python tokenizer for the
Bedrock OpenAI models, so the estimate is ``ceil(len(text) / 3.5)`` over code
points, conservative by design. S-207 caps issues and the spec with it; S-209's
budget fit (``budget.py``) reuses ``estimate``, ``estimate_len`` and
``truncate`` from here and defines no estimator of its own.
"""

from __future__ import annotations

__all__ = [
    "CHARS_PER_TOKEN",
    "TRUNCATION_MARKER",
    "estimate",
    "estimate_len",
    "max_chars",
    "truncate",
]

CHARS_PER_TOKEN = 3.5
TRUNCATION_MARKER = "[truncated]"
_MARKER_LINE = TRUNCATION_MARKER + "\n"


def estimate(text: str) -> int:
    """``ceil(len(text) / 3.5)``, in integer arithmetic (``3.5 == 7 / 2``)."""
    return estimate_len(len(text))


def estimate_len(length: int) -> int:
    """``estimate`` of any text of ``length`` code points.

    The budget fit (S-209) charges a block from its lengths without building
    the string first. ``ceil`` is subadditive, so blocks charged one by one
    never under-count their concatenation.
    """
    if length < 0:
        raise ValueError("length must be >= 0")
    return (2 * length + 6) // 7


def max_chars(tokens: int) -> int:
    """The longest text length whose estimate is at most ``tokens``."""
    return 7 * tokens // 2


def truncate(text: str, max_tokens: int) -> tuple[str, bool]:
    """``(text, False)`` when it fits; else a prefix plus ``[truncated]``.

    The prefix ends at a line boundary when one fits, and is hard-cut when the
    first line alone is too long. The result's estimate never exceeds
    ``max_tokens``; an allowance with no room beside the marker yields ``""``.
    """
    if max_tokens < 0:
        raise ValueError("max_tokens must be >= 0")
    if estimate(text) <= max_tokens:
        return text, False
    room = max_chars(max_tokens) - len(_MARKER_LINE)
    if room < 1:
        return "", True
    head = text[:room]
    cut = head.rfind("\n")
    if cut >= 0:
        return head[: cut + 1] + _MARKER_LINE, True
    # One line longer than the allowance: hard cut, then end the line.
    return head[: room - 1] + "\n" + _MARKER_LINE, True
