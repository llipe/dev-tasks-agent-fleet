"""RT-15 and RT-12 (6): agent comment bodies (S-186 AC1, AC5; S-185 AC3; D-85, D-104).

S-186 owns the disposition body and S-185 the refusal body. The claim body
(S-188) joins this file in its story.
"""

from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from disposition import Diagnosis, build_body
from issues import MAX_COMMENT_CHARS, utf16_len
from markers import REFUSAL_REASONS, Marker, build, parse_block
from refusal import INVALID_PARAMS_KEYS, REPO_GATE_ITEMS, Refusal, build_reply

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


_NAME = st.from_regex(r"[A-Za-z0-9._-]{1,39}", fullmatch=True).filter(
    lambda n: n not in (".", "..")
)
# DF-185-07: a cross-repo linked PR names its ``owner/name``; ``None`` is this repo.
_PR_REPO = st.one_of(st.none(), st.tuples(_NAME, _NAME).map("/".join))


def _refusal(code: str, pr: int, item: str, key: str, pr_repo: str | None = None) -> Refusal:
    if code == "linked_pr":
        return Refusal(code, pr_number=pr, pr_repo=pr_repo)
    if code == "repo_gate":
        return Refusal(code, detail=item)
    if code == "invalid_params":
        return Refusal(code, detail=key)
    return Refusal(code)


@settings(max_examples=1000, deadline=None)
@given(
    st.uuids().map(str),
    st.sampled_from(REFUSAL_REASONS),
    st.integers(min_value=1, max_value=2**31),
    st.integers(min_value=1, max_value=2**31),
    st.sampled_from(REPO_GATE_ITEMS),
    st.sampled_from(INVALID_PARAMS_KEYS),
    st.one_of(st.none(), st.just("https://panel.example/runs/x"), _MODEL_TEXT),
    _PR_REPO,
)
def test_refusal_body_is_fixed_text_with_its_own_marker(
    run_id, code, issue, pr, item, key, link, pr_repo
):
    refusal = _refusal(code, pr, item, key, pr_repo)
    body = build_reply(run_id, refusal, issue, run_link=link)
    # (1) Its own marker on line 1; the body never starts with the trigger.
    assert body.split("\n", 1)[0] == build("refusal", run_id, code)
    assert not body.startswith("/bug-fix")
    # (3) Parsing yields exactly (kind, run_id, reason).
    assert parse_block(body) == (Marker("refusal", run_id, code),)
    # (2) Fixed text: line 2 starts with the fixed prefix, three lines in all,
    # and a hostile link never reaches the body.
    lines = body.split("\n")
    assert len(lines) == 3
    assert lines[1].startswith("Bug-fix didn't start: ")
    if lines[2] != f"Run: `{run_id}`":
        assert lines[2] == f"Run: {link}"
        assert re.fullmatch(r"https://\S+", link or "")
    assert body.count("<!--") == 1
    if code == "linked_pr":
        ref = f"{pr_repo}#{pr}" if pr_repo else f"#{pr}"
        assert f"pull request {ref} is already open" in lines[1]
