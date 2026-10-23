"""
S-211 hostile-input pass (qa-engineer completion gate, issue #413).

Attacks the guarantee "no scenario, no block; a blocking finding must point at
changed code; stale drift can be filtered but never ignored" (PRD §8, FR-23,
spec §8.6, §8.7, D-08, D-15, D-33, D-37) beyond the TC-211-* rows and RT-08.

Seeded tactics use ``tests/helpers/prng.py`` with seeds ``413 x 1000 + k``:

- 413002: verdict monotonicity under added findings and checks;
- 413003: the location check against a brute-force oracle (unsorted,
  overlapping, adjacent and duplicate ranges, swapped and huge lines);
- 413004: path matching against an independent oracle of the documented
  normalization, over look-alike, NFC/NFD, whitespace, separator, case,
  ``..`` and escaped-control-character variants;
- 413005: counts conservation, fixed keys, integer leaves, no finding text.

Replay one iteration: ``PRNG_SEED=<seed> PRNG_ITER=<i> make test-unit -k <test>``.

Pinned defects (``xfail(strict=True)``; the fix turns XPASS into a failure,
so the marker must be removed with it). Fixed: QA-211-D1 by D-50 (a blocking
span is at most ``MAX_BLOCKING_SPAN`` = 200 lines), so its marker is gone.

- QA-211-D1 (fixed, D-50), location bypass by a huge span. Pinned decision 8 says "a span
  from 1 to ``10**300`` intersects every range". So a blocking finding whose
  span is ``[1, 10**300]`` passes the location check on every reviewed file
  that has at least one changed line, wherever the changed line is. For such
  findings the check reduces to "the file has a changed line". The finding
  then points at the whole file, not at changed code, and the story's
  guarantee (a blocking finding exists "only when it points at changed code")
  is not enforced. The pinned cases are ones any reasonable bound rejects. A
  span of a million lines or more around a single changed line is never a
  location. The bound itself is for the planner to choose: a maximum span
  length, or an endpoint inside the ±3 window.

Characterized, not pinned (planner questions, see the report):

- placeholder scenarios: resolved by D-51 (blank means no letter or number),
  so ``"."`` and ``"-"`` are blank and ``"N/A"`` and ``"none"`` are not;
- ``escape_path`` collisions: fixed (gap 3). ``\\`` is escaped too, so a
  literal ``a\\nb.py`` and ``a<LF>b.py`` render differently, and the escaped
  form decides the match.
"""

from __future__ import annotations

import json
import random
import time
import unicodedata

import pytest

from context.diff import escape_path
from context.verifier import Candidate
from findings_schema import CATEGORIES, SEVERITIES, SchemaViolation
from tests.helpers.prng import Tactic, tactic_seed
from validate import (
    DOWNGRADE_OUTSIDE_DIFF,
    DOWNGRADE_REASONS,
    DROP_NOT_REVIEWED,
    DROP_REASONS,
    STATUS_CONFIRMED,
    STATUS_NOT_REPRODUCED,
    STATUSES,
    VERDICT_BLOCKING,
    VERDICT_CLEAR,
    in_changed_range,
    is_blank,
    match_reviewed,
    normalize_file,
    validate,
)

ONE_LINE = {"src/a.py": ((500, 500),)}


def finding(**overrides):
    base = {
        "severity": "blocking",
        "category": "correctness",
        "file": "src/a.py",
        "line_start": 500,
        "line_end": 500,
        "title": "Off-by-one",
        "failure_scenario": "Given n = 10 the loop reads index 10 and raises IndexError.",
        "consequence": "The request fails with a 500.",
        "rank": 1,
    }
    base.update(overrides)
    return base


def check(cid, status=STATUS_CONFIRMED, reason="seen at head"):
    return {"candidate_id": cid, "status": status, "reason": reason}


def cand(k: int) -> Candidate:
    return Candidate(f"V{k}", "workstream/fidelity-report-S-1.md", k, k + 10, f"| row {k} |", False)


