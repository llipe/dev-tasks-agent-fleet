"""
RT-06 (test plan §9, S-212): comment truncation and neutralization properties.

Seed 414001 (test plan), 1,000 iterations. The generator draws 0–40 blocking
findings and 0–20 suggestions with field lengths up to the schema maxima
(400-char paths, 200-char titles, 1,500-char scenarios, 500-char
consequences), text from a hostile alphabet (``@``, HTML, backticks, ``-->``,
``/review``, ``&``, pipes, newlines, Unicode), line numbers up to ``10**300``,
and 0–5 verifier rows (sometimes hundreds, as S-208 allows) in every status.

Properties, on every rendered body:

- ``len(body) <= 60,000`` (so always under GitHub's 65,536);
- the first line is the marker and the third the verdict header, unchanged
  by truncation; the verdict is the validation's;
- untruncated bodies are exactly what an unlimited render gives, and carry
  no truncation note; truncated ones carry it;
- suggestions are dropped before any scenario cut (stage 2 implies no
  ``<details>`` left), and stages apply in order;
- no ``@`` without U+200B after it; no raw ``<`` from content; exactly one
  ``<!--`` and one ``-->``; the body never starts with ``/review``.

Replay: ``PRNG_SEED=414001 PRNG_ITER=<i> make test-unit -k rt06``.
"""

from __future__ import annotations

import random
import re

from render import MAX_COMMENT_CHARS, TRUNCATION_NOTE, render_review
from tests.helpers.prng import Tactic, tactic_seed
from tests.helpers.render_inputs import (
    HEAD,
    MODEL,
    PANEL,
    REPORT,
    REPORT_PARSED,
    RUN_ID,
    candidate,
    clear_fixture,
    context_data,
    finding,
    report,
    status,
    validation,
    verifier_ctx,
)
from validate import (
    STATUS_CONFIRMED,
    STATUS_DROPPED_FOR_BUDGET,
    STATUS_NOT_CHECKED,
    STATUS_NOT_REPRODUCED,
)

SEED = tactic_seed(414, 1)
ITERATIONS = 1_000

ATOMS = [
    "@",
    "@everyone",
    "<",
    "</details>",
    "<!--",
    "-->",
    "`",
    "&",
    "&#64;",
    "|",
    "\n",
    "\r\n",
    " ",
    "/review ",
    "# ",
    "[x](javascript:1)",
    "![](http://t)",
    "https://e.x",
    "www.e.x",
    "#12",
    "é",
    "漢字",
    "🙂",
    "‮",
    "\\",
    "*",
    "_",
    "a",
    "word ",
]
CATEGORIES = ("correctness", "edge_case", "maintainability", "intent")
STATES = (STATUS_CONFIRMED, STATUS_NOT_REPRODUCED, STATUS_NOT_CHECKED, STATUS_DROPPED_FOR_BUDGET)
WRAPPER_TAGS = ("<details><summary>", "</summary>", "</details>", "<sub>", "</sub>")


