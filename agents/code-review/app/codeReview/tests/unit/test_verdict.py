"""
S-211 AC6 — the verdict and per-candidate status (spec §8.4 step 5, §8.7).

Test plan TC-211-11..13, EC-30, EC-31; decisions D-15, D-33, D-37.

- A shown candidate counts when the model returns ``confirmed`` or omits it
  ("not checked by the model"). ``not_reproduced`` does not count.
- A candidate dropped for budget always counts, even when the model returns a
  check for its ID (the prompt notes name the dropped IDs, so it can).
- Checks for IDs not in ``shown_candidates`` are ignored; IDs match exactly
  (``V01`` is not ``V1``).
- Duplicate checks for one ID (DF-12, pinned here): any ``confirmed`` wins,
  with the first ``confirmed`` entry's reason; otherwise the first entry's.
"""

from __future__ import annotations

import time

from context.verifier import Candidate
from validate import (
    NOT_CHECKED_REASON,
    REASON_MAX_CHARS,
    STATUS_CONFIRMED,
    STATUS_DROPPED_FOR_BUDGET,
    STATUS_NOT_CHECKED,
    STATUS_NOT_REPRODUCED,
    VERDICT_BLOCKING,
    VERDICT_CLEAR,
    candidate_statuses,
    validate,
)

RANGES = {"src/a.py": ((100, 105),)}


def cand(k: int) -> Candidate:
    return Candidate(
        id=f"V{k}",
        report_path="workstream/fidelity-report-S-170.md",
        row_index=k,
        line=20 + k,
        text=f"| D{k} | Critical | Unintended | row {k} |",
        truncated=False,
    )


def check(cid: str, status: str, reason: str = "r") -> dict:
    return {"candidate_id": cid, "status": status, "reason": reason}


def blocking_finding(**overrides) -> dict:
    base = {
        "severity": "blocking",
        "category": "correctness",
        "file": "src/a.py",
        "line_start": 101,
        "line_end": 101,
        "title": "t",
        "failure_scenario": "fails when x",
        "consequence": "500",
        "rank": 1,
    }
    base.update(overrides)
    return base


def run(*, findings=(), checks=(), shown=(), dropped=()):
    return validate(
        {"findings": list(findings), "verifier_checks": list(checks)},
        changed_ranges=RANGES,
        shown_candidates=tuple(shown),
        dropped_candidates=tuple(dropped),
        max_suggestions=5,
    )


def statuses(result):
    return [(c.candidate.id, c.status, c.counted) for c in result.candidates]


# ---------------------------------------------------------------------------
# TC-211-11 — the verdict table
# ---------------------------------------------------------------------------


def test_tc211_11_a_confirmed_candidate_blocks():
    result = run(checks=[check("V1", STATUS_CONFIRMED, "visible in the diff")], shown=[cand(1)])
    assert result.verdict == VERDICT_BLOCKING
    assert statuses(result) == [("V1", STATUS_CONFIRMED, True)]
    assert result.candidates[0].reason == "visible in the diff"


def test_tc211_11_not_reproduced_only_is_clear_and_keeps_the_reason():
    result = run(
        checks=[check("V1", STATUS_NOT_REPRODUCED, "report predates the head")], shown=[cand(1)]
    )
    assert result.verdict == VERDICT_CLEAR
    assert statuses(result) == [("V1", STATUS_NOT_REPRODUCED, False)]
    assert result.candidates[0].reason == "report predates the head"


def test_tc211_11_an_omitted_candidate_counts_as_not_checked_by_the_model():
    result = run(shown=[cand(1)])
    assert result.verdict == VERDICT_BLOCKING
    assert statuses(result) == [("V1", STATUS_NOT_CHECKED, True)]
    assert result.candidates[0].reason == NOT_CHECKED_REASON == "not checked by the model"


def test_tc211_11_a_blocking_finding_alone_blocks():
    result = run(findings=[blocking_finding()])
    assert result.verdict == VERDICT_BLOCKING
    assert result.candidates == ()