def run(findings=(), *, ranges=ONE_LINE, checks=(), shown=(), dropped=(), max_suggestions=5):
    return validate(
        {"findings": list(findings), "verifier_checks": list(checks)},
        changed_ranges=ranges,
        shown_candidates=tuple(shown),
        dropped_candidates=tuple(dropped),
        max_suggestions=max_suggestions,
    )


def only(result):
    assert len(result.findings) == 1, result
    return result.findings[0]


# ---------------------------------------------------------------------------
# 1. Location bypass (pinned decision 8) and line edges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end"),
    [(1, 10**300), (10**300, 1), (1, 10**6)],
    ids=["1-to-1e300", "swapped-1e300-to-1", "1-to-1e6"],
)
def test_qa211_d1_a_huge_span_around_one_changed_line_is_not_a_location(start, end):
    # One changed line (500) in the whole file. A span of a million lines or
    # more around it does not point at changed code.
    kept = only(run([finding(line_start=start, line_end=end)]))
    assert (kept.severity, kept.downgraded) == ("suggestion", DOWNGRADE_OUTSIDE_DIFF)


def test_a_huge_span_on_a_file_with_no_changed_range_is_always_outside_diff():
    """Whatever bound fixes D1, a reviewed file with no changed range (a pure
    rename or a removed file) never anchors a blocking finding, whatever span
    the model gives. This holds today and must hold after the fix.
    """
    rng = random.Random(tactic_seed(413, 6))
    for _ in range(300):
        line = rng.randint(1, 10**6)
        ranges = {"src/a.py": ((line, line + rng.randint(0, 5)),), "docs/renamed.md": ()}
        span = rng.choice([(1, 10**300), (10**300, 1), (1, line), (line, line)])
        kept = only(
            run(
                [finding(file="docs/renamed.md", line_start=span[0], line_end=span[1])],
                ranges=ranges,
            )
        )
        assert (kept.severity, kept.downgraded) == ("suggestion", DOWNGRADE_OUTSIDE_DIFF)


@pytest.mark.parametrize(
    ("ranges", "line", "blocking"),
    [
        (((1, 1),), 1, True),
        (((1, 1),), 4, True),
        (((1, 1),), 5, False),
        (((2, 3),), 1, True),  # the widened start is below 1
        (((10, 10), (17, 17)), 13, True),  # 13 is +3 of 10 and -4 of 17
        (((10, 10), (17, 17)), 14, True),  # +4 of 10, -3 of 17
        (((10, 10), (18, 18)), 14, False),  # +4 of 10, -4 of 18: in the gap
        (((10, 10), (18, 18)), 15, True),
    ],
)
def test_single_line_spans_at_the_widened_edges(ranges, line, blocking):
    kept = only(run([finding(line_start=line, line_end=line)], ranges={"src/a.py": ranges}))
    assert (kept.severity == "blocking") is blocking


@pytest.mark.parametrize("field", ["line_start", "line_end", "rank"])
@pytest.mark.parametrize("bad", [0, -1, -(10**300), True, False, 1.0, "5", None])
def test_zero_negative_and_non_integer_lines_are_rejected_not_trusted(field, bad):
    with pytest.raises(SchemaViolation):
        run([finding(**{field: bad})])


def _oracle_hits(start: int, end: int, ranges) -> bool:
    lo, hi = min(start, end), max(start, end)
    return any(a - 3 <= hi and lo <= b + 3 for a, b in ranges)


def test_location_check_matches_a_brute_force_oracle_on_hostile_ranges():
    tactic = Tactic.from_env(tactic_seed(413, 3), 2_000)
    rng = tactic.rng()
    for i in range(tactic.iterations):
        ranges = []
        for _ in range(rng.randint(0, 8)):
            a = rng.randint(1, 60)
            ranges.append((a, a + rng.choice([0, 0, 1, 3, 7])))
        if ranges and rng.random() < 0.3:
            ranges.append(rng.choice(ranges))  # duplicates
        rng.shuffle(ranges)  # unsorted
        start = rng.choice([1, rng.randint(1, 80), 10**300])
        end = rng.choice([start, rng.randint(1, 80), 10**300])
        if not tactic.selected(i):
            continue
        value = (ranges, start, end)
        assert in_changed_range(start, end, ranges) is _oracle_hits(start, end, ranges), (
            tactic.context(i, value)
        )


