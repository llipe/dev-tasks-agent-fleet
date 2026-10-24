"""RT-12: model-text neutralizer properties (S-186 AC4; D-65, D-85).

Oracles (1)-(4) here. (6), "a diagnosis built from neutralized text has exactly
one parseable marker", is checked in ``test_comment_bodies_property.py``; (5),
the PR body, belongs to S-194.
"""

from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from neutralize import ZWSP, neutralize

# GitHub's closing-reference grammar, written independently of the module: a
# keyword at a word boundary, an optional colon, whitespace, then a reference.
_CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+"
    r"(?:#\d+|[\w.-]+/[\w.-]+#\d+|https?://(?:www\.)?github\.com/\S+/(?:issues|pull)/\d+|GH-\d+)",
    re.IGNORECASE,
)

_KW = st.sampled_from(
    ["close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved"]
).flatmap(lambda k: st.sampled_from([k, k.upper(), k.capitalize()]))
_REF = st.one_of(
    st.integers(1, 99999).map(lambda n: f"#{n}"),
    st.integers(1, 999).map(lambda n: f"o/r#{n}"),
    st.integers(1, 999).map(lambda n: f"https://github.com/o/r/issues/{n}"),
    st.integers(1, 999).map(lambda n: f"GH-{n}"),
)
_CLOSER = st.tuples(_KW, st.sampled_from(["", ":"]), st.sampled_from([" ", "  ", "\n"]), _REF).map(
    "".join
)
_PIECES = st.one_of(
    st.text(max_size=40),
    _CLOSER,
    st.sampled_from(["@octocat", "a@b.c", "```", "<!-- agent-fleet:bug-fix:claim run_id=x -->"]),
)
_TEXT = st.lists(_PIECES, max_size=25).map("".join)


@settings(max_examples=2000, deadline=None)
@given(_TEXT)
def test_no_closing_reference_survives(text):
    assert _CLOSING.search(neutralize(text)) is None


@settings(max_examples=2000, deadline=None)
@given(_TEXT)
def test_every_at_is_followed_by_zwsp(text):
    out = neutralize(text)
    assert all(out[i + 1 : i + 2] == ZWSP for i, ch in enumerate(out) if ch == "@")


@settings(max_examples=2000, deadline=None)
@given(_TEXT)
def test_idempotent(text):
    once = neutralize(text)
    assert neutralize(once) == once


@settings(max_examples=1000, deadline=None)
@given(st.text(alphabet=st.characters(blacklist_characters="@#/:-"), max_size=200))
def test_text_without_references_or_mentions_is_unchanged(text):
    # (4) Text outside a matched span is preserved byte for byte: with no
    # reference character and no "@", nothing matches.
    assert neutralize(text) == text
