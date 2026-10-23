"""
RT-08 (test plan §9, S-211): findings validation and verdict properties.

Seed 413001 (test plan), 3,000 iterations. The generator draws random changed
ranges per file, random findings (severity, a file in or out of the PR, path
variants, lines near range edges, swapped lines, blank or non-blank scenario
and consequence, duplicate and huge ranks) and random candidates and checks
(confirmed, not_reproduced, unknown and duplicate IDs, checks on dropped IDs).

Properties (oracle-free or metamorphic, with an independent location oracle):

- no output blocking finding lies outside the ±3-widened ranges or has a
  blank scenario; no output finding has a blank consequence;
- suggestions ≤ ``max_suggestions``; blocking findings are never capped (the
  output keeps every finding the oracle says must stay blocking);
- IDs are contiguous ``B1..Bn``, ``S1..Sm``, in (rank, model order);
- conservation: input = kept + dropped;
- ``verdict == blocking`` ⇔ (kept blocking ≥ 1 or counted candidate ≥ 1);
- monotone: adding a valid in-diff blocking finding never makes the verdict
  ``clear`` and never removes a blocking finding;
- deterministic: the same input gives an equal result.

Replay: ``PRNG_SEED=413001 PRNG_ITER=<i> make test-unit -k rt08``.
"""

from __future__ import annotations

import copy
import random

from context.verifier import Candidate
from findings_schema import CATEGORIES, MAX_FINDINGS
from tests.helpers.prng import Tactic, tactic_seed
from validate import (
    STATUS_CONFIRMED,
    STATUS_NOT_REPRODUCED,
    VERDICT_BLOCKING,
    VERDICT_CLEAR,
    validate,
)

SEED = tactic_seed(413, 1)
ITERATIONS = 3_000

BLANK_POOL = ["", " ", "\n\t", "​", "　﻿", "  ⁠"]
TEXT_POOL = ["x", " fails when n = 0 ", "​z", "raises KeyError", "@user <b>hi</b>"]
FILES = ["src/a.py", "src/b.py", "lib/c.ts", "docs/r.md"]
OUTSIDE = ["nope.py", "src/A.py", "src\\a.py", "src/../src/a.py", " src/a.py"]


def _ranges(rng: random.Random) -> dict[str, tuple[tuple[int, int], ...]]:
    out: dict[str, tuple[tuple[int, int], ...]] = {}
    for name in rng.sample(FILES, rng.randint(0, len(FILES))):
        ranges: list[tuple[int, int]] = []
        cursor = 1
        for _ in range(rng.randint(0, 4)):
            start = cursor + rng.randint(0, 20)
            end = start + rng.randint(0, 6)
            ranges.append((start, end))
            cursor = end + 2  # merged ranges are disjoint and non-adjacent
        out[name] = tuple(ranges)
    return out


def _line(rng: random.Random, ranges: tuple[tuple[int, int], ...]) -> int:
    if ranges and rng.random() < 0.7:
        a, b = rng.choice(ranges)
        return max(1, rng.choice([a - 4, a - 3, a - 2, a, b, b + 2, b + 3, b + 4]))
    return rng.choice([1, 2, 50, 10**6, 10**300])


def _file(rng: random.Random, ranges: dict[str, tuple[tuple[int, int], ...]]) -> str:
    if ranges and rng.random() < 0.75:
        name = rng.choice(sorted(ranges))
        return rng.choice([name, "./" + name, "/" + name, "`" + name + "`"])
    return rng.choice(OUTSIDE)


def _finding(rng: random.Random, ranges: dict[str, tuple[tuple[int, int], ...]]) -> dict:
    file = _file(rng, ranges)
    file_ranges = ranges.get(file.strip("`").lstrip("./"), ())
    start, end = _line(rng, file_ranges), _line(rng, file_ranges)
    if rng.random() < 0.6:
        start, end = min(start, end), max(start, end)
    return {
        "severity": rng.choice(["blocking", "blocking", "suggestion"]),
        "category": rng.choice(CATEGORIES),
        "file": file,
        "line_start": start,
        "line_end": end,
        "title": rng.choice(TEXT_POOL),
        "failure_scenario": rng.choice(BLANK_POOL if rng.random() < 0.3 else TEXT_POOL),
        "consequence": rng.choice(BLANK_POOL if rng.random() < 0.2 else TEXT_POOL),
        "rank": rng.choice([1, 1, 2, 3, rng.randint(1, 50), 10**300]),
    }


def _candidate(k: int) -> Candidate:
    return Candidate(f"V{k}", "workstream/fidelity-report-S-1.md", k, k + 10, f"| row {k} |", False)


