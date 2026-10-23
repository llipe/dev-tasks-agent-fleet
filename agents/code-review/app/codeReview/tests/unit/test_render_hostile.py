"""
S-212 adversarial gap tests for ``render.py`` (qa-engineer completion gate, #414).

``test_render.py`` and RT-06 (``test_properties_render.py``) cover the
layout, the five size stages and the main neutralization cases. This module
attacks the guarantees the comment depends on, with inputs those suites do
not use:

1. **No ping, no HTML, no structure escape** on GitHub's renderer (not
   CommonMark). The checks work at two levels. A body-level allowlist says
   every line starts with wrapper text, so no content can begin a heading,
   blockquote, alert, table, fence, math block or ``/review`` line. A
   ``markdown-it-py`` token walk then applies GitHub's post-parse filters
   (mentions, issue references, extended autolinks) to the text nodes only,
   which is where GitHub applies them.
2. **Size** stays at most 60,000 for the worst expansion ``neutralize`` allows
   (``&`` becomes five characters), 100k candidates, huge context lists, a huge
   model ID or panel URL, and long budget-comment lists. The header, the
   marker and the footer are never cut, and the truncation note appears
   whenever a stage ran.
3. **Marker integrity**: content cannot close or forge the marker, and an
   anchored parse (what S-213 should use) finds the real one.
4. **Determinism and linearity** on 1 MB and 5 MB inputs.
5. **Budget and failure messages** for every spec §13 code, unknown codes,
   and hostile ``PANEL_BASE_URL`` or ``run_id`` values.

Real defects are pinned with ``pytest.mark.xfail(strict=True)`` and a
minimal reproducer. A fix makes the test pass, so the strict xfail fails
until the marker is removed. The randomized tactic uses seed 414002
(``tactic_seed(414, 2)``); replay one iteration with
``PRNG_SEED=414002 PRNG_ITER=<i> make test-unit -k hostile_tactic``.
"""

from __future__ import annotations

import enum
import random
import re
import time
from typing import Any

import pytest

