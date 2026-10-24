"""RT-15 and RT-12 (6): agent comment bodies (S-186 AC1, AC5; D-85, D-104).

S-186 owns the disposition body. The claim body (S-188) and the refusal body
(S-185) join this file in their stories.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from disposition import Diagnosis, build_body
from issues import MAX_COMMENT_CHARS, utf16_len
from markers import Marker, build, parse_block

_HOSTILE = st.one_of(
    st.text(max_size=200),
    st.sampled_from(
        [
            "/bug-fix",
            "@octocat",
            "Fixes #1",
            "-->",
            "<!--",
            build("claim", "1c0b3e5f-2d4e-4f60-9b7c-8d9e0f1a2b3c"),
            build("pr", "1c0b3e5f-2d4e-4f60-9b7c-8d9e0f1a2b3c"),
            "\r\n",
            "```",
        ]
    ),
)
_MODEL_TEXT = st.lists(_HOSTILE, max_size=12).map("".join)


@settings(max_examples=1000, deadline=None)
@given(
    st.uuids().map(str),
    _MODEL_TEXT,
    _MODEL_TEXT,
    st.one_of(st.none(), _MODEL_TEXT),
)
def test_disposition_body_has_exactly_its_own_marker(run_id, why, tried, diffstat):
    body = build_body(run_id, Diagnosis(why=why, tried=tried, diffstat=diffstat), [])
    # (1) Its own marker on line 1, so the body never starts with "/bug-fix".
    assert body.split("\n", 1)[0] == build("disposition", run_id)
    assert not body.startswith("/bug-fix")
    # (3)/(4) Parsing yields exactly the marker used to build it.
    assert parse_block(body) == (Marker("disposition", run_id),)
    # Model text can't hide an HTML comment in the posted body.
    assert body.count("<!--") == 1
    assert utf16_len(body) <= MAX_COMMENT_CHARS