# ---------------------------------------------------------------------------
# 2. Path matching: no finding attaches to a file the model did not name
# ---------------------------------------------------------------------------

NFC = unicodedata.normalize("NFC", "src/café.py")
NFD = unicodedata.normalize("NFD", "src/café.py")
assert NFC != NFD

REVIEWED = {
    "src/a.py": ((500, 500),),
    NFC: ((1, 1),),
    "src/x\x1by.py": ((1, 1),),
}

HOSTILE = [
    "src/а.py",  # Cyrillic a
    "ѕrc/a.py",  # Cyrillic dze for s
    "src/a.рy",  # Cyrillic er for p
    "src／a.py",  # fullwidth solidus
    "src∕a.py",  # division slash
    NFD,  # NFD of a reviewed NFC path
    "src/a.py ",
    " src/a.py",
    "src/a.py\t",
    "src/a.py\n",
    "src/a.py ",
    "src/a.py​",
    "​src/a.py",
    "﻿src/a.py",
    "src/a.py\x00",
    "src\\a.py",
    ".\\src\\a.py",
    "SRC/A.PY",
    "src/A.py",
    "src/../src/a.py",
    "../src/a.py",
    "./../src/a.py",
    "src/./a.py",
    "src//a.py",
    "src/a.py/",
    "src/a.py:500",
    "src/a.py#L500",
    "a/src/a.py",  # diff-header prefix
    "b/src/a.py",
    "src/x\\u001by.py",  # another escape spelling than escape_path's \x1b
    "src/x\\x1By.py",  # hex case differs from escape_path's output
    "src/x\\\\x1by.py",
]


@pytest.mark.parametrize("raw", HOSTILE, ids=[ascii(r) for r in HOSTILE])
def test_hostile_path_variants_match_no_reviewed_file_and_are_dropped(raw):
    assert match_reviewed(raw, REVIEWED) is None
    result = run([finding(file=raw)], ranges=REVIEWED)
    assert result.findings == ()
    assert [d.reason for d in result.dropped] == [DROP_NOT_REVIEWED]
    assert result.dropped[0].file == raw  # raw model text, for S-212 to neutralize


def test_nfc_and_nfd_reviewed_paths_stay_distinct():
    ranges = {NFC: ((1, 1),), NFD: ((900, 900),)}
    assert match_reviewed(NFC, ranges) == NFC
    assert match_reviewed(NFD, ranges) == NFD
    kept = only(run([finding(file=NFD, line_start=1, line_end=1)], ranges=ranges))
    assert kept.file == NFD
    assert kept.downgraded == DOWNGRADE_OUTSIDE_DIFF  # checked against NFD's ranges, not NFC's


def test_case_distinct_reviewed_paths_each_attach_to_their_own():
    ranges = {"README.md": ((1, 1),), "readme.md": ((900, 900),)}
    kept = only(run([finding(file="readme.md", line_start=1, line_end=1)], ranges=ranges))
    assert (kept.file, kept.downgraded) == ("readme.md", DOWNGRADE_OUTSIDE_DIFF)


def test_the_escaped_form_attaches_only_to_the_control_character_file():
    kept = only(run([finding(file="src/x\\x1by.py", line_start=1, line_end=1)], ranges=REVIEWED))
    assert (kept.file, kept.severity) == ("src/x\x1by.py", "blocking")
    kept = only(
        run([finding(file="`./src/x\\x1by.py`", line_start=1, line_end=1)], ranges=REVIEWED)
    )
    assert kept.file == "src/x\x1by.py"


