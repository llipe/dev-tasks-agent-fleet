"""
Model-text neutralizer (spec §8.7; D-65, D-85).

Model-written text (a summary, a rationale, a commit message, a diagnosis)
must not cause side effects on GitHub when the wrapper posts it:

- **Closing keywords.** ``close[sd]?``, ``fix(e[sd])?`` or ``resolve[sd]?``,
  in any case, then a colon with optional whitespace or whitespace alone,
  then an issue reference (``#N``, ``owner/repo#N``, a GitHub issue or pull
  URL with or without its scheme, or ``GH-N``) would close that issue when a
  PR merges. A reference wrapped in Markdown (``[#N](url)``, ``**#N**``, a
  code span, ``<url>``) counts too, and the wrapper is kept inside the
  ``(ref …)``. The keyword and the separator are replaced, leaving
  ``(ref <reference>)``; for ``#N`` that is exactly ``(ref #N)``. The
  reference text is kept as written, so a cross-repository reference never
  turns into a wrong local ``#N``. Only the wrapper writes the single
  ``Fixes #<N>`` line.
- **Mentions.** Every ``@`` gets U+200B (zero-width space) after it, so no
  user or team is notified.

The function is idempotent, and text outside a matched span is unchanged.
The keyword match is deliberately wider than GitHub's (a keyword glued to
``_`` or a non-ASCII letter is also neutralized): over-neutralizing only
changes wording, while missing one would close an issue.
"""

from __future__ import annotations

import re

ZWSP = "​"

_REFERENCE = (
    r"(?:"
    r"(?:https?://)?(?:www\.)?github\.com/[^\s/]+/[^\s/]+/(?:issues|pull)/\d+"
    r"|[\w.-]+/[\w.-]+#\d+"
    r"|#\d+"
    r"|GH-\d+"
    r")"
)
# A reference as Markdown may wrap it: a link, emphasis, a code span or an
# autolink. The wrapper is consumed with the reference so the output stays
# well-formed; an unclosed opener is consumed too.
_TARGET = (
    r"(?:"
    r"\[" + _REFERENCE + r"\](?:\([^()\s]*\))?"
    r"|(?P<em>\*{1,2}|_{1,2}|`)" + _REFERENCE + r"(?P=em)"
    r"|<" + _REFERENCE + r">"
    r"|[\[*_`<]*" + _REFERENCE + r")"
)
_CLOSING = re.compile(
    r"(?<![A-Za-z0-9])(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)(?::\s*|\s+)(?P<ref>"
    + _TARGET
    + r")",
    re.IGNORECASE,
)
_AT = re.compile("@(?!" + ZWSP + ")")


def neutralize(text: str) -> str:
    """Return ``text`` with closing references and mentions defused."""
    if not isinstance(text, str):
        raise TypeError("neutralize() needs a str")
    # Repeat to a fixed point: a replacement can expose a keyword that was
    # glued to the previous reference (``#1close #1`` -> ``(ref #1)close #1``).
    # Each pass removes at least one keyword, so the loop terminates.
    while True:
        out = _CLOSING.sub(lambda m: f"(ref {m.group('ref')})", text)
        if out == text:
            break
        text = out
    return _AT.sub("@" + ZWSP, text)
