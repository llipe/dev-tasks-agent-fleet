"""
S-211 AC1-AC5, AC7 — findings validation (spec §8.6, D-08, PRD FR-23, FR-31).

Test plan TC-211-01..10, TC-211-14, TC-211-15, EC-29, EC-31. The verdict
cases (TC-211-11..13) are in ``test_verdict.py``; the RT-08 property tactic is
in ``test_properties_validate.py``.

Reviewed files come from the diff (``DiffContext.changed_ranges``: reviewed,
fetched, non-removed files), never from ``ContextData.full_files_included``,
which is empty after an R4 retry or a repair (fidelity report S-210).
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from context.diff import DiffContext, FileDiff, NameOnlyFile, escape_path
from findings_schema import CATEGORIES, SchemaViolation
from validate import (
    DOWNGRADE_NO_SCENARIO,
    DOWNGRADE_OUTSIDE_DIFF,
    DROP_CAP,
    DROP_NO_CONSEQUENCE,
    DROP_NOT_REVIEWED,
    LOCATION_WINDOW,
    VERDICT_BLOCKING,
    VERDICT_CLEAR,
    in_changed_range,
    is_blank,
    match_reviewed,
    normalize_file,
    validate,
    validate_result,
)

RANGES = {
    "src/a.py": ((100, 105),),
    "src/b.py": ((10, 10), (40, 42)),
    "docs/renamed.md": (),  # reviewed, but a pure rename: no changed head line
}


def finding(**overrides):
    base = {
        "severity": "blocking",
        "category": "correctness",
        "file": "src/a.py",
        "line_start": 101,
        "line_end": 102,
        "title": "Off-by-one in the boundary check",
        "failure_scenario": "Given n = 10, the loop reads index 10 and raises IndexError.",
        "consequence": "The request fails with a 500.",
        "rank": 1,
    }
    base.update(overrides)
    return base


def run(findings, *, ranges=RANGES, max_suggestions=5, checks=(), shown=(), dropped=()):
    review = {"findings": list(findings), "verifier_checks": list(checks)}
    return validate(
        review,
        changed_ranges=ranges,
        shown_candidates=shown,
        dropped_candidates=dropped,
        max_suggestions=max_suggestions,
    )


def only(result):
    assert len(result.findings) == 1, result
    return result.findings[0]


# ---------------------------------------------------------------------------
# AC1 — non-reviewed files are dropped (TC-211-01, TC-211-02)
# ---------------------------------------------------------------------------


def test_tc211_01_a_finding_on_a_file_not_in_the_pr_is_dropped():
    result = run([finding(file="src/elsewhere.py")])
    assert result.findings == ()
    assert [d.reason for d in result.dropped] == [DROP_NOT_REVIEWED]
    assert DROP_NOT_REVIEWED == "not_reviewed"  # DF-07: the name is pinned here
    assert result.verdict == VERDICT_CLEAR


def _file_diff(name, status="modified", head="x\n", ranges=((1, 1),)):
    return FileDiff(
        filename=name,
        status=status,
        previous_filename=None,
        diff="",
        head_content=None if status == "removed" else head,
        changed_ranges=() if status == "removed" else ranges,
    )


def _diff_context():
    return DiffContext(
        head_sha="a" * 40,
        merge_base_sha="b" * 40,
        changed_lines=10,
        files=(
            _file_diff("src/a.py", ranges=((100, 105),)),
            _file_diff("src/gone.py", status="removed"),
            _file_diff("docs/moved.md", status="renamed", ranges=()),
        ),
        name_only=(
            NameOnlyFile("pnpm-lock.yaml", "modified", "lockfile"),
            NameOnlyFile("workstream/tasks-x.md", "modified", "excluded"),
            NameOnlyFile("img/logo.png", "added", "binary"),
            NameOnlyFile("src/huge.py", "modified", "content_unavailable", "not found"),
        ),
    )


def _result(findings, checks=(), shown=(), dropped=(), full_files_included=()):
    context = SimpleNamespace(
        shown_candidates=tuple(shown),
        dropped_candidates=tuple(dropped),
        full_files_included=tuple(full_files_included),
    )
    return SimpleNamespace(
        findings={"findings": list(findings), "verifier_checks": list(checks)}, context=context
    )


@pytest.mark.parametrize(
    "path",
    ["pnpm-lock.yaml", "workstream/tasks-x.md", "img/logo.png", "src/huge.py", "src/gone.py"],
)
def test_tc211_01_name_only_and_removed_files_are_not_reviewed_even_when_blocking(path):
    # Name-only (lockfile, excluded, binary, content unavailable) and removed
    # files have no head content in the diff, so they are not reviewed.
    result = validate_result(_result([finding(file=path)]), _diff_context(), max_suggestions=5)
    assert result.findings == ()
    assert [d.reason for d in result.dropped] == [DROP_NOT_REVIEWED]
    assert result.verdict == VERDICT_CLEAR


def test_reviewed_files_come_from_the_diff_not_from_full_files_included():
    # After an R4 retry or a repair, ContextData.full_files_included is empty;
    # the files are still reviewed.
    result = validate_result(
        _result([finding(file="src/a.py")], full_files_included=()),
        _diff_context(),
        max_suggestions=5,
    )
    assert only(result).severity == "blocking"
    # And a full file listed there does not make a non-reviewed file reviewed.
    result = validate_result(
        _result([finding(file="pnpm-lock.yaml")], full_files_included=("pnpm-lock.yaml",)),
        _diff_context(),
        max_suggestions=5,
    )
    assert result.findings == ()


def test_a_pure_rename_with_no_changed_line_is_reviewed_but_outside_the_diff():
    result = validate_result(
        _result([finding(file="docs/moved.md", line_start=1, line_end=1)]),
        _diff_context(),
        max_suggestions=5,
    )
    kept = only(result)
    assert kept.severity == "suggestion"
    assert kept.downgraded == DOWNGRADE_OUTSIDE_DIFF


@pytest.mark.parametrize(
    "raw",
    [
        "src/a.py",
        "./src/a.py",
        "`src/a.py`",
        "/src/a.py",
        "`./src/a.py`",
        "``src/a.py``",
        ".//src/a.py",
        "//src/a.py",
        "././src/a.py",
        "`/src/a.py`",
    ],
)
def test_tc211_02_path_normalization_matches(raw):
    kept = only(run([finding(file=raw)]))
    assert kept.file == "src/a.py"
    assert kept.severity == "blocking"


@pytest.mark.parametrize(
    "raw",
    [
        "src/A.py",
        "src\\a.py",
        "src/../src/a.py",  # `..` is never resolved
        "./../src/a.py",
        "src/./a.py",
        " src/a.py",  # whitespace is not stripped (pinned)
        "src/a.py ",
        "'src/a.py'",
        "src/a.py:101",
        "a.py",
        "",
    ],
)
def test_tc211_02_near_misses_do_not_match_and_are_dropped(raw):
    result = run([finding(file=raw)])
    assert result.findings == ()
    assert [d.reason for d in result.dropped] == [DROP_NOT_REVIEWED]


def test_a_literal_dotdot_path_matches_only_when_it_is_itself_reviewed():
    ranges = {"a/../b.py": ((5, 5),), "b.py": ((5, 5),)}
    assert only(run([finding(file="a/../b.py", line_start=5, line_end=5)], ranges=ranges)).file == (
        "a/../b.py"
    )
    assert match_reviewed("x/../b.py", ranges) is None


def test_escaped_control_character_paths_match_the_reviewed_file():
    name = "src/evil\nname.py"
    ranges = {name: ((1, 3),)}
    assert escape_path(name) == "src/evil\\nname.py"
    for raw in (name, escape_path(name), "./" + escape_path(name), "`" + escape_path(name) + "`"):
        kept = only(run([finding(file=raw, line_start=2, line_end=2)], ranges=ranges))
        assert kept.file == name  # the canonical (raw repository) path


def test_a_literal_path_wins_over_another_files_escaped_form():
    # A file literally named `x\nb.py` (backslash, n) and one with a newline:
    # the escaped form of the second equals the first's literal name.
    literal, control = "x\\nb.py", "x\nb.py"
    ranges = {literal: ((1, 1),), control: ((9, 9),)}
    assert match_reviewed(literal, ranges) == literal
    assert match_reviewed(control, ranges) == control


def test_normalize_file_strips_backticks_then_leading_dot_slash_and_slash():
    assert normalize_file("`./src/a.py`") == "src/a.py"
    assert normalize_file("/./src/a.py") == "src/a.py"
    assert normalize_file("../a") == "../a"
    assert normalize_file("`") == ""
    assert normalize_file("./") == ""


def test_normalize_file_is_linear_on_hostile_input():
    raw = "`" * 200_000 + "./" * 200_000 + "/" * 200_000 + "a" + "`" * 200_000
    start = time.perf_counter()
    assert normalize_file(raw) == "a"
    assert time.perf_counter() - start < 1.0


# ---------------------------------------------------------------------------
# AC2 — location (TC-211-03, TC-211-04, TC-211-05, TC-211-15)
# ---------------------------------------------------------------------------


def test_tc211_03_a_blocking_finding_inside_a_changed_range_stays_blocking():
    kept = only(run([finding(line_start=101, line_end=104)]))
    assert kept.severity == "blocking"
    assert kept.downgraded is None
    assert kept.as_artifact()["downgraded"] is False


@pytest.mark.parametrize(
    ("start", "end", "blocking"),
    [
        (97, 97, True),
        (108, 108, True),
        (96, 96, False),
        (109, 109, False),
        (50, 99, True),
        (50, 96, False),
        (109, 200, False),
        (108, 500, True),
        (1, 1000, True),
    ],
)
def test_tc211_04_the_plus_minus_three_boundary_on_both_sides(start, end, blocking):
    assert LOCATION_WINDOW == 3
    kept = only(run([finding(line_start=start, line_end=end)]))
    if blocking:
        assert (kept.severity, kept.downgraded) == ("blocking", None)
    else:
        assert (kept.severity, kept.downgraded) == ("suggestion", DOWNGRADE_OUTSIDE_DIFF)


def test_tc211_04_the_window_applies_to_each_of_several_ranges():
    # src/b.py: (10, 10), (40, 42). 14 and 36 are each 4 away.
    for line, ok in [(7, True), (13, True), (14, False), (36, False), (37, True), (45, True)]:
        kept = only(run([finding(file="src/b.py", line_start=line, line_end=line)]))
        assert (kept.severity == "blocking") is ok, line


def test_tc211_05_a_blocking_finding_outside_every_range_is_downgraded():
    kept = only(run([finding(line_start=10, line_end=20)]))
    assert kept.severity == "suggestion"
    assert kept.downgraded == DOWNGRADE_OUTSIDE_DIFF
    assert kept.as_artifact()["downgraded"] == "outside_diff"


def test_a_suggestion_outside_the_diff_is_kept_and_not_marked_downgraded():
    kept = only(run([finding(severity="suggestion", line_start=1, line_end=1)]))
    assert (kept.severity, kept.downgraded) == ("suggestion", None)


def test_tc211_15_line_end_before_line_start_is_swapped():
    kept = only(run([finding(line_start=104, line_end=101)]))
    assert (kept.line_start, kept.line_end) == (101, 104)
    assert kept.severity == "blocking"
    # Swapped before the location check: [96, 200] reversed still intersects.
    kept = only(run([finding(line_start=200, line_end=96)]))
    assert kept.severity == "blocking"


def test_tc211_15_a_line_beyond_the_file_is_outside_the_diff():
    kept = only(run([finding(line_start=10_000, line_end=10_001)]))
    assert kept.downgraded == DOWNGRADE_OUTSIDE_DIFF


def test_huge_line_numbers_are_compared_exactly_without_overflow():
    huge = 10**300
    # Far past every range: outside.
    kept = only(run([finding(line_start=huge, line_end=huge + 1)]))
    assert kept.downgraded == DOWNGRADE_OUTSIDE_DIFF
    # A span from 1 to 10**300 covers the range: it intersects (spec literal).
    kept = only(run([finding(line_start=1, line_end=huge)]))
    assert kept.severity == "blocking"
    assert kept.line_end == huge  # kept exactly, never clamped or converted
    # Swapped huge span.
    kept = only(run([finding(line_start=huge, line_end=103)]))
    assert (kept.line_start, kept.line_end, kept.severity) == (103, huge, "blocking")


def test_the_location_check_is_fast_with_many_ranges_and_huge_lines():
    ranges = {"src/a.py": tuple((k * 10, k * 10 + 1) for k in range(1, 200_001))}
    findings = [
        finding(line_start=10**300 - k, line_end=10**300 + k, rank=k + 1) for k in range(40)
    ]
    start = time.perf_counter()
    result = run(findings, ranges=ranges)
    assert time.perf_counter() - start < 1.0
    assert all(f.downgraded == DOWNGRADE_OUTSIDE_DIFF for f in result.findings)


def test_in_changed_range_direct():
    assert in_changed_range(97, 97, ((100, 105),))
    assert not in_changed_range(96, 96, ((100, 105),))
    assert in_changed_range(110, 1, ((100, 105),))  # swapped
    assert not in_changed_range(1, 1, ())


# ---------------------------------------------------------------------------
# AC3 — scenario (TC-211-06) and the one blank definition
# ---------------------------------------------------------------------------

BLANKS = [
    "",
    " ",
    "   ",
    "\n",
    "\t\r\n\x0b\x0c",
    " ",  # no-break space
    " 　",  # em space, ideographic space
    "  ",  # line and paragraph separators
    "​",  # zero-width space
    "‌‍",  # zero-width non-joiner, joiner
    "⁠",  # word joiner
    "﻿",  # BOM / zero-width no-break space
    "᠎",  # Mongolian vowel separator
    "­",  # soft hyphen (Cf)
    "‎‮⁦",  # bidi controls (Cf)
    "\x00\x1b",  # C0 controls (Cc)
    "\u0085",  # NEL (Cc)
    "ㅤᅟᅠﾠ",  # Hangul fillers
    "⠀",  # braille pattern blank
    " ​ ﻿ \n",
]

NON_BLANKS = ["x", " a ", "​z", "͏", "-", "0", "é", "\U0001f600"]


@pytest.mark.parametrize("text", BLANKS)
def test_is_blank_pins_the_blank_definition(text):
    assert is_blank(text)


@pytest.mark.parametrize("text", NON_BLANKS)
def test_is_blank_rejects_visible_text(text):
    assert not is_blank(text)


@pytest.mark.parametrize("scenario", BLANKS)
def test_tc211_06_a_blank_scenario_downgrades_a_blocking_finding(scenario):
    kept = only(run([finding(failure_scenario=scenario)]))
    assert kept.severity == "suggestion"
    assert kept.downgraded == DOWNGRADE_NO_SCENARIO
    assert kept.as_artifact()["downgraded"] == "no_scenario"


def test_tc211_06_a_finding_failing_both_checks_is_outside_diff_the_first_rule():
    kept = only(run([finding(line_start=1, line_end=1, failure_scenario="  ")]))
    assert kept.downgraded == DOWNGRADE_OUTSIDE_DIFF
    assert run([finding(line_start=1, line_end=1, failure_scenario="")]).counts.downgraded == {
        DOWNGRADE_OUTSIDE_DIFF: 1,
        DOWNGRADE_NO_SCENARIO: 0,
    }


def test_a_suggestion_with_a_blank_scenario_is_kept_as_is():
    kept = only(run([finding(severity="suggestion", failure_scenario="")]))
    assert (kept.severity, kept.downgraded) == ("suggestion", None)


def test_is_blank_is_linear():
    text = "​ ﻿" * 1_000_000
    start = time.perf_counter()
    assert is_blank(text)
    assert not is_blank(text + "x")
    assert time.perf_counter() - start < 2.0


# ---------------------------------------------------------------------------
# AC4 — consequence (TC-211-07)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("severity", ["blocking", "suggestion"])
@pytest.mark.parametrize("consequence", ["", "   ", "\n", "​", "　﻿"])
def test_tc211_07_a_blank_consequence_is_dropped_for_both_severities(severity, consequence):
    result = run([finding(severity=severity, consequence=consequence)])
    assert result.findings == ()
    assert [d.reason for d in result.dropped] == [DROP_NO_CONSEQUENCE]
    assert result.dropped[0].as_artifact() == {
        "reason": "no_consequence",
        "title": "Off-by-one in the boundary check",
    }


def test_a_downgraded_finding_with_a_blank_consequence_is_dropped_and_still_counted_downgraded():
    result = run([finding(line_start=1, line_end=1, consequence="")])
    assert result.findings == ()
    assert result.counts.dropped[DROP_NO_CONSEQUENCE] == 1
    assert result.counts.downgraded[DOWNGRADE_OUTSIDE_DIFF] == 1


def test_a_non_reviewed_file_takes_precedence_over_a_blank_consequence():
    result = run([finding(file="nope.py", consequence="")])
    assert [d.reason for d in result.dropped] == [DROP_NOT_REVIEWED]


# ---------------------------------------------------------------------------
# AC5 — sort, cap, IDs (TC-211-08, TC-211-09, TC-211-10)
# ---------------------------------------------------------------------------


def test_tc211_08_suggestions_sorted_by_rank_ties_in_model_order_and_capped():
    findings = [
        finding(severity="suggestion", title="r3", rank=3),
        finding(severity="suggestion", title="r1a", rank=1),
        finding(severity="suggestion", title="r2", rank=2),
        finding(severity="suggestion", title="r1b", rank=1),
        finding(severity="suggestion", title="r9", rank=9),
        finding(severity="suggestion", title="r1c", rank=1),
    ]
    result = run(findings, max_suggestions=4)
    assert [f.title for f in result.suggestions] == ["r1a", "r1b", "r1c", "r2"]
    assert [f.id for f in result.suggestions] == ["S1", "S2", "S3", "S4"]
    assert sorted((d.title, d.reason) for d in result.dropped) == [
        ("r3", DROP_CAP),
        ("r9", DROP_CAP),
    ]
    assert result.counts.suggestions_capped == 2


def test_tc211_08_blocking_findings_are_never_capped():
    findings = [finding(title=f"b{k}", rank=k + 1) for k in range(12)]
    findings += [finding(severity="suggestion", title=f"s{k}", rank=k + 1) for k in range(7)]
    result = run(findings, max_suggestions=5)
    assert len(result.blocking) == 12
    assert len(result.suggestions) == 5
    assert result.counts.suggestions_capped == 2
    result = run(findings, max_suggestions=0)
    assert len(result.blocking) == 12


def test_tc211_09_max_suggestions_zero_drops_every_suggestion_downgraded_included():
    findings = [
        finding(severity="suggestion", rank=1),
        finding(line_start=1, line_end=1, rank=2),  # downgraded: outside_diff
        finding(failure_scenario="", rank=3),  # downgraded: no_scenario
        finding(rank=4),  # blocking, kept
    ]
    result = run(findings, max_suggestions=0)
    assert result.suggestions == ()
    assert [f.id for f in result.blocking] == ["B1"]
    assert result.counts.dropped[DROP_CAP] == 3
    assert result.counts.suggestions_capped == 3
    assert result.counts.downgraded == {DOWNGRADE_OUTSIDE_DIFF: 1, DOWNGRADE_NO_SCENARIO: 1}


def test_tc211_09_downgraded_findings_count_toward_the_cap_by_rank():
    findings = [
        finding(severity="suggestion", title="s5", rank=5),
        finding(line_start=1, line_end=1, title="d1", rank=1),
    ]
    result = run(findings, max_suggestions=1)
    assert [f.title for f in result.suggestions] == ["d1"]
    assert [d.title for d in result.dropped] == ["s5"]


def test_tc211_10_ids_are_contiguous_in_rank_order_after_every_filter():
    findings = [
        finding(title="b-r5", rank=5),
        finding(file="nope.py", rank=1),  # dropped
        finding(title="b-r2", rank=2),
        finding(consequence="", rank=1),  # dropped
        finding(title="b-r2-later", rank=2),
        finding(severity="suggestion", title="s-r7", rank=7),
        finding(line_start=1, line_end=1, title="d-r3", rank=3),
    ]
    result = run(findings)
    assert [(f.id, f.title) for f in result.blocking] == [
        ("B1", "b-r2"),
        ("B2", "b-r2-later"),
        ("B3", "b-r5"),
    ]
    assert [(f.id, f.title) for f in result.suggestions] == [("S1", "d-r3"), ("S2", "s-r7")]
    assert [f.id for f in result.findings] == ["B1", "B2", "B3", "S1", "S2"]


def test_huge_and_duplicate_ranks_sort_stably():
    huge = 10**300
    findings = [
        finding(severity="suggestion", title="h1", rank=huge),
        finding(severity="suggestion", title="one", rank=1),
        finding(severity="suggestion", title="h2", rank=huge),
        finding(severity="suggestion", title="h0", rank=huge - 1),
    ]
    result = run(findings, max_suggestions=3)
    assert [f.title for f in result.suggestions] == ["one", "h0", "h1"]
    assert [d.title for d in result.dropped] == ["h2"]


def test_zero_findings():
    result = run([])
    assert (result.findings, result.dropped, result.verdict) == ((), (), VERDICT_CLEAR)
    assert result.counts.findings_in == 0
    assert result.counts.kept == 0


def test_everything_downgraded_leaves_no_blocking_finding():
    findings = [finding(line_start=1, line_end=1, rank=1), finding(failure_scenario=" ", rank=2)]
    result = run(findings)
    assert result.blocking == ()
    assert [f.downgraded for f in result.suggestions] == [
        DOWNGRADE_OUTSIDE_DIFF,
        DOWNGRADE_NO_SCENARIO,
    ]
    assert result.verdict == VERDICT_CLEAR


def test_kept_findings_carry_the_model_fields_and_the_artifact_shape():
    kept = only(run([finding(category="edge_case", rank=7)]))
    assert kept.as_artifact() == {
        "id": "B1",
        "severity": "blocking",
        "category": "edge_case",
        "file": "src/a.py",
        "line_start": 101,
        "line_end": 102,
        "title": "Off-by-one in the boundary check",
        "failure_scenario": "Given n = 10, the loop reads index 10 and raises IndexError.",
        "consequence": "The request fails with a 500.",
        "rank": 7,
        "downgraded": False,
    }
    assert kept.index == 0


def test_dropped_findings_are_listed_in_model_order():
    findings = [
        finding(severity="suggestion", title="cap-me", rank=9),
        finding(file="x.py", title="not-reviewed"),
        finding(consequence="", title="no-consequence"),
        finding(severity="suggestion", title="keep", rank=1),
    ]
    result = run(findings, max_suggestions=1)
    assert [(d.index, d.title, d.reason) for d in result.dropped] == [
        (0, "cap-me", DROP_CAP),
        (1, "not-reviewed", DROP_NOT_REVIEWED),
        (2, "no-consequence", DROP_NO_CONSEQUENCE),
    ]


# ---------------------------------------------------------------------------
# AC7 — counts for metrics (TC-211-14, FR-31)
# ---------------------------------------------------------------------------


def test_counts():
    findings = [
        finding(rank=1),  # blocking, correctness
        finding(category="intent", rank=2),  # blocking, intent
        finding(line_start=1, line_end=1, category="edge_case", rank=3),  # outside_diff
        finding(failure_scenario="", category="maintainability", rank=4),  # no_scenario
        finding(severity="suggestion", rank=5),  # suggestion, capped below
        finding(file="nope.py"),  # not_reviewed
        finding(consequence=""),  # no_consequence
    ]
    result = run(findings, max_suggestions=2)
    c = result.counts
    assert c.findings_in == 7
    assert c.kept == 4
    assert c.findings_in == c.kept + sum(c.dropped.values())
    assert c.downgraded == {DOWNGRADE_OUTSIDE_DIFF: 1, DOWNGRADE_NO_SCENARIO: 1}
    assert c.dropped == {DROP_NOT_REVIEWED: 1, DROP_NO_CONSEQUENCE: 1, DROP_CAP: 1}
    assert c.suggestions_capped == 1
    assert c.findings_by_severity == {"blocking": 2, "suggestion": 2}
    assert c.findings_by_category == {
        "correctness": 1,
        "edge_case": 1,
        "maintainability": 1,
        "intent": 1,
    }
    metrics = result.metrics()
    assert set(metrics) == {
        "findings_by_severity",
        "findings_by_category",
        "downgraded",
        "dropped",
        "suggestions_capped",
        "verifier_candidates",
        "verifier_confirmed",
        "verifier_by_status",
        "verifier_checks_ignored",
        "verifier_checks_duplicate",
    }
    assert metrics["findings_by_category"] == c.findings_by_category
    assert list(metrics["findings_by_category"]) == list(CATEGORIES)


def test_counts_have_every_key_even_when_zero():
    m = run([]).metrics()
    assert m["downgraded"] == {"outside_diff": 0, "no_scenario": 0}
    assert m["dropped"] == {"not_reviewed": 0, "no_consequence": 0, "cap": 0}
    assert m["suggestions_capped"] == 0
    assert m["findings_by_severity"] == {"blocking": 0, "suggestion": 0}
    assert m["findings_by_category"] == dict.fromkeys(CATEGORIES, 0)


def test_metrics_never_contain_finding_text():
    marker = "SECRET-MARKER-7f3a"
    findings = [
        finding(title=marker, failure_scenario=marker, consequence=marker, rank=1),
        finding(file=marker, title=marker),
        finding(severity="suggestion", title=marker, consequence=marker, rank=2),
    ]
    result = run(findings, max_suggestions=0)
    dumped = json.dumps(result.metrics())
    assert marker not in dumped


# ---------------------------------------------------------------------------
# Input guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [-1, True, 1.5, "5", None])
def test_max_suggestions_must_be_a_non_negative_int(bad):
    with pytest.raises(ValueError):
        run([], max_suggestions=bad)


def test_a_schema_invalid_review_is_rejected_not_trusted():
    with pytest.raises(SchemaViolation):
        validate(
            {"findings": [finding(severity="high")], "verifier_checks": []},
            changed_ranges=RANGES,
            shown_candidates=(),
            dropped_candidates=(),
            max_suggestions=5,
        )


def test_validate_does_not_mutate_its_input():
    review = {"findings": [finding(line_start=105, line_end=101)], "verifier_checks": []}
    snapshot = json.dumps(review)
    validate(
        review,
        changed_ranges=RANGES,
        shown_candidates=(),
        dropped_candidates=(),
        max_suggestions=5,
    )
    assert json.dumps(review) == snapshot


def test_validate_is_deterministic():
    findings = [finding(rank=k % 3 + 1, title=f"t{k}") for k in range(20)]
    findings += [finding(severity="suggestion", rank=1, title=f"s{k}") for k in range(10)]
    assert run(findings) == run(findings)


def test_a_full_forty_finding_review_with_verdict_blocking():
    findings = [finding(rank=k + 1, title=f"t{k}") for k in range(40)]
    result = run(findings, max_suggestions=0)
    assert len(result.blocking) == 40
    assert result.verdict == VERDICT_BLOCKING


def test_in_changed_range_accepts_unsorted_overlapping_ranges():
    # DiffContext ranges are merged and sorted; a hand-built input may not be.
    ranges = ((300, 310), (1, 200), (50, 60), (201, 205))
    assert in_changed_range(208, 208, ranges)  # 205 + 3
    assert not in_changed_range(209, 296, ranges)
    assert in_changed_range(297, 297, ranges)
    assert in_changed_range(150, 150, ranges)
