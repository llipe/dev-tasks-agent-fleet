"""
Markdown structure shared by the context readers (S-208; DR-10).

``FenceTracker`` follows CommonMark fenced code blocks line by line, so the spec
trimmer (``context.spec``, S-207) and the drift parser (``context.verifier``,
S-208) agree on what is code:

- an opener is 0-3 spaces, then 3 or more backticks or tildes; the rest of
  the line is the info string, and a backtick opener's info string may not
  contain a backtick (such a line is inline code, not a fence; QA D4, DR-10);
- a closer uses the opener's character, is at least as long, and has only
  whitespace after it; anything else inside the fence is code;
- an unclosed fence runs to the end of the document.

Lines are passed without their ``\\n``; a trailing ``\\r`` counts as whitespace.
The regex is linear in the line length.
"""

from __future__ import annotations

import re

__all__ = ["FENCE_RE", "FenceTracker"]

FENCE_RE = re.compile(r" {0,3}(`{3,}|~{3,})")


class FenceTracker:
    """Feed lines in order; ``step`` says whether each one is part of a fence."""

    def __init__(self) -> None:
        self.open: str | None = None  # the opening fence run while inside one

    def step(self, line: str) -> bool:
        """``True`` when ``line`` is part of a fence (its opener and closer too)."""
        m = FENCE_RE.match(line)
        if self.open is not None:
            if (
                m is not None
                and m.group(1)[0] == self.open[0]
                and len(m.group(1)) >= len(self.open)
                and not line[m.end() :].strip()
            ):
                self.open = None
            return True
        if m is not None:
            fence = m.group(1)
            if fence[0] == "`" and "`" in line[m.end() :]:
                return False
            self.open = fence
            return True
        return False
