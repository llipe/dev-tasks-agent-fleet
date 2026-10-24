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
# The keyword-boundary rule (no ASCII letter or digit just before the
# keyword) is applied in ``_pass``, so a keyword glued to the end of the
# previous replacement can be accepted in the same pass.
_CLOSING = re.compile(
    r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)(?::\s*|\s+)(?P<ref>" + _TARGET + r")",
    re.IGNORECASE,
)
_AT = re.compile("@(?!" + ZWSP + ")")


def _glued(text: str, start: int) -> bool:
    if start == 0:
        return False
    before = text[start - 1]
    return before.isascii() and before.isalnum()


def _pass(text: str) -> str:
    """One left-to-right replacement pass.

    A keyword glued to the end of the previous replacement counts as free:
    the replacement ends with ``)``, so the next pass would accept it anyway.
    Accepting it now keeps a ``close #1close #1…`` chain linear instead of
    one pass per link (65,536 characters took ~14 s).
    """
    out: list[str] = []
    pos = 0  # end of the text already copied to ``out``
    i = 0
    while True:
        m = _CLOSING.search(text, i)
        if m is None:
            break
        if m.start() != pos and _glued(text, m.start()):
            i = m.start() + 1
            continue
        out.append(text[pos : m.start()])
        out.append(f"(ref {m.group('ref')})")
        pos = i = m.end()
    out.append(text[pos:])
    return "".join(out)


def neutralize(text: str) -> str:
    """Return ``text`` with closing references and mentions defused."""
    if not isinstance(text, str):
        raise TypeError("neutralize() needs a str")
    # Repeat to a fixed point: a replacement can expose a keyword, for example
    # inside a reference it consumed. Each pass removes at least one keyword,
    # so the loop terminates.
    while True:
        out = _pass(text)
        if out == text:
            break
        text = out
    return _AT.sub("@" + ZWSP, text)