def test_tc211_11_neither_is_clear():
    assert run().verdict == VERDICT_CLEAR


def test_a_dropped_for_budget_candidate_counts_even_with_a_model_check_for_its_id():
    result = run(
        checks=[check("V2", STATUS_NOT_REPRODUCED, "stale")],
        shown=[cand(1)],
        dropped=[cand(2)],
    )
    # V1 omitted (counts), V2 dropped (counts; its check is ignored).
    assert statuses(result) == [
        ("V1", STATUS_NOT_CHECKED, True),
        ("V2", STATUS_DROPPED_FOR_BUDGET, True),
    ]
    assert result.candidates[1].reason == NOT_CHECKED_REASON
    assert result.counts.verifier_checks_ignored == 1


def test_a_dropped_candidate_alone_blocks():
    result = run(checks=[check("V1", STATUS_NOT_REPRODUCED)], dropped=[cand(1)])
    assert result.verdict == VERDICT_BLOCKING


def test_mixed_statuses_and_counts():
    result = run(
        checks=[
            check("V1", STATUS_CONFIRMED, "yes"),
            check("V2", STATUS_NOT_REPRODUCED, "no"),
        ],
        shown=[cand(1), cand(2), cand(3)],
        dropped=[cand(4)],
    )
    assert statuses(result) == [
        ("V1", STATUS_CONFIRMED, True),
        ("V2", STATUS_NOT_REPRODUCED, False),
        ("V3", STATUS_NOT_CHECKED, True),
        ("V4", STATUS_DROPPED_FOR_BUDGET, True),
    ]
    assert [c.id for c in result.counted_candidates] == ["V1", "V3", "V4"]
    c = result.counts
    assert c.verifier_candidates == 4
    assert c.verifier_confirmed == 3  # counted: §8.7 treats omitted as confirmed
    assert c.verifier_by_status == {
        STATUS_CONFIRMED: 1,
        STATUS_NOT_REPRODUCED: 1,
        STATUS_NOT_CHECKED: 1,
        STATUS_DROPPED_FOR_BUDGET: 1,
    }
    m = result.metrics()
    assert m["verifier_candidates"] == 4
    assert m["verifier_confirmed"] == 3
    assert m["verifier_by_status"] == c.verifier_by_status


# ---------------------------------------------------------------------------
# TC-211-12 — unknown and duplicate IDs (EC-30, DF-12)
# ---------------------------------------------------------------------------


def test_tc211_12_an_unknown_candidate_id_is_ignored():
    result = run(checks=[check("V9", STATUS_CONFIRMED)], shown=[cand(1)])
    assert statuses(result) == [("V1", STATUS_NOT_CHECKED, True)]
    assert result.counts.verifier_checks_ignored == 1


def test_tc211_12_an_unknown_confirmed_id_cannot_block_alone():
    result = run(checks=[check("V9", STATUS_CONFIRMED)])
    assert result.verdict == VERDICT_CLEAR
    assert result.candidates == ()


def test_ids_match_exactly_leading_zeros_do_not_alias():
    result = run(checks=[check("V01", STATUS_NOT_REPRODUCED)], shown=[cand(1)])
    assert statuses(result) == [("V1", STATUS_NOT_CHECKED, True)]
    assert result.verdict == VERDICT_BLOCKING


def test_tc211_12_duplicates_any_confirmed_wins_with_its_first_reason():
    result = run(
        checks=[
            check("V1", STATUS_NOT_REPRODUCED, "a"),
            check("V1", STATUS_CONFIRMED, "b"),
            check("V1", STATUS_CONFIRMED, "c"),
        ],
        shown=[cand(1)],
    )
    assert statuses(result) == [("V1", STATUS_CONFIRMED, True)]
    assert result.candidates[0].reason == "b"
    assert result.counts.verifier_checks_duplicate == 2