def _text(rng: random.Random, limit: int) -> str:
    if rng.random() < 0.15:
        return rng.choice(["<", "&", "@", "a"]) * limit  # escape-heavy, at the maximum
    target = rng.choice([0, 1, rng.randint(0, limit), limit])
    if target == 0:
        return ""
    unit = "".join(rng.choice(ATOMS) for _ in range(rng.randint(1, 12)))
    return (unit * (target // len(unit) + 1))[:target]


def _line(rng: random.Random) -> int:
    return rng.choice([1, 2, 120, 10**9, 10**300, rng.randint(1, 10**6)])


def _finding(rng: random.Random, fid: str):
    start = _line(rng)
    end = start + rng.choice([0, 0, 1, 14, 10**300])
    return finding(
        fid,
        category=rng.choice(CATEGORIES),
        file=_text(rng, 400) or "x.py",
        line_start=start,
        line_end=end,
        title=_text(rng, 200),
        failure_scenario=_text(rng, 1500) or "s",
        consequence=_text(rng, 500) or "c",
        downgraded=rng.choice([None, "outside_diff", "no_scenario"]) if fid[0] == "S" else None,
    )


def _case(rng: random.Random) -> dict:
    blocking = [_finding(rng, f"B{k}") for k in range(1, rng.randint(0, 40) + 1)]
    suggestions = [_finding(rng, f"S{k}") for k in range(1, rng.randint(0, 20) + 1)]
    n = rng.choice([0, 1, 2, 3, 4, 5, rng.randint(0, 400)])
    cands = [
        candidate(k, _text(rng, 1050) or "|", report=_text(rng, 60) or REPORT)
        for k in range(1, n + 1)
    ]
    statuses = [status(c, rng.choice(STATES), _text(rng, 300)) for c in cands]
    fx = clear_fixture()
    fx["validation"] = validation(blocking, suggestions, statuses)
    fx["verifier"] = verifier_ctx(
        report(REPORT, REPORT_PARSED, candidates=cands, other_drift=rng.randint(0, 9))
    )
    fx["context"] = context_data(
        issue_numbers=tuple(range(1, rng.randint(0, 5) + 1)),
        spec_paths=(_text(rng, 120),) if rng.random() < 0.5 else (),
        full_files_included=("k.py",) if rng.random() < 0.5 else (),
        full_files_dropped=tuple(_text(rng, 80) for _ in range(rng.randint(0, 30))),
        verifier_state=REPORT_PARSED,
    )
    return fx


def _render(fx: dict, **kw):
    return render_review(
        fx["validation"],
        context=fx["context"],
        diff=fx["diff"],
        verifier=fx["verifier"],
        run_id=RUN_ID,
        head_sha=HEAD,
        model_id=MODEL,
        rubric_version="1",
        panel_base_url=PANEL,
        **kw,
    )


def render_size(body: str) -> int:
    return len(body.encode("utf-16-le")) // 2


def _listed_or_counted(body: str, kind: str, noun: str) -> int:
    """Entries rendered for ``kind`` (B or V) plus the ones a "not shown" line counts."""
    listed = len(re.findall(rf"^(?:- )?\*\*{kind}\d+ [·(]", body, re.M))
    missing = re.search(rf"(\d+) (?:more )?{noun} not shown\.$", body, re.M)
    return listed + (int(missing.group(1)) if missing else 0)


def _content_lt(body: str) -> int:
    rest = body.split("\n", 1)[1]
    for tag in WRAPPER_TAGS:
        rest = rest.replace(tag, "")
    return rest.count("<")


def test_rt06_comment_truncation_and_neutralization():
    tactic = Tactic.from_env(SEED, ITERATIONS)
    rng = tactic.rng()
    truncated_seen = 0
    for i in range(ITERATIONS):
        fx = _case(rng)
        if not tactic.selected(i):
            continue
        out = _render(fx)
        body = out.body
        ctx = tactic.context(i, (len(fx["validation"].blocking), len(fx["validation"].suggestions)))
        assert len(body) <= MAX_COMMENT_CHARS, ctx
        lines = body.split("\n")
        assert lines[0] == f"<!-- code-review-agent:v1 run={RUN_ID} sha={HEAD} -->", ctx
        assert lines[2] == f"## Code review: **{fx['validation'].verdict}** · `{HEAD[:7]}`", ctx
        assert not body.startswith("/review"), ctx
        assert body.count("<!--") == 1 and body.count("-->") == 1, ctx
        assert not re.search(r"@(?!​)", body), ctx
        assert _content_lt(body) == 0, ctx
        assert body.endswith("</sub>\n"), ctx
        assert render_size(body) <= MAX_COMMENT_CHARS, ctx  # UTF-16 units too (DR-9)
        n_cands = len(fx["validation"].candidates)
        assert _listed_or_counted(body, "V", "verifier candidates?") == n_cands, ctx  # DR-4
        n_block = len(fx["validation"].blocking)
        assert _listed_or_counted(body, "B", "blocking findings?") == n_block, ctx  # D2
        assert list(out.stages) == sorted(set(out.stages)), ctx
        if out.truncated:
            truncated_seen += 1
            assert TRUNCATION_NOTE in body, ctx
            if 2 in out.stages:
                assert "<details>" not in body, ctx  # suggestions went first
        else:
            assert out.stages == (), ctx
            assert TRUNCATION_NOTE not in body, ctx
            if i % 10 == 0:
                assert _render(fx, limit=10**9).body == body, ctx
    if not tactic.replaying:
        assert truncated_seen > 50  # the generator reaches the truncation stages