def test_escape_collision_is_gone_and_the_escaped_form_decides():
    """Gap 3 fixed: ``escape_path`` escapes ``\\``, so it is injective.

    ``a<LF>b.py`` renders as ``a\\nb.py`` and the literal ``a\\nb.py`` as
    ``a\\\\nb.py``; the two headers differ. Matching tries the escaped form
    first (what the diff and the prompt show), so the model's copy of each
    header attaches to its own file. (A reviewed path never holds ``\\`` in
    production: the client guard refuses it, so the file is content
    unavailable.)
    """
    control, literal = "a\nb.py", "a\\nb.py"
    assert escape_path(control) != escape_path(literal)
    ranges = {control: ((1, 1),), literal: ((900, 900),)}
    kept = only(run([finding(file=escape_path(control), line_start=1, line_end=1)], ranges=ranges))
    assert (kept.file, kept.severity) == (control, "blocking")
    kept = only(run([finding(file=escape_path(literal), line_start=1, line_end=1)], ranges=ranges))
    assert (kept.file, kept.downgraded) == (literal, DOWNGRADE_OUTSIDE_DIFF)
    kept = only(run([finding(file=control, line_start=1, line_end=1)], ranges=ranges))
    assert (kept.file, kept.severity) == (control, "blocking")


def _oracle_match(raw: str, reviewed: list[str]) -> str | None:
    """The documented rule, written independently of ``validate``."""

    def norm(s: str) -> str:
        s = s.strip("`")
        while True:
            if s.startswith("./"):
                s = s[2:]
            elif s.startswith("/"):
                s = s[1:]
            else:
                return s

    for form in (raw, norm(raw)):
        for p in reviewed:  # the escaped form (what the model sees) first
            if escape_path(p) == form:
                return p
        if form in reviewed:
            return form
    return None


_PATH_POOL = [
    "src/a.py",
    "src/A.py",
    "src/а.py",
    NFC,
    NFD,
    "src/a.py ",
    "src\\a.py",
    "a\nb.py",
    "a\\nb.py",
    "x\x1by.py",
    "x y.py",
    "`tick`.py",
    "src/../src/a.py",
]


def _mutate(rng: random.Random, path: str) -> str:
    kind = rng.randrange(9)
    if kind == 0:
        return path
    if kind == 1:
        return "./" * rng.randint(1, 3) + path
    if kind == 2:
        return "/" * rng.randint(1, 3) + path
    if kind == 3:
        return "`" * rng.randint(1, 2) + path + "`" * rng.randint(0, 2)
    if kind == 4:
        return escape_path(path)
    if kind == 5:
        return "`./" + escape_path(path) + "`"
    if kind == 6:
        return path + rng.choice([" ", "\t", "​", "/", ":1"])
    if kind == 7:
        return path.upper()
    return path.replace("/", "\\")


def test_path_matching_follows_only_the_documented_normalization():
    tactic = Tactic.from_env(tactic_seed(413, 4), 3_000)
    rng = tactic.rng()
    for i in range(tactic.iterations):
        reviewed = rng.sample(_PATH_POOL, rng.randint(1, 6))
        raw = _mutate(rng, rng.choice(_PATH_POOL))
        if not tactic.selected(i):
            continue
        ranges = dict.fromkeys(reviewed, ((1, 1),))
        expected = _oracle_match(raw, reviewed)
        ctx = tactic.context(i, (reviewed, raw))
        assert match_reviewed(raw, ranges) == expected, ctx
        result = run([finding(file=raw, line_start=1, line_end=1)], ranges=ranges)
        if expected is None:
            assert result.findings == () and result.dropped[0].reason == DROP_NOT_REVIEWED, ctx
        else:
            kept = only(result)
            assert kept.file == expected, ctx
            # The canonical path relates to the model's text only by the
            # documented transforms: identity, escape_path, normalize_file.
            assert expected in (raw, normalize_file(raw)) or escape_path(expected) in (
                raw,
                normalize_file(raw),
            ), ctx


