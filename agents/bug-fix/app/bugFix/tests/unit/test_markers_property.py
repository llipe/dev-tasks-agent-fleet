"""RT-02: marker parsing, forgery and open-claim invariants (S-186 AC1, AC2; D-53, D-80).

The race verdict itself (oracle 7) belongs to ``claim.py`` (S-188); the
open-claim set it reads is covered here.
"""

from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from markers import KINDS, REFUSAL_REASONS, Marker, build, open_claims, parse_block

APP_ID = 4242
_CANON = re.compile(
    r"<!-- agent-fleet:bug-fix:(?:(?:claim|disposition|pr) run_id=(?P<a>[0-9a-f]{8}-[0-9a-f]{4}"
    r"-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})|refusal run_id=(?P<b>[0-9a-f]{8}-[0-9a-f]{4}"
    r"-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}) reason=(?:" + "|".join(REFUSAL_REASONS) + r")) -->"
)

run_ids = st.uuids().map(str)
markers_st = st.builds(
    lambda kind, rid, reason: Marker(kind, rid, reason if kind == "refusal" else None),
    st.sampled_from(KINDS),
    run_ids,
    st.sampled_from(REFUSAL_REASONS),
)

# Perturbations applied to a canonical marker line.
_PERTURB = [
    lambda s: " " + s,
    lambda s: "﻿" + s,
    lambda s: "​" + s,
    lambda s: s.replace("-", "‑", 1),
    lambda s: s.replace("<!--", "<!-- <!--"),
    lambda s: s.upper(),
    lambda s: s[:-1],
    lambda s: s + "x",
    lambda s: s.replace("run_id=", "run_id= "),
]


@settings(max_examples=1000, deadline=None)
@given(st.lists(markers_st, min_size=1, max_size=5), st.text(max_size=80), st.booleans())
def test_block_round_trips_and_stops_at_the_first_other_line(block, tail, crlf):
    nl = "\r\n" if crlf else "\n"
    lines = [build(m.kind, m.run_id, m.reason) for m in block]
    body = nl.join(lines) + nl + "visible " + tail
    assert parse_block(body) == tuple(block)


@settings(max_examples=1000, deadline=None)
@given(markers_st, st.sampled_from(range(len(_PERTURB))))
def test_perturbed_marker_never_parses(marker, idx):
    line = _PERTURB[idx](build(marker.kind, marker.run_id, marker.reason))
    parsed = parse_block(line)
    # A marker parses iff the line matches the canonical grammar byte for byte.
    assert bool(parsed) == bool(_CANON.fullmatch(line))


@settings(max_examples=1000, deadline=None)
@given(st.text(max_size=300))
def test_arbitrary_text_parses_only_canonical_lines(text):
    for marker in parse_block(text):
        assert _CANON.fullmatch(build(marker.kind, marker.run_id, marker.reason))
    first = text.split("\n", 1)[0].removesuffix("\r")
    if not _CANON.fullmatch(first):
        assert parse_block(text) == ()


def _comment(cid, marker, trusted_flag):
    body = build(marker.kind, marker.run_id, marker.reason) + "\ntext"
    if trusted_flag:
        return {
            "id": cid,
            "body": body,
            "user": {"type": "Bot"},
            "performed_via_github_app": {"id": APP_ID},
        }
    return {"id": cid, "body": body, "user": {"type": "User"}, "performed_via_github_app": None}


comment_lists = st.lists(
    st.tuples(st.sampled_from(KINDS), st.integers(0, 4), st.booleans()),
    min_size=1,
    max_size=20,
)


@settings(max_examples=1000, deadline=None)
@given(comment_lists, st.lists(run_ids, min_size=5, max_size=5, unique=True), st.randoms())
def test_open_claim_invariants(spec, pool, rnd):
    comments = []
    for cid, (kind, ri, trusted_flag) in enumerate(spec, start=1):
        marker = Marker(kind, pool[ri], "closed" if kind == "refusal" else None)
        comments.append(_comment(cid, marker, trusted_flag))

    result = open_claims(comments, APP_ID)

    # (3) The oracle: trusted claims with no trusted pr/disposition for the run.
    closed = {pool[ri] for kind, ri, t in spec if t and kind in ("pr", "disposition")}
    expected = sorted(
        (cid, pool[ri])
        for cid, (kind, ri, t) in enumerate(spec, start=1)
        if t and kind == "claim" and pool[ri] not in closed
    )
    assert result == expected

    # (4) Permutation invariance.
    shuffled = list(comments)
    rnd.shuffle(shuffled)
    assert open_claims(shuffled, APP_ID) == result

    # (5) An untrusted comment of any kind never changes the set.
    extra = len(comments) + 1
    for kind in KINDS:
        for rid in pool:
            m = Marker(kind, rid, "closed" if kind == "refusal" else None)
            assert open_claims([*comments, _comment(extra, m, False)], APP_ID) == result

    # (6) A trusted refusal never changes the set.
    for rid in pool:
        m = Marker("refusal", rid, "active_run")
        assert open_claims([*comments, _comment(extra, m, True)], APP_ID) == result