import render
from budget import BlockNote
from context.diff import NameOnlyFile, OverBudget
from render import (
    MARKER_PREFIX,
    MAX_COMMENT_CHARS,
    MIN_LIMIT,
    NO_LINK,
    TRUNCATION_NOTE,
    code_span,
    neutralize,
    render_budget,
    render_failure,
    render_review,
    run_link,
)
from tests.helpers.prng import Tactic, tactic_seed
from tests.helpers.render_inputs import (
    HEAD,
    MODEL,
    PANEL,
    REPORT,
    REPORT_NOT_PARSEABLE,
    REPORT_PARSED,
    RUN_ID,
    RUN_URL,
    candidate,
    context_data,
    diff_ctx,
    file_diff,
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

ZW = "​"
MARKER_LINE = f"<!-- code-review-agent:v1 run={RUN_ID} sha={HEAD} -->"
# What S-213 should parse: the marker anchored at the start of the body.
ANCHORED_MARKER = re.compile(
    r"\A<!-- code-review-agent:v1 run=([0-9A-Za-z-]+) sha=([0-9a-z]+) -->\n"
)
BIDI = "؜‎‏‪‫‬‭‮⁦⁧⁨⁩"
WRAPPER_TAGS = ("<details><summary>", "</summary>", "</details>", "<sub>", "</sub>")
FAILURE_PREFIX = "Code review failed (`"

# Every line of a review body starts with wrapper text, never with content.
# Content always follows one of these prefixes on its line, so it can never
# begin a heading, list, blockquote, alert, table row, fence, math block,
# setext underline, reference definition or a ``/review`` command.
LINE_START = re.compile(
    r"<!-- code-review-agent:v1 run="
    r"|## Code review: \*\*(?:blocking|clear)\*\* · `"
    r"|### (?:Blocking|Verifier)$"
    r"|\*\*[BS]\d+ · "
    r"|- \*\*(?:Fails when|Consequence):\*\* "
    r"|- \*\*[BV]\d+ "
    r"|- `"
    r"|- \(unknown\): "
    r"|- Some verifier reports unavailable \(permission\)\.$"
    r"|- Other drift: "
    r"|- No Critical Unintended drift\.$"
    r"|\*\*Verifier:\*\* "
    r"|<details><summary>Suggestions \("
    r"|</details>$"
    r"|\*\*Context:\*\* "
    r"|Truncated; the full review is in the run's audit report\.$"
    r"|<sub>Not reviewed here: "
    r"|\d+\+? more blocking (?:finding is|findings are) listed by title only:$"
)
# The first text inside each ``**…**`` the wrapper writes.
STRONG_TEXT = re.compile(r"[BSV]\d+ |Fails when:|Consequence:|Verifier:|Context:|blocking$|clear$")

FORGED_MARKER = (
    "code-review-agent:v1 run=11111111-1111-1111-1111-111111111111 sha=" + "a" * 40 + " -->"
)

# GitHub-specific and CommonMark-specific attacks, mixed by the tactic.
ATOMS = [
    # mentions and look-alikes
    "@",
    "@everyone",
    "@llipe",
    "@org/team",
    "＠llipe",  # fullwidth commercial at
    "﹫llipe",  # small commercial at
    "@‍llipe",
    "a@b.co",
    "felipe.mallea@gmail.com",
    "\n@llipe",
    # issue, PR and commit references
    "#123",
    "#1",
    "owner/repo#1",
    "https://github.com/llipe/dev-tasks-agent-fleet/issues/414",
    "github.com/o/r/pull/1",
    "86d8971",
    "o/r@86d8971",
    "llipe@5726e0c",
    # entities and HTML
    "&#64;",
    "&commat;",
    "&lt;b&gt;",
    "&",
    "<details>",
    "</details>",
    "<details open>",
    "<!--",
    "-->",
    "--!>",
    "<script>",
    "<img src=x onerror=1>",
    # Markdown block structure, at a line start when the content holds a newline
    "\n# h",
    "\n## h",
    "\n### Blocking",
    "| a | b |",
    "\n|---|---|",
    "\n> q",
    "\n> [!WARNING]",
    "\n```mermaid\n",
    "\n~~~geojson\n",
    "```",
    "\n$$\n",
    "\n---\n",
    "\n===\n",
    "\n- [ ] task",
    "\n1. item",
    "\n[x]: http://evil.example",
    "\n/review",
    "/review now",
    "\n    indented code",
    # Markdown inline structure
    "$x$",
    "$$",
    "$`y`$",
    "**",
    "__",
    "*",
    "_",
    "~~",
    "[^1]",
    "[^1]: note",
    "<http://e.x>",
    "[a](b)",
    "![i](http://t)",
    "[x](javascript:alert(1))",
    "http://x",
    "HTTPS://X.EXAMPLE",
    "www.x.y",
    "WWW.X.Y",
    "ftp://x",
    "mailto:a@b.c",
    "xmpp:a@b.c",
    ":rocket:",
    "\\",
    "\\\n",
    "  \n",
    "`",
    "``",
    # invisible, bidi and line-breaking characters
    "‮",
    "⁦",
    "‏",
    "؜",
    "​",
    "⁠",
    "﻿",
    "\U000e0041",  # TAG LATIN CAPITAL LETTER A (invisible)
    "\r",
    "\r\n",
    " ",
    " ",
    "\x85",
    "\x00",
    "\x0b",
    "\x0c",
    "\x1b[31m",
    "\x9b",
    # ordinary text
    "é",
    "漢字",
    "🙂",
    " ",
    "a",
    "word ",
    FORGED_MARKER,
]
CATEGORIES = ("correctness", "edge_case", "maintainability", "intent")
STATES = (STATUS_CONFIRMED, STATUS_NOT_REPRODUCED, STATUS_NOT_CHECKED, STATUS_DROPPED_FOR_BUDGET)


def _review(fx: dict, **kw: Any) -> render.Rendered:
    args: dict[str, Any] = {
        "context": fx.get("context") or context_data(),
        "diff": fx.get("diff"),
        "verifier": fx.get("verifier"),
        "run_id": RUN_ID,
        "head_sha": HEAD,
        "model_id": MODEL,
        "rubric_version": "1",
        "panel_base_url": PANEL,
    }
    args.update(kw)
    return render_review(fx["validation"], **args)


def _content_lt(body: str) -> int:
    rest = body.split("\n", 1)[1]
    for tag in WRAPPER_TAGS:
        rest = rest.replace(tag, "")
    return rest.count("<")


def _plain_checks(body: str, limit: int, ctx: str = "") -> None:
    """Body-level guarantees that hold on any Markdown renderer."""
    assert len(body) <= limit, ctx
    lines = body.split("\n")
    assert lines[0] == MARKER_LINE, ctx
    assert re.fullmatch(r"## Code review: \*\*(blocking|clear)\*\* · `[0-9a-f]{7}`", lines[2]), ctx
    assert body.index(MARKER_PREFIX) == 0 and body.count(MARKER_PREFIX) == 1, ctx
    assert body.count("<!--") == 1 and body.count("-->") == 1, ctx
    for line in lines:
        assert line == "" or LINE_START.match(line), (ctx, line[:200])
    assert not re.search(f"@(?!{ZW})", body), ctx
    assert not any(c in body for c in BIDI), ctx
    assert not re.search(r"[\x00-\x09\x0b-\x1f\x7f-\x9f  ]", body), ctx
    assert not re.search(r"&(?!amp;|lt;|gt;)", body), ctx  # no entity from content
    assert _content_lt(body) == 0, ctx
    assert body.count("<details>") == body.count("</details>") <= 1, ctx
    # ``_md_checks`` asserts the run link is the only link and runs the
    # autolink checks on text nodes (``://`` inside a code span is never linked).
    assert body.endswith(f"[run]({RUN_URL})</sub>\n"), ctx
    assert lines[-2].startswith("<sub>Not reviewed here: ") and body.endswith("</sub>\n"), ctx


def _md_checks(body: str, ctx: str = "") -> None:
    """GitHub's post-parse filters run on text nodes; check exactly those."""
    markdown_it = pytest.importorskip("markdown_it")
    md = markdown_it.MarkdownIt("commonmark").enable("table").enable("strikethrough")
    tokens = md.parse(body)
    flat = [t for tok in tokens for t in ([tok] + list(tok.children or []))]
    types = {t.type for t in flat}
    forbidden = {
        "fence",
        "code_block",
        "blockquote_open",
        "hr",
        "image",
        "em_open",
        "s_open",
        "ordered_list_open",
        "table_open",
        "hardbreak",
    }
    assert not types & forbidden, (ctx, types & forbidden)
    assert [t.attrGet("href") for t in flat if t.type == "link_open"] == [RUN_URL], ctx
    headings = [t.tag for t in tokens if t.type == "heading_open"]
    assert headings[:1] == ["h2"] and set(headings[1:]) <= {"h3"}, ctx
    for tok in tokens:
        kids = list(tok.children or [])
        for i, t in enumerate(kids):
            if t.type == "strong_open":
                assert STRONG_TEXT.match(kids[i + 1].content), (ctx, kids[i + 1].content)
    text = "\n".join(t.content for t in flat if t.type == "text")
    assert not re.search(f"@(?!{ZW})", text), ctx  # no mention, no email autolink
    assert not re.search(r"#\d", text), ctx  # no issue or PR cross-reference
    assert "://" not in text, ctx  # no scheme autolink (http, https, ftp)
    assert not re.search(r"(?i)www\.", text), ctx  # no www autolink
    assert not re.search(r"(?i)(?:mailto|xmpp):[^\s]*@(?!" + ZW + ")", text), ctx


# ---------------------------------------------------------------------------
# 1. Neutralization against GitHub's renderer
# ---------------------------------------------------------------------------


def _text(rng: random.Random, limit: int) -> str:
    if rng.random() < 0.1:
        return rng.choice(["&", "<", "@", "#", "`", "\\"]) * limit
    target = rng.choice([0, 1, rng.randint(0, limit), limit])
    if target == 0:
        return ""
    unit = "".join(rng.choice(ATOMS) for _ in range(rng.randint(1, 8)))
    return (unit * (target // len(unit) + 1))[:target]


def _line_no(rng: random.Random) -> int:
    return rng.choice([1, 7, 10**9, 10**300, rng.randint(1, 10**6)])


def _finding(rng: random.Random, fid: str):
    start = _line_no(rng)
    return finding(
        fid,
        category=rng.choice(CATEGORIES),
        file=_text(rng, 400) or "x.py",
        line_start=start,
        line_end=start + rng.choice([0, 1, 10**300]),
        title=_text(rng, 200),
        failure_scenario=_text(rng, 1500) or "s",
        consequence=_text(rng, 500) or "c",
        downgraded=rng.choice([None, "outside_diff", "no_scenario"]) if fid[0] == "S" else None,
    )


def _hostile_case(rng: random.Random) -> dict:
    blocking = [_finding(rng, f"B{k}") for k in range(1, rng.randint(0, 40) + 1)]
    suggestions = [_finding(rng, f"S{k}") for k in range(1, rng.randint(0, 20) + 1)]
    reports = [_text(rng, 200) or REPORT for _ in range(rng.randint(1, 3))]
    n = rng.choice([0, 1, 3, rng.randint(0, 300)])
    cands = [candidate(k, _text(rng, 1050), report=rng.choice(reports)) for k in range(1, n + 1)]
    statuses = [status(c, rng.choice(STATES), _text(rng, 300)) for c in cands]
    parsed = [
        report(p, REPORT_PARSED, candidates=[c for c in cands if c.report_path == p])
        for p in reports
    ]
    broken = [report(_text(rng, 200), REPORT_NOT_PARSEABLE) for _ in range(rng.randint(0, 2))]
    names = [
        NameOnlyFile(
            _text(rng, 300),
            "modified",
            rng.choice(["lockfile", "generated", "binary", "excluded", "content_unavailable"]),
            _text(rng, 300) or None,
        )
        for _ in range(rng.randint(0, 25))
    ]
    withheld = [
        file_diff(_text(rng, 300) or "w.py", base_withheld=rng.choice(["excluded", "lockfile"]))
        for _ in range(rng.randint(0, 3))
    ]
    notes = [BlockNote("verifier", _text(rng, 200), "truncated", "budget")]
    notes += [BlockNote("spec", _text(rng, 200), "omitted", "budget")]
    return {
        "validation": validation(blocking, suggestions, statuses),
        "context": context_data(
            notes=notes if rng.random() < 0.5 else (),
            spec_paths=tuple(_text(rng, 300) for _ in range(rng.randint(0, 3))),
            full_files_included=("k.py",) if rng.random() < 0.5 else (),
            full_files_dropped=tuple(_text(rng, 300) for _ in range(rng.randint(0, 30))),
            verifier_state=REPORT_PARSED,
            verifier_unavailable=rng.random() < 0.2,
        ),
        "diff": diff_ctx(files=withheld, name_only=names),
        "verifier": verifier_ctx(*parsed, *broken),
        "model_id": _text(rng, 400) or MODEL,
        "rubric_version": _text(rng, 40) or "1",
        "limit": rng.choice([MIN_LIMIT, 20_000, MAX_COMMENT_CHARS]),
    }


def test_hostile_tactic_github_neutralization_size_and_marker():
    """Seed 414002: every hostile slot, every limit; plain checks always, markdown-it on 1 in 4."""
    tactic = Tactic.from_env(tactic_seed(414, 2), 300)
    rng = tactic.rng()
    stage_sets: set[tuple[int, ...]] = set()
    for i in range(tactic.iterations):
        fx = _hostile_case(rng)
        if not tactic.selected(i):
            continue
        out = _review(
            fx,
            model_id=fx["model_id"],
            rubric_version=fx["rubric_version"],
            limit=fx["limit"],
        )
        ctx = tactic.context(i, (len(fx["validation"].blocking), fx["limit"]))
        _plain_checks(out.body, fx["limit"], ctx)
        assert ANCHORED_MARKER.match(out.body).groups() == (RUN_ID, HEAD), ctx
        assert (TRUNCATION_NOTE in out.body) == out.truncated, ctx
        if out.truncated:
            # The note sits right before the footer, which is never cut.
            assert f"\n\n{TRUNCATION_NOTE}\n\n<sub>Not reviewed here: " in out.body, ctx
        stage_sets.add(out.stages)
        if i % 4 == 0 or tactic.replaying:
            _md_checks(out.body, ctx)
    if not tactic.replaying:
        assert {(), (5,)} & stage_sets and any(5 in s for s in stage_sets)
        assert any(1 in s for s in stage_sets) and any(4 in s for s in stage_sets)


@pytest.mark.parametrize(
    "text",
    [
        "＠llipe",
        "﹫llipe",
        "\U000e0041\U000e0042",
        "x⁠y﻿z",
        ":rocket:",
    ],
)
def test_accepted_cosmetic_inputs_are_not_markup(text):
    """Cosmetic only: GitHub has no mention for look-alike ``@`` signs and
    invisible characters carry no Markdown. They pass through unchanged, and
    the body keeps every structural guarantee."""
    out = _review({"validation": validation([finding("B1", title=text, consequence=text)])})
    _plain_checks(out.body, MAX_COMMENT_CHARS)
    _md_checks(out.body)


@pytest.mark.parametrize(
    "text",
    [
        "see #414",
        "llipe/dev-tasks-agent-fleet#414",
        "https://github.com/llipe/dev-tasks-agent-fleet/issues/414",
        "www.github.com/llipe/dev-tasks-agent-fleet/issues/414",
        "HtTpS://github.com/x",
        "felipe@example.com",
        "mailto:felipe@example.com",
        "@llipe/core",
        "llipe/dev-tasks-agent-fleet@86d8971",
        "&#64;llipe &commat;llipe &#x40;llipe",
        "$$\n\\begin{x}\n$$",
        "> [!WARNING]\n> boom",
        "```mermaid\ngraph TD\n```",
        "| a | b |\n|---|---|\n| c | d |",
        "[x]: http://evil.example\n[x]",
        "x[^1]\n\n[^1]: boom",
        "- [ ] task",
        "/review\n/review",
        "</details><details open><summary>x</summary>",
        "<!-- --> --!> -->",
    ],
)
def test_github_constructs_are_inert_in_every_plain_slot(text):
    """Each construct in title, scenario, consequence, verifier row and reason."""
    c = candidate(1, text)
    v = validation(
        [finding("B1", title=text, failure_scenario=text, consequence=text)],
        [finding("S2", title=text, consequence=text)],
        [status(c, STATUS_CONFIRMED, text)],
    )
    out = _review(
        {
            "validation": v,
            "context": context_data(verifier_state=REPORT_PARSED, spec_paths=(text,)),
            "verifier": verifier_ctx(report(REPORT, REPORT_PARSED, candidates=(c,))),
        }
    )
    _plain_checks(out.body, MAX_COMMENT_CHARS)
    _md_checks(out.body)


def test_neutralize_escapes_every_markdown_punctuation_with_an_odd_backslash_run():
    """Inline math, emphasis, code, links, tables and strikethrough need an
    unescaped delimiter; every one of them is preceded by an odd backslash run."""
    rng = random.Random(tactic_seed(414, 3))
    for _ in range(2_000):
        raw = "".join(rng.choice(ATOMS) for _ in range(rng.randint(1, 20)))
        out = neutralize(raw)
        for m in re.finditer(r"[`*_\[\]!|~$]", out):
            run = len(out[: m.start()]) - len(out[: m.start()].rstrip("\\"))
            assert run % 2 == 1, (raw, out)


def test_code_span_never_holds_a_backtick_lt_or_line_break():
    rng = random.Random(tactic_seed(414, 4))
    for _ in range(2_000):
        raw = "".join(rng.choice(ATOMS) for _ in range(rng.randint(1, 20)))
        span = code_span(raw, 200)
        inner = span[1:-1] if span.startswith("`") else span
        assert "`" not in inner and "<" not in inner and "\n" not in inner, raw
        assert not re.search(f"@(?!{ZW})", inner), raw
        assert not any(c in inner for c in BIDI), raw


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-212-D1: neutralize breaks '#<n>' but not GitHub's 'GH-<n>' issue reference, "
        "so model or repository text can still cross-reference issues and PRs of the repo "
        "(PR #437 decision 13). Expected: 'GH-<n>' gets a U+200B like '#'."
    ),
)
def test_gh_prefixed_issue_reference_is_broken_in_content():
    assert not re.search(r"(?<![A-Za-z0-9])GH-\d", neutralize("see GH-414 and (GH-437)"))
    out = _review({"validation": validation([finding("B1", title="Regression of GH-414")])})
    markdown_it = pytest.importorskip("markdown_it")
    tokens = markdown_it.MarkdownIt("commonmark").parse(out.body)
    text = "\n".join(t.content for tok in tokens for t in (tok.children or []) if t.type == "text")
    assert not re.search(r"(?<![A-Za-z0-9])GH-\d", text)


# ---------------------------------------------------------------------------
# 2. Size: at most 60,000 for every input
# ---------------------------------------------------------------------------


def test_neutralize_expands_any_character_at_most_fivefold():
    """The documented worst case: ``&`` → ``&amp;``. No character expands more."""
    worst = 0
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        c = chr(cp)
        worst = max(worst, len(neutralize("a" + c + "a")) - 2)
        assert len(render._code_text("a" + c + "a", None)) - 2 <= 6, hex(cp)  # escape_path \xNN
    assert worst == 5
    assert len(neutralize("://" * 1000)) == 4 * 1000  # the only multi-char rewrite: 3 → 4


def test_size_ampersand_worst_case_at_schema_maxima_with_everything_huge():
    """40 blocking and 40 suggestions at schema maxima, all ``&`` (5x), 2,000
    candidates, a 10k model ID, a 1k rubric version, a 10k panel URL, huge lines."""
    amp = "&"
    blocking = [
        finding(
            f"B{i}",
            file=amp * 400,
            line_start=10**300,
            line_end=10**301,
            title=amp * 200,
            failure_scenario=amp * 1500,
            consequence=amp * 500,
        )
        for i in range(1, 41)
    ]
    suggestions = [
        finding(f"S{i}", file=amp * 400, title=amp * 200, consequence=amp * 500)
        for i in range(41, 81)
    ]
    cands = [candidate(k, amp * 2000, report=amp * 1000) for k in range(1, 2001)]
    statuses = [status(c, STATUS_CONFIRMED, amp * 300) for c in cands]
    fx = {
        "validation": validation(blocking, suggestions, statuses),
        "context": context_data(
            verifier_state=REPORT_PARSED,
            full_files_dropped=tuple(amp * 400 for _ in range(1000)),
            spec_paths=(amp * 400,),
        ),
        "verifier": verifier_ctx(report(amp * 1000, REPORT_PARSED, candidates=cands)),
    }
    out = _review(fx, model_id=amp * 10_000, rubric_version=amp * 1000)
    assert out.chars <= MAX_COMMENT_CHARS
    assert out.stages == (1, 2, 3, 4, 5)
    lines = out.body.split("\n")
    assert lines[0] == MARKER_LINE
    assert lines[2] == f"## Code review: **blocking** · `{HEAD[:7]}`"
    assert f"\n\n{TRUNCATION_NOTE}\n\n<sub>Not reviewed here: " in out.body
    footer = lines[-2]
    assert footer.endswith(f"· [run]({RUN_URL})</sub>")
    assert len(footer) <= 1_700
    # Bad panel URL: still bounded, link replaced.
    fx["validation"] = validation(blocking, suggestions)
    bad = _review(fx, panel_base_url="https://" + "a" * 10_000)
    assert bad.chars <= MAX_COMMENT_CHARS and bad.body.endswith(f"· {NO_LINK}</sub>\n")


def test_size_100k_candidates_only_stage5_still_adds_the_note():
    """No suggestion, no blocking, rows under 300: stages 1–4 change nothing,
    so stage 5 cuts a body assembled without the note, and must add it."""
    cands = [candidate(k, "| DR | Critical | Unintended | x |") for k in range(1, 100_001)]
    statuses = [status(c, STATUS_CONFIRMED, "still there") for c in cands]
    fx = {
        "validation": validation((), (), statuses),
        "context": context_data(verifier_state=REPORT_PARSED),
        "verifier": verifier_ctx(report(REPORT, REPORT_PARSED, candidates=cands)),
    }
    out = _review(fx)
    assert out.stages == (5,)
    _plain_checks(out.body, MAX_COMMENT_CHARS)
    assert f"\n\n{TRUNCATION_NOTE}\n\n<sub>" in out.body
    assert out.body.split("\n")[2] == f"## Code review: **blocking** · `{HEAD[:7]}`"


def test_size_huge_context_lists_stay_bounded_without_truncation():
    """100k issues, notes, specs, dropped files, name-only and withheld files:
    the context line is bounded by ``LIST_MAX`` and ``CONTEXT_MAX_CHARS``."""
    n = 100_000
    hostile = "@&<`#1" * 100
    notes = [BlockNote("issue", f"#{k}", "omitted", "budget") for k in range(n, 2 * n)]
    notes += [BlockNote("spec", hostile + str(k), "omitted", "budget") for k in range(n)]
    notes += [BlockNote("verifier", hostile + str(k), "truncated", "budget") for k in range(n)]
    fx = {
        "validation": validation(),
        "context": context_data(
            notes=notes,
            issue_numbers=tuple(range(1, n + 1)),
            spec_paths=tuple(hostile + str(k) for k in range(n)),
            full_files_included=("k.py",),
            full_files_dropped=tuple(hostile + str(k) for k in range(n)),
        ),
        "diff": diff_ctx(
            files=[file_diff(hostile + str(k), base_withheld="lockfile") for k in range(n)],
            name_only=[NameOnlyFile(hostile, "added", "content_unavailable", hostile)] * n,
        ),
    }
    out = _review(fx)
    context_line = next(x for x in out.body.split("\n") if x.startswith("**Context:**"))
    assert out.stages == ()
    assert len(context_line) <= 20_000
    assert context_line.count(" more") >= 6  # every list says "and N more"
    assert not re.search(f"@(?!{ZW})", context_line) and "<" not in context_line


def test_size_huge_model_id_rubric_and_panel_url_keep_the_footer_bounded():
    for model in ("&" * 1_000_000, "@" * 1_000_000, "\x00" * 1_000_000, "`" * 1_000_000):
        out = _review(
            {"validation": validation()},
            model_id=model,
            rubric_version="&" * 1_000_000,
            panel_base_url="https://" + "a" * 1_000_000,
        )
        footer = out.body.split("\n")[-2]
        assert len(footer) <= 1_700, len(footer)
        assert footer.endswith(f"· {NO_LINK}</sub>")
        assert out.stages == ()


def test_budget_comment_long_lists_and_huge_counts_are_bounded():
    hostile = "\n/review @everyone <b>#1</b> `x` &#64; GH-1 ‮"
    names = [NameOnlyFile(hostile * 50, "added", "excluded", hostile * 50)] * 100_000
    over = OverBudget(lines=10**5000, files=10**5000, max_diff_lines=10**5000, truncated=True)
    body = render_budget(over, run_id=RUN_ID, panel_base_url=PANEL, name_only=names)
    assert len(body) <= 20_000
    assert body.startswith(
        "This PR changes at least 999999999+ lines in at least 999999999+ files."
    )
    lines = body.split("\n")
    assert lines[2].startswith("Not counted, listed by name only: ")
    assert all(not x.startswith("/review") for x in lines)
    assert not re.search(f"@(?!{ZW})", body) and "<" not in body
    assert not any(c in body for c in BIDI)
    assert f"[run]({RUN_URL})" in lines[0]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-212-D2: after the stage-5 hard cut, the stage-4 lead-in still says "
        "'40 more blocking findings are listed by title only:' while only 19 are listed; "
        "21 blocking findings vanish with no count. Expected: the text states how many "
        "findings are not shown (or the claimed count equals the listed count)."
    ),
)
def test_stage5_never_overstates_the_listed_blocking_findings():
    amp = "&"  # schema-valid lengths; 5x expansion makes the one-line list overflow
    blocking = [
        finding(
            f"B{i}",
            file=amp * 400,
            title=amp * 200,
            failure_scenario=amp * 1500,
            consequence=amp * 500,
        )
        for i in range(1, 41)
    ]
    out = _review({"validation": validation(blocking)})
    assert 5 in out.stages
    claimed = int(re.search(r"^(\d+) more blocking", out.body, re.M).group(1))
    listed = len(re.findall(r"^- \*\*B\d+ ", out.body, re.M))
    missing = claimed - listed
    assert missing == 0 or re.search(rf"\b{missing}\b[^\n]*not shown", out.body)