# ---------------------------------------------------------------------------
# 3. Verdict: candidates and monotonicity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cid", ["v1", " V1", "V1 ", "V1\n", "\nV1", "V١", "Ｖ1", "V-1", "V", "V1​", ""]
)
def test_candidate_id_variants_are_rejected_by_the_schema_not_aliased(cid):
    with pytest.raises(SchemaViolation):
        run(checks=[check(cid, STATUS_NOT_REPRODUCED)], shown=[cand(1)])


def test_a_not_reproduced_check_for_an_unshown_id_cannot_clear_an_omitted_candidate():
    result = run(
        checks=[check("V2", STATUS_NOT_REPRODUCED), check("V01", STATUS_NOT_REPRODUCED)],
        shown=[cand(1)],
    )
    assert result.verdict == VERDICT_BLOCKING
    assert result.counts.verifier_checks_ignored == 2


def test_an_id_both_shown_and_dropped_still_counts_on_the_dropped_side():
    result = run(checks=[check("V1", STATUS_NOT_REPRODUCED)], shown=[cand(1)], dropped=[cand(1)])
    assert [(c.status, c.counted) for c in result.candidates] == [
        (STATUS_NOT_REPRODUCED, False),
        ("dropped_for_budget", True),
    ]
    assert result.verdict == VERDICT_BLOCKING


def test_a_later_not_reproduced_never_overrides_a_confirmed_check():
    for checks in (
        [check("V1"), check("V1", STATUS_NOT_REPRODUCED)],
        [check("V1", STATUS_NOT_REPRODUCED), check("V1"), check("V1", STATUS_NOT_REPRODUCED)],
    ):
        assert run(checks=checks, shown=[cand(1)]).verdict == VERDICT_BLOCKING


def test_the_empty_review_is_clear_with_all_zero_counts():
    result = run(ranges={})
    assert result.verdict == VERDICT_CLEAR
    m = result.metrics()
    assert all(v == 0 for v in m.values() if isinstance(v, int))
    assert all(v == 0 for d in m.values() if isinstance(d, dict) for v in d.values())


_MONO_FILES = ["src/a.py", "src/b.py", "gone.py"]


def _mono_finding(rng: random.Random, ranges) -> dict:
    name = rng.choice([*_MONO_FILES, "nope.py", "./src/a.py"])
    file_ranges = ranges.get(name.removeprefix("./"), ())
    if file_ranges and rng.random() < 0.6:
        a, b = rng.choice(file_ranges)
        start = max(1, rng.randint(a - 5, b + 5))
    else:
        start = rng.choice([1, 300, 10**300])
    return finding(
        severity=rng.choice(SEVERITIES),
        category=rng.choice(CATEGORIES),
        file=name,
        line_start=start,
        line_end=start + rng.choice([0, 0, 2]),
        failure_scenario=rng.choice(["", " ", "fails when x", "​"]),
        consequence=rng.choice(["", "500", "　"]),
        rank=rng.randint(1, 5),
    )


