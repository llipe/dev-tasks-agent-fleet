"""
RT-05 (S-208) — drift-row parsing property tactic, seed 410001, 3,000 iterations.

Random Markdown drift tables with cells drawn from {``Critical``, ``Major``,
``Minor``, ``Unintended``, ``Intended``, ``Undetermined``, ``Non-critical``,
``CRITICAL``, escaped ``\\|``, noise}, with random outer pipes and line endings,
spread over 0-3 reports (some missing, some without a drift heading).
Properties, checked against an independent reference:

- a data row is a candidate iff it contains the whole, case-sensitive words
  ``Critical`` and ``Unintended`` (reference: split on non-``[A-Za-z0-9_]``);
  header and separator rows are never candidates;
- the candidate text equals the source line byte for byte (rows here are
  under the 300-token cap);
- IDs are contiguous ``V1…Vk`` across reports, in report then row order;
- candidates + other drift = data rows, per report.
"""

from __future__ import annotations

import random
import re

from context.verifier import (
    REPORT_NONE,
    REPORT_NOT_PARSEABLE,
    REPORT_PARSED,
    build_verifier_context,
)
from tests.helpers.prng import Tactic, tactic_seed

SEED = tactic_seed(410, 1)
ITERATIONS = 3000

WORDS = [
    "Critical",
    "Major",
    "Minor",
    "Unintended",
    "Intended",
    "Undetermined",
    "Non-critical",
    "CRITICAL",
    "**Critical**",
    "Non-Critical",
    "Unintentional",
    "a \\| b",
    "Critical\\|Unintended",
    "noise",
    "x_Critical",
    "",
]
ENDINGS = ["\n", "\r\n", "\r"]


def _reference_candidate(line: str) -> bool:
    words = set(re.split(r"[^A-Za-z0-9_]", line))
    return "Critical" in words and "Unintended" in words


def _row(rng: random.Random, cols: int) -> str:
    cells = [" ".join(rng.choice(WORDS) for _ in range(rng.randint(1, 3))) for _ in range(cols)]
    body = " | ".join(cells)
    lead = rng.choice(["| ", "|", ""])
    trail = rng.choice([" |", "|", ""]) if lead else rng.choice([" |", ""])
    if not lead and not trail and cols == 1:
        lead = "| "
    return lead + body + trail


def _report(rng: random.Random) -> tuple[str | None, list[tuple[str, bool]], bool]:
    """(text, [(data row, expected candidate)], parseable); ``None`` text = 404."""
    kind = rng.random()
    if kind < 0.1:
        return None, [], False
    cols = rng.randint(1, 5)
    header_words = ["#", "Finding", "Critical", "Unintended", "Impact", "Intent"]
    header = "| " + " | ".join(rng.choice(header_words) for _ in range(cols)) + " |"
    delimiter = "| " + " | ".join(rng.choice(["---", ":---", "---:", ":-:"]) for _ in range(cols))
    delimiter += " |"
    rows = [_row(rng, cols) for _ in range(rng.randint(0, 8))]
    heading = rng.choice(
        [
            "## Drift",
            "### Drift catalog",
            "## Drift (rolled up)",
            "## 4. Drift Catalog",
            "## 3 Drift",
        ]
    )
    if kind < 0.2:
        heading = rng.choice(["## Findings", "## 1234. Drift catalog", "# Drift"])
    lines = ["# Report", "", heading, "", header, delimiter, *rows, "", "## Gates", "", "- ok"]
    end = rng.choice(ENDINGS)
    text = end.join(lines) + end
    if kind < 0.2:
        return text, [], False
    return text, [(r, _reference_candidate(r)) for r in rows], True


def _case(rng: random.Random):
    reports = []
    for k in range(rng.randint(0, 3)):
        text, rows, parseable = _report(rng)
        reports.append((f"workstream/fidelity-report-S-{k + 1}.md", k + 1, text, rows, parseable))
    return reports


def test_rt05_drift_row_parsing_properties():
    tactic = Tactic.from_env(SEED, ITERATIONS)
    rng = tactic.rng()
    seen_candidates = 0
    for i in range(tactic.iterations):
        reports = _case(rng)
        if not tactic.selected(i):
            continue
        ctx_msg = tactic.context(i, [(p, t) for p, _, t, _, _ in reports])
        ctx = build_verifier_context([(p, n, t) for p, n, t, _, _ in reports])
        assert [c.id for c in ctx.candidates] == [
            f"V{k}" for k in range(1, len(ctx.candidates) + 1)
        ], ctx_msg
        expected_all: list[tuple[str, str, int]] = []
        for report, (path, _, text, rows, parseable) in zip(ctx.reports, reports, strict=True):
            assert report.path == path, ctx_msg
            if text is None:
                assert report.state == REPORT_NONE, ctx_msg
                continue
            if not parseable:
                assert report.state == REPORT_NOT_PARSEABLE, ctx_msg
                assert report.candidates == () and report.other_drift == 0, ctx_msg
                continue
            assert report.state == REPORT_PARSED, ctx_msg
            assert len(report.candidates) + report.other_drift == len(rows), ctx_msg
            expected = [(r, idx) for idx, (r, cand) in enumerate(rows, start=1) if cand]
            assert [(c.text, c.row_index) for c in report.candidates] == expected, ctx_msg
            assert all(not c.truncated for c in report.candidates), ctx_msg
            expected_all += [(path, r, idx) for r, idx in expected]
        assert [(c.report_path, c.text, c.row_index) for c in ctx.candidates] == expected_all, (
            ctx_msg
        )
        seen_candidates += len(ctx.candidates)
    if not tactic.replaying:
        assert seen_candidates > 500