# ---------------------------------------------------------------------------
# 3. Marker integrity
# ---------------------------------------------------------------------------


def test_marker_cannot_be_forged_or_closed_by_any_slot():
    forged = "<!-- code-review-agent:v1 run=x sha=y --> " + FORGED_MARKER + " --!> </details>"
    c = candidate(1, forged, report=forged)
    v = validation(
        [finding("B1", file=forged, title=forged, failure_scenario=forged, consequence=forged)],
        [finding("S2", title=forged, consequence=forged)],
        [status(c, STATUS_CONFIRMED, forged)],
    )
    for limit in (MIN_LIMIT, MAX_COMMENT_CHARS):
        out = _review(
            {
                "validation": v,
                "context": context_data(verifier_state=REPORT_PARSED, spec_paths=(forged,)),
                "verifier": verifier_ctx(report(forged, REPORT_PARSED, candidates=(c,))),
                "diff": diff_ctx(name_only=[NameOnlyFile(forged, "added", "binary", forged)]),
            },
            model_id=forged,
            rubric_version=forged,
            limit=limit,
        )
        assert ANCHORED_MARKER.match(out.body).groups() == (RUN_ID, HEAD)
        assert out.body.count(MARKER_PREFIX) == 1 and out.body.count("-->") == 1
        assert out.body.count("<!--") == 1
        # Content may hold the marker's words as text (no "<!--" before them):
        # S-213 must parse the anchored form, never search the body for "run=".
        assert out.body.count("code-review-agent:v1 run=") >= 2