def test_verdict_is_monotone_under_added_findings_and_checks():
    """Adding findings or checks never turns ``blocking`` into ``clear``, except a
    ``not_reproduced`` check on a shown candidate (the legitimate D-33 filter);
    adding findings never removes a blocking finding.
    """
    tactic = Tactic.from_env(tactic_seed(413, 2), 1_500)
    rng = tactic.rng()
    for i in range(tactic.iterations):
        ranges = {
            "src/a.py": ((rng.randint(1, 40), rng.randint(41, 60)),),
            "src/b.py": ((10, 10), (30, 31)),
            "gone.py": (),
        }
        base_findings = [_mono_finding(rng, ranges) for _ in range(rng.randint(0, 10))]
        n = rng.randint(0, 4)
        cut = rng.randint(0, n)
        shown = [cand(k) for k in range(1, cut + 1)]
        dropped = [cand(k) for k in range(cut + 1, n + 1)]
        base_checks = [
            check(f"V{rng.randint(1, 6)}", rng.choice([STATUS_CONFIRMED, STATUS_NOT_REPRODUCED]))
            for _ in range(rng.randint(0, 4))
        ]
        extra_findings = [_mono_finding(rng, ranges) for _ in range(rng.randint(1, 10))]
        shown_ids = {c.id for c in shown}
        extra_checks = []
        for _ in range(rng.randint(1, 6)):
            cid = f"V{rng.randint(1, 8)}"
            status = rng.choice([STATUS_CONFIRMED, STATUS_NOT_REPRODUCED])
            if status == STATUS_NOT_REPRODUCED and cid in shown_ids:
                status = STATUS_CONFIRMED  # the one legitimate way to clear
            extra_checks.append(check(cid, status))
        ms = rng.randint(0, 3)
        if not tactic.selected(i):
            continue
        ctx = tactic.context(i, (ranges, base_findings, base_checks, extra_findings, extra_checks))

        def go(fs, cs, ranges=ranges, shown=shown, dropped=dropped, ms=ms):
            return run(
                fs, ranges=ranges, checks=cs, shown=shown, dropped=dropped, max_suggestions=ms
            )

        base = go(base_findings, base_checks)
        grown_f = go(base_findings + extra_findings, base_checks)
        grown_c = go(base_findings, base_checks + extra_checks)
        both = go(base_findings + extra_findings, base_checks + extra_checks)
        if base.verdict == VERDICT_BLOCKING:
            assert grown_f.verdict == grown_c.verdict == both.verdict == VERDICT_BLOCKING, ctx
        assert {f.index for f in base.blocking} <= {f.index for f in grown_f.blocking}, ctx
        assert base.counts.verifier_confirmed <= grown_c.counts.verifier_confirmed, ctx
        # Dropped-for-budget candidates count whatever the checks say.
        assert all(c.counted for c in both.candidates if c.status == "dropped_for_budget"), ctx


# ---------------------------------------------------------------------------
# 4. Counts: conservation, fixed keys, integers only, no finding text
# ---------------------------------------------------------------------------

_SENTINEL = "QA413-SENTINEL"


def test_counts_conserve_and_never_carry_finding_text():
    tactic = Tactic.from_env(tactic_seed(413, 5), 1_000)
    rng = tactic.rng()
    expected_keys = None
    for i in range(tactic.iterations):
        ranges = {"src/a.py": ((100, 105),), "src/b.py": ()}
        findings = []
        for k in range(rng.randint(0, 40)):
            f = _mono_finding(rng, ranges)
            tag = f"{_SENTINEL}-{k}"
            f["title"] = tag
            if f["failure_scenario"].strip():
                f["failure_scenario"] = tag
            if f["consequence"].strip():
                f["consequence"] = tag
            if rng.random() < 0.2:
                f["file"] = tag
            findings.append(f)
        shown = [cand(k) for k in range(1, rng.randint(0, 3) + 1)]
        checks = [
            check(
                f"V{rng.randint(1, 4)}",
                rng.choice([STATUS_CONFIRMED, STATUS_NOT_REPRODUCED]),
                _SENTINEL,
            )
            for _ in range(rng.randint(0, 4))
        ]
        ms = rng.randint(0, 6)
        if not tactic.selected(i):
            continue
        ctx = tactic.context(i, (findings, checks, ms))
        result = run(findings, ranges=ranges, checks=checks, shown=shown, max_suggestions=ms)
        c, m = result.counts, result.metrics()
        assert _SENTINEL not in json.dumps(m), ctx
        if expected_keys is None:
            expected_keys = {k: sorted(v) if isinstance(v, dict) else None for k, v in m.items()}
        assert {
            k: sorted(v) if isinstance(v, dict) else None for k, v in m.items()
        } == expected_keys
        for v in m.values():
            leaves = v.values() if isinstance(v, dict) else [v]
            assert all(type(x) is int and x >= 0 for x in leaves), ctx
        assert sorted(m["downgraded"]) == sorted(DOWNGRADE_REASONS)
        assert sorted(m["dropped"]) == sorted(DROP_REASONS)
        assert sorted(m["verifier_by_status"]) == sorted(STATUSES)
        assert c.findings_in == len(findings) == c.kept + sum(c.dropped.values()), ctx
        assert c.kept == len(result.findings) == sum(c.findings_by_severity.values()), ctx
        assert c.kept == sum(c.findings_by_category.values()), ctx
        assert c.suggestions_capped == c.dropped["cap"], ctx
        assert sum(c.downgraded.values()) <= c.findings_in, ctx
        assert c.verifier_candidates == sum(c.verifier_by_status.values()) == len(result.candidates)
        assert c.verifier_confirmed == len(result.counted_candidates), ctx