def _case(rng: random.Random) -> dict:
    ranges = _ranges(rng)
    n = rng.randint(0, MAX_FINDINGS - 1)  # one slot left for the monotone step
    findings = [_finding(rng, ranges) for _ in range(n)]
    total = rng.randint(0, 5)
    candidates = [_candidate(k) for k in range(1, total + 1)]
    cut = rng.randint(0, total)
    shown, dropped = candidates[:cut], candidates[cut:]
    checks = []
    for _ in range(rng.randint(0, 8)):
        cid = rng.choice([f"V{rng.randint(0, 7)}", "V01", "V1"])
        checks.append(
            {
                "candidate_id": cid,
                "status": rng.choice([STATUS_CONFIRMED, STATUS_NOT_REPRODUCED]),
                "reason": rng.choice(TEXT_POOL),
            }
        )
    return {
        "ranges": ranges,
        "review": {"findings": findings, "verifier_checks": checks},
        "shown": tuple(shown),
        "dropped": tuple(dropped),
        "max_suggestions": rng.randint(0, 6),
    }


def _run(case: dict):
    return validate(
        copy.deepcopy(case["review"]),
        changed_ranges=case["ranges"],
        shown_candidates=case["shown"],
        dropped_candidates=case["dropped"],
        max_suggestions=case["max_suggestions"],
    )


def _oracle_blank(text: str) -> bool:
    return all(c in "".join(BLANK_POOL) for c in text)


def _oracle_canonical(raw: str, ranges: dict) -> str | None:
    for candidate in (raw, raw.strip("`").removeprefix("./").removeprefix("/")):
        if candidate in ranges:
            return candidate
    return None


def _oracle_in_diff(start: int, end: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    lo, hi = min(start, end), max(start, end)
    return any(a - 3 <= hi and lo <= b + 3 for a, b in ranges)


def _oracle_must_block(f: dict, ranges: dict) -> bool:
    name = _oracle_canonical(f["file"], ranges)
    return (
        name is not None
        and f["severity"] == "blocking"
        and _oracle_in_diff(f["line_start"], f["line_end"], ranges[name])
        and not _oracle_blank(f["failure_scenario"])
        and not _oracle_blank(f["consequence"])
    )


def _check(case: dict, result) -> None:
    ranges = case["ranges"]
    findings = case["review"]["findings"]
    for f in result.blocking:
        assert f.file in ranges
        assert _oracle_in_diff(f.line_start, f.line_end, ranges[f.file])
        assert f.line_start <= f.line_end
        assert not _oracle_blank(f.failure_scenario)
    for f in result.findings:
        assert not _oracle_blank(f.consequence)
    assert len(result.suggestions) <= case["max_suggestions"]
    # Never capped: every finding that must block is kept, as blocking.
    expected = sorted(i for i, f in enumerate(findings) if _oracle_must_block(f, ranges))
    assert sorted(f.index for f in result.blocking) == expected
    assert [f.id for f in result.blocking] == [f"B{k}" for k in range(1, len(result.blocking) + 1)]
    assert [f.id for f in result.suggestions] == [
        f"S{k}" for k in range(1, len(result.suggestions) + 1)
    ]
    for group in (result.blocking, result.suggestions):
        keys = [(f.rank, f.index) for f in group]
        assert keys == sorted(keys)
    assert len(findings) == len(result.findings) + len(result.dropped)
    assert result.counts.findings_in == len(findings)
    counted = [c for c in result.candidates if c.counted]
    assert (result.verdict == VERDICT_BLOCKING) == (bool(result.blocking) or bool(counted))
    assert result.verdict in (VERDICT_BLOCKING, VERDICT_CLEAR)
    # Every dropped-for-budget candidate counts.
    dropped_ids = {c.id for c in case["dropped"]}
    assert all(c.counted for c in result.candidates if c.candidate.id in dropped_ids)
    assert [c.candidate for c in result.candidates] == [*case["shown"], *case["dropped"]]


def test_rt08_validation_and_verdict_properties():
    tactic = Tactic.from_env(SEED, ITERATIONS)
    rng = tactic.rng()
    for i in range(tactic.iterations):
        case = _case(rng)
        if not tactic.selected(i):
            continue
        try:
            result = _run(case)
            _check(case, result)
            assert _run(case) == result  # deterministic
            # Monotone: add one valid, in-diff blocking finding.
            if case["ranges"] and any(case["ranges"].values()):
                name = sorted(n for n, r in case["ranges"].items() if r)[0]
                a, _b = case["ranges"][name][0]
                extra = copy.deepcopy(case)
                extra["review"]["findings"].append(
                    {
                        "severity": "blocking",
                        "category": "correctness",
                        "file": name,
                        "line_start": a,
                        "line_end": a,
                        "title": "t",
                        "failure_scenario": "s",
                        "consequence": "c",
                        "rank": 1,
                    }
                )
                grown = _run(extra)
                _check(extra, grown)
                assert grown.verdict == VERDICT_BLOCKING
                assert len(grown.blocking) == len(result.blocking) + 1
                assert {f.index for f in result.blocking} <= {f.index for f in grown.blocking}
        except AssertionError as exc:
            raise AssertionError(tactic.context(i, case)) from exc