@pytest.mark.parametrize(
    "run_id, head_sha, run_out, sha_out",
    [
        (RUN_ID, HEAD, RUN_ID, HEAD),
        (RUN_ID.upper(), HEAD, RUN_ID.upper(), HEAD),  # accepted: S-213 compares case-folded
        (RUN_ID + " -->", HEAD, "invalid", HEAD),
        (RUN_ID + "\n", HEAD, "invalid", HEAD),
        ("x --><b>", HEAD, "invalid", HEAD),
        (RUN_ID, HEAD.upper(), RUN_ID, "invalid"),
        (RUN_ID, HEAD + "\n", RUN_ID, "invalid"),
        (RUN_ID, HEAD[:39], RUN_ID, "invalid"),
        (RUN_ID, HEAD + "a", RUN_ID, "invalid"),
        (RUN_ID, "a" * 64, RUN_ID, "a" * 64),
        (None, None, "invalid", "invalid"),
        (b"x", 12, "invalid", "invalid"),
    ],
)
def test_marker_fields_are_validated_and_parse_back(run_id, head_sha, run_out, sha_out):
    out = render_review(
        validation(),
        context=context_data(),
        diff=None,
        verifier=None,
        run_id=run_id,
        head_sha=head_sha,
        model_id=MODEL,
        rubric_version="1",
        panel_base_url=PANEL,
    )
    assert ANCHORED_MARKER.match(out.body).groups() == (run_out, sha_out)
    assert out.body.count("-->") == 1


