"""RT-02: marker parsing, forgery, open-claim and race invariants
(S-186 AC1, AC2; S-188 AC2; D-53, D-54, D-80).

One open-claim rule (DF-33, confirmed by @llipe 2026-10-24): a trusted claim
for run R is open until a trusted ``pr``, ``disposition`` or ``refusal`` marker
for R exists. Oracle (7), the race verdict, runs ``claim.race_winner``.
"""

from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from claim import race_winner
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

    # (3) The oracle: trusted claims with no trusted pr/disposition/refusal for the run.
    closed = {pool[ri] for kind, ri, t in spec if t and kind in ("pr", "disposition", "refusal")}
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

    # (6) A trusted refusal never opens a claim: it only closes its own run's.
    for rid in pool:
        m = Marker("refusal", rid, "active_run")
        got = open_claims([*comments, _comment(extra, m, True)], APP_ID)
        assert got == [(cid, r) for cid, r in result if r != rid]


STATUSES = ("queued", "running", "succeeded", "failed", "timed_out", "canceled", None)


@settings(max_examples=1000, deadline=None)
@given(
    comment_lists,
    st.lists(run_ids, min_size=5, max_size=5, unique=True),
    st.lists(st.sampled_from(STATUSES), min_size=5, max_size=5),
    st.integers(1, 21),
    st.randoms(),
)
def test_race_verdict(spec, pool, statuses, own_cid, rnd):
    # (7) This run (pool[0], comment own_cid) loses iff an open claim with a
    # lower comment id belongs to another, non-terminal run. A missing v_runs
    # row counts as finished (CT-34).
    own = pool[0]
    comments = []
    for cid, (kind, ri, trusted_flag) in enumerate(spec, start=1):
        marker = Marker(kind, pool[ri], "closed" if kind == "refusal" else None)
        comments.append(_comment(cid, marker, trusted_flag))
    status_of = {rid: s for rid, s in zip(pool, statuses, strict=True) if s is not None}

    def read(ids):
        return {i: status_of[i] for i in ids if i in status_of}

    rnd.shuffle(comments)
    winner = race_winner(comments, APP_ID, own, own_cid, read, warn=lambda _m: None)

    active = [
        (cid, rid)
        for cid, rid in open_claims(comments, APP_ID)
        if cid < own_cid and rid != own and status_of.get(rid) in ("queued", "running")
    ]
    assert (winner is not None) == bool(active)
    if winner is not None:
        assert winner == active[0][1]
    # (5) An untrusted comment of any kind never changes the verdict.
    for kind in KINDS:
        m = Marker(kind, pool[1], "closed" if kind == "refusal" else None)
        forged = [*comments, _comment(max(own_cid - 1, 1) if kind == "claim" else 99, m, False)]
        assert race_winner(forged, APP_ID, own, own_cid, read, warn=lambda _m: None) == winner