def test_tc211_12_duplicates_all_not_reproduced_keep_the_first_reason():
    result = run(
        checks=[check("V1", STATUS_NOT_REPRODUCED, "a"), check("V1", STATUS_NOT_REPRODUCED, "b")],
        shown=[cand(1)],
    )
    assert statuses(result) == [("V1", STATUS_NOT_REPRODUCED, False)]
    assert result.candidates[0].reason == "a"
    assert result.verdict == VERDICT_CLEAR


def test_duplicate_resolution_does_not_depend_on_order():
    a = run(
        checks=[check("V1", STATUS_CONFIRMED, "x"), check("V1", STATUS_NOT_REPRODUCED, "y")],
        shown=[cand(1)],
    )
    b = run(
        checks=[check("V1", STATUS_NOT_REPRODUCED, "y"), check("V1", STATUS_CONFIRMED, "x")],
        shown=[cand(1)],
    )
    assert a.candidates[0].status == b.candidates[0].status == STATUS_CONFIRMED


# ---------------------------------------------------------------------------
# TC-211-13 — clear cases (EC-31)
# ---------------------------------------------------------------------------


def test_tc211_13_every_blocking_finding_downgraded_and_no_candidates_is_clear():
    result = run(
        findings=[
            blocking_finding(line_start=1, line_end=1),
            blocking_finding(failure_scenario="​"),
        ]
    )
    assert result.blocking == ()
    assert result.verdict == VERDICT_CLEAR


def test_tc211_13_zero_findings_and_zero_candidates_is_clear():
    result = run()
    assert result.verdict == VERDICT_CLEAR
    assert result.counts.verifier_candidates == 0
    assert result.counts.verifier_confirmed == 0


def test_every_downgraded_but_an_omitted_candidate_still_blocks():
    result = run(findings=[blocking_finding(line_start=1, line_end=1)], shown=[cand(1)])
    assert result.verdict == VERDICT_BLOCKING


# ---------------------------------------------------------------------------
# The reason is untrusted: raw, length-capped
# ---------------------------------------------------------------------------


def test_the_model_reason_is_kept_raw_for_s212_to_neutralize():
    raw = "@someone <img src=x> `tick` ‮"
    result = run(checks=[check("V1", STATUS_NOT_REPRODUCED, raw)], shown=[cand(1)])
    assert result.candidates[0].reason == raw
    assert result.candidates[0].reason_from_model is True


def test_wrapper_reasons_are_flagged_as_not_from_the_model():
    result = run(shown=[cand(1)], dropped=[cand(2)])
    assert [c.reason_from_model for c in result.candidates] == [False, False]


def test_the_reason_is_capped():
    assert REASON_MAX_CHARS == 300
    long = "x" * (REASON_MAX_CHARS + 50)
    # Built in-process past the schema maximum (300): the cap still holds.
    statuses_ = candidate_statuses(
        [check("V1", STATUS_NOT_REPRODUCED, long)], shown=(cand(1),), dropped=()
    )
    assert statuses_[0].reason == "x" * REASON_MAX_CHARS


def test_candidate_statuses_direct_keeps_shown_then_dropped_order():
    out = candidate_statuses(
        [check("V3", STATUS_CONFIRMED)], shown=(cand(3), cand(1)), dropped=(cand(2),)
    )
    assert [(c.id, c.status) for c in out] == [
        ("V3", STATUS_CONFIRMED),
        ("V1", STATUS_NOT_CHECKED),
        ("V2", STATUS_DROPPED_FOR_BUDGET),
    ]


def test_an_unbounded_check_list_is_linear():
    checks = [check(f"V{k % 1000}", STATUS_NOT_REPRODUCED) for k in range(200_000)]
    shown = tuple(cand(k) for k in range(1, 1001))
    start = time.perf_counter()
    out = candidate_statuses(checks, shown=shown, dropped=())
    assert time.perf_counter() - start < 2.0
    assert all(c.status == STATUS_NOT_REPRODUCED for c in out)