def test_marker_and_header_survive_the_hard_cut_at_the_smallest_limit():
    blocking = [finding(f"B{i}", title="<" * 200, file="<" * 400) for i in range(1, 41)]
    out = _review({"validation": validation(blocking)}, limit=MIN_LIMIT)
    assert 5 in out.stages and out.chars <= MIN_LIMIT
    assert ANCHORED_MARKER.match(out.body).groups() == (RUN_ID, HEAD)
    assert out.body.split("\n")[2] == f"## Code review: **blocking** · `{HEAD[:7]}`"


# ---------------------------------------------------------------------------
# 4. Determinism and linearity on 1–5 MB inputs
# ---------------------------------------------------------------------------


def _big_case(size: int) -> dict:
    unit = "@<&#`*_|$://www. \n‮/review "
    s = (unit * (size // len(unit) + 1))[:size]
    c = candidate(1, s, report=s)
    return {
        "validation": validation(
            [finding("B1", file=s, title=s, failure_scenario=s, consequence=s)],
            [finding("S2", file=s, title=s, consequence=s)],
            [status(c, STATUS_CONFIRMED, s)],
        ),
        "context": context_data(
            verifier_state=REPORT_PARSED, spec_paths=(s,), full_files_dropped=(s,)
        ),
        "verifier": verifier_ctx(report(s, REPORT_PARSED, candidates=(c,))),
        "diff": diff_ctx(name_only=[NameOnlyFile(s, "added", "binary", s)]),
    }


def _timed(fx: dict, **kw) -> tuple[float, str]:
    start = time.perf_counter()
    body = _review(fx, **kw).body
    return time.perf_counter() - start, body


def test_render_1mb_and_5mb_inputs_is_deterministic_bounded_and_linear():
    small, large = _big_case(1_000_000), _big_case(5_000_000)
    t1a, b1a = _timed(small, model_id="m" * 1_000_000)
    t1b, b1b = _timed(small, model_id="m" * 1_000_000)
    t5a, b5a = _timed(large, model_id="m" * 5_000_000)
    t5b, b5b = _timed(large, model_id="m" * 5_000_000)
    assert b1a == b1b and b5a == b5b
    for body in (b1a, b5a):
        _plain_checks(body, MAX_COMMENT_CHARS)
    # Linear: 5x the input costs about 5x (measured 6.5-7x on this container,
    # allocation overhead). Quadratic would be 25x.
    ratio = min(t5a, t5b) / max(min(t1a, t1b), 1e-3)
    assert ratio < 15, (t1a, t1b, t5a, t5b)


def test_neutralize_and_code_span_are_linear_on_5mb():
    s = "&@#://www.`\\$‮\n" * 350_000  # about 5 MB
    start = time.perf_counter()
    out = neutralize(s)
    assert time.perf_counter() - start < 5
    assert len(out) <= 5 * len(s)
    start = time.perf_counter()
    assert len(code_span(s, 200)) <= 1_300
    assert time.perf_counter() - start < 1  # escape_path runs on limit + 1 chars only


# ---------------------------------------------------------------------------
# 5. Budget and failure messages, hostile run links
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", render.ERROR_CODES)
def test_failure_every_section13_code_is_one_fixed_line(code):
    body = render_failure(code, run_id=RUN_ID, panel_base_url=PANEL)
    assert body == f"Code review failed (`{code}`). [run]({RUN_URL})\n"


@pytest.mark.parametrize(
    "code",
    [
        "",
        "internal_error",
        "RUN_TIMEOUT ",
        " RUN_TIMEOUT",
        "RUN_TIMEOUT\n",
        "RUN_TIMEOUT`). @everyone <b>x</b> (`",
        "GITHUB_NOT_FOUND",
        "‮RUN_TIMEOUT",
        "RUN_TIMEOUT​",
        "ＲＵＮ_TIMEOUT",
        b"RUN_TIMEOUT",
        42,
        None,
        ["RUN_TIMEOUT"],
        ValueError("RUN_TIMEOUT"),
    ],
)
def test_failure_unknown_codes_render_internal_error(code):
    body = render_failure(code, run_id=RUN_ID, panel_base_url=PANEL)
    assert body == f"Code review failed (`INTERNAL_ERROR`). [run]({RUN_URL})\n"


# Deliberately the (str, Enum) mixin, not StrEnum: StrEnum formats as its
# value and would hide the defect; the mixin formats as "_EnumCode.RUN_TIMEOUT".
class _EnumCode(str, enum.Enum):  # noqa: UP042
    RUN_TIMEOUT = "RUN_TIMEOUT"


class _FormattingCode(str):
    def __format__(self, spec: str) -> str:
        return "@everyone <img src=x onerror=1>"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-212-D3: render_failure checks 'error_code in ERROR_CODES' but interpolates the "
        "caller's object, not the matched constant. A (str, Enum) member renders "
        "'_EnumCode.RUN_TIMEOUT'; a str subclass's __format__ can inject any text. "
        "Expected: the canonical §13 string is always what is rendered."
    ),
)
@pytest.mark.parametrize("code", [_EnumCode.RUN_TIMEOUT, _FormattingCode("RUN_TIMEOUT")])
def test_failure_renders_the_canonical_code_for_str_subclasses(code):
    body = render_failure(code, run_id=RUN_ID, panel_base_url=PANEL)
    assert body == f"Code review failed (`RUN_TIMEOUT`). [run]({RUN_URL})\n"