# ---------------------------------------------------------------------------
# 5. Blank definition: placeholders (D-51)
# ---------------------------------------------------------------------------

MARK_ONLY = ["́", "͏", "️", "\U000e0100", "឴", "́́​"]


PUNCTUATION_ONLY = [".", "-", "—", "…", "?"]
WORD_PLACEHOLDERS = ["N/A", "n/a", "none", "None", "TBD", "null"]


@pytest.mark.parametrize("text", PUNCTUATION_ONLY + MARK_ONLY, ids=ascii)
def test_placeholder_and_mark_only_scenarios_are_blank_under_d51(text):
    """D-51 (QA-211-Q1): blank means no Unicode letter or number.

    Punctuation, symbols and combining marks alone carry no scenario, so a
    blocking finding with one is downgraded with ``no_scenario``.
    """
    assert is_blank(text)
    kept = only(run([finding(failure_scenario=text)]))
    assert (kept.severity, kept.downgraded) == ("suggestion", "no_scenario")


@pytest.mark.parametrize("text", WORD_PLACEHOLDERS, ids=ascii)
def test_placeholder_words_are_not_blank_under_d51(text):
    """D-51 has no word deny-list: ``"N/A"`` and ``"none"`` contain letters."""
    assert not is_blank(text)
    kept = only(run([finding(failure_scenario=text)]))
    assert (kept.severity, kept.downgraded) == ("blocking", None)


@pytest.mark.parametrize(
    "text",
    ["\U000e0020", "⁢", "­‍", "　 ", "⠀", "ᅟᅠ", "\x00\x7f"],
    ids=ascii,
)
def test_invisible_format_tags_and_fillers_are_blank_and_downgrade(text):
    assert is_blank(text)
    kept = only(run([finding(failure_scenario=text)]))
    assert kept.downgraded == "no_scenario"


# ---------------------------------------------------------------------------
# 6. Performance: 40 schema-maximal findings, 200k ranges
# ---------------------------------------------------------------------------


def test_forty_schema_maximal_findings_over_many_files_and_200k_ranges_stay_fast():
    dense = tuple((3 * k + 1, 3 * k + 1) for k in range(200_000))  # gaps of 2: no merge
    ranges = {"src/a.py": dense, **{f"f{i}.py": dense[:20_000] for i in range(39)}}
    findings = [
        finding(
            file="src/a.py" if i == 0 else f"f{i - 1}.py",
            line_start=3 * i + 1,  # a changed line: stays valid once D1 is fixed
            line_end=3 * i + 1,
            title="t" * 200,
            failure_scenario="​" * 1499 + "s",  # is_blank scans to the end
            consequence="　" * 499 + "c",
            rank=10**300 - i,
        )
        for i in range(40)
    ]
    checks = [check("V" + "1" * 1000, STATUS_CONFIRMED, "r" * 300)] * 100_000
    start = time.perf_counter()
    result = run(findings, ranges=ranges, checks=checks, shown=[cand(1)])
    assert time.perf_counter() - start < 2.0
    assert len(result.blocking) == 40
    assert result.counts.verifier_checks_ignored == 100_000


def test_strings_over_the_schema_maximum_are_rejected_before_any_scan():
    start = time.perf_counter()
    for field, size in (
        ("file", 401),
        ("title", 201),
        ("failure_scenario", 1501),
        ("consequence", 501),
    ):
        with pytest.raises(SchemaViolation):
            run([finding(**{field: "​" * (size + 10**7)})])
    assert time.perf_counter() - start < 1.0