HOSTILE_PANEL_URLS = [
    "javascript:alert(1)",
    "JAVASCRIPT:alert(1)",
    "javascript://x.example/%0aalert(1)",
    "data:text/html;base64,PHNjcmlwdD4=",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
    "http://evil/@",
    "http://evil/@everyone",
    "https://user:pass@x.example",
    "https://x.example@evil.example",
    "https://user@x.example:8443",
    "http://[::1]",
    "http://[::1]:8080/panel",
    "http://[2001:db8::1]/",
    "https://exämple.com",
    "https://例え.jp",
    "https://xn--e1afmkfd.xn--p1ai/ü",
    "ｈttps://x.example",
    "https://x．example",
    "https://x.example?x=1",
    "https://x.example/?q=@a",
    "https://x.example#frag",
    "https://x.example/p#@x",
    "https://x.example/a%20b",
    "https://x.example/%2e%2e",
    "https://x.example/)",
    "https://x.example/](javascript:x)",
    'https://x.example/"onmouseover="x',
    "https://x.example/<!--",
    "https://x.example/`x`",
    "https://x.example/a\\b",
    "//x.example",
    "https:x.example",
    "https:/x.example",
    " https://x.example",
    "https://x.example\n",
    "https://x.example\t",
    "https://x.example/​",
    "https://x.example/‮",
    "https://-x.example",
    "https://x.example.",
    "https://x.example:",
    "https://x.example:123456",
    "https://x.example/" + "a" * 300,
    "",
    None,
]


@pytest.mark.parametrize("base", HOSTILE_PANEL_URLS)
def test_hostile_panel_base_url_gives_no_link_in_all_three_comments(base):
    failure = render_failure("RUN_TIMEOUT", run_id=RUN_ID, panel_base_url=base)
    assert failure == f"Code review failed (`RUN_TIMEOUT`). {NO_LINK}\n"
    over = OverBudget(lines=10, files=1, max_diff_lines=5)
    assert render_budget(over, run_id=RUN_ID, panel_base_url=base).endswith(f" {NO_LINK}\n")
    review = _review({"validation": validation()}, panel_base_url=base).body
    assert review.endswith(f"· {NO_LINK}</sub>\n") and "](" not in review


@pytest.mark.parametrize(
    "run_id",
    [
        "x",
        RUN_ID + "\n",
        " " + RUN_ID,
        "{" + RUN_ID + "}",
        "urn:uuid:" + RUN_ID,
        RUN_ID.replace("-", ""),
        "../" + RUN_ID,
        RUN_ID + "/../../admin",
        RUN_ID + ")",
        "０b7c4e9a-1d2f-4a3b-8c5d-6e7f8091a2b3",  # fullwidth digit
    ],
)
def test_hostile_run_id_gives_no_link_and_an_invalid_marker(run_id):
    assert run_link(PANEL, run_id) is None
    out = _review({"validation": validation()}, run_id=run_id)
    assert out.body.startswith(f"{MARKER_PREFIX}run=invalid sha={HEAD} -->\n")
    assert out.body.endswith(f"· {NO_LINK}</sub>\n")


@pytest.mark.parametrize(
    "base, expected",
    [
        (PANEL, PANEL),
        ("http://localhost:3000/", "http://localhost:3000"),
        ("https://x.example/panel/v1//", "https://x.example/panel/v1"),
        # Accepted, operator-set: dot segments and a port above 65535 pass the
        # shape check. Neither can inject Markdown; both are cosmetic.
        ("https://x.example/../..", "https://x.example/../.."),
        ("http://x.example:99999", "http://x.example:99999"),
    ],
)
def test_accepted_panel_urls_build_an_inert_link(base, expected):
    url = run_link(base, RUN_ID)
    assert url == f"{expected}/runs/{RUN_ID}"
    assert re.fullmatch(r"https?://[A-Za-z0-9.-]+(?::\d{1,5})?(?:/[A-Za-z0-9._~-]+)*", url)
    body = render_failure("BEDROCK_ERROR", run_id=RUN_ID, panel_base_url=base)
    assert body == f"Code review failed (`BEDROCK_ERROR`). [run]({url})\n"


def test_budget_and_failure_bodies_never_start_or_break_a_line_with_review():
    hostile = "\n/review\r\n/review /review"
    names = [NameOnlyFile(hostile, "added", "content_unavailable", hostile)]
    for over in (
        OverBudget(lines=10, files=1, max_diff_lines=5),
        OverBudget(lines=1, files=1, max_diff_lines=5, reason="tokens"),
        OverBudget(
            lines=1,
            files=1,
            max_diff_lines=5,
            reason="tokens",
            tokens=9,
            diff_tokens=8,
            max_context_tokens=7,
        ),
    ):
        body = render_budget(over, run_id=RUN_ID, panel_base_url=PANEL, name_only=names)
        assert body.startswith("This PR changes ")
        assert all(not line.startswith("/review") for line in body.split("\n"))
    for code in (*render.ERROR_CODES, hostile):
        body = render_failure(code, run_id=RUN_ID, panel_base_url=PANEL)
        assert body.startswith(FAILURE_PREFIX) and body.count("\n") == 1
