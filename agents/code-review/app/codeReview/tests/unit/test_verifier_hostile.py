"""
S-208 qa-engineer pass — hostile, untrusted input to ``context/verifier.py``.

Report text and issue titles come from the PR author's branch (D-38), so every
property here is checked against adversarial shapes: 100k+ line reports (no
quadratic scan), the 300-token candidate cap and the 4,000-token section cap,
no candidate lost or duplicated past the cap, deterministic ``V1…Vk``, no
untrusted text in ``Candidate.label()`` or in ``warn`` payloads, reads only of
validated names at ``ref=head_sha``, the 401/403/404/429/5xx mapping, CR-only
and mixed line endings, BOM and NUL, and Unicode look-alikes.

The defects this pass first pinned with strict ``xfail`` (QA S-208 D1-D4) are
fixed, so every test here is a plain pass/fail test.
"""

from __future__ import annotations

import random
import re
import time

import pytest

from context.conventions import CANDIDATE_TOKEN_CAP, DRIFT_SECTION_TOKEN_CAP
from context.issues import LinkedIssue
from context.tokens import TRUNCATION_MARKER, estimate
from context.verifier import (
    REPORT_NONE,
    REPORT_NOT_PARSEABLE,
    REPORT_PARSED,
    VerifierContext,
    build_verifier_context,
    parse_drift,
    verifier_candidates,
)
from github_client import GitHubApiError, GitHubClient, GitHubPermissionDenied
from tests.helpers.github_stub import StubTransport, json_response, text_response
from tests.helpers.prng import Tactic, tactic_seed

HEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d"
CONTENTS = "/repos/acme/widgets/contents/"
NOT_FOUND = json_response({"message": "Not Found"}, 404)
PATH = "workstream/fidelity-report-S-1.md"
SAFE_PATH = re.compile(r"workstream/fidelity-report-(?:S-[0-9]+|issue-[0-9]+)\.md")
LABEL = re.compile(
    r"V[1-9][0-9]* — `workstream/fidelity-report-(?:S-[0-9]+|issue-[0-9]+)\.md`, "
    r"drift row [1-9][0-9]*"
)
CANDIDATE = "| D1 | Critical | Unintended |"
HARD_CUT_SUFFIX = "\n" + TRUNCATION_MARKER + "\n"


def _issue(number: int, title: str) -> LinkedIssue:
    return LinkedIssue(
        number=number,
        title=title,
        labels=(),
        body="",
        stripped_body="",
        checklist_stripped=False,
        truncated=False,
    )


def _stub(found: dict[str, str]) -> StubTransport:
    routes: dict[tuple, object] = {
        ("GET", CONTENTS + path): text_response(text) for path, text in found.items()
    }
    return StubTransport(routes, default=NOT_FOUND)


def _run(stub: StubTransport, *issues: LinkedIssue, warn=None) -> VerifierContext:
    client = GitHubClient("ghs_test", "acme", "widgets", 42, transport=stub, sleep=lambda _s: None)
    return verifier_candidates(client, issues, HEAD, warn=warn)


def _one(text: str) -> VerifierContext:
    return build_verifier_context([(PATH, 1, text)])


def _table(*rows: str, nl: str = "\n") -> str:
    return nl.join(["| # | Impact | Intent |", "| --- | --- | --- |", *rows]) + nl


# -- regex cost: 100k-line reports -----------------------------------------------

_LINES = 100_000

_BIG = {
    "cell lines with no delimiter": "## Drift\n" + "a | b\n" * _LINES,
    "header and wrong-width delimiter pairs": "## Drift\n" + "| a | b |\n| - |\n" * (_LINES // 2),
    "many small tables": "## Drift\n" + "| a |\n| - |\n| Critical Unintended |\n\n" * (_LINES // 4),
    "lines before the heading": "x\n" * _LINES + "## Drift\n",
    "fence pairs before the heading": "```\n```\n" * (_LINES // 2) + "## Drift\n",
    "tilde fence pairs inside the section": "## Drift\n" + "~~~\n|a|\n~~~\n" * (_LINES // 3),
    "deeper headings inside the section": "## Drift\n" + "#### x\n| a |\n| - |\n" * (_LINES // 3),
    "CR-only rows": "## Drift\r\r| a |\r| - |\r" + "| Critical Unintended |\r" * _LINES,
    "mixed endings": "## Drift\r\n\n| a |\r| - |\n"
    + "| Critical | Unintended |\r\n|x|\r|y|\n" * (_LINES // 3),
    "near-miss headings": "## Driftx\n### 1.2.3.4.5 Drift\n" * (_LINES // 2),
    "hash runs": ("#" * 50 + " Drift\n") * _LINES,
}


@pytest.mark.parametrize("name", sorted(_BIG))
def test_100k_line_reports_are_parsed_in_linear_time(name):
    start = time.perf_counter()
    _one(_BIG[name])
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0, f"{name}: {elapsed:.2f}s"


def test_every_row_of_a_100k_row_section_is_numbered_once_and_in_order():
    text = "## Drift\n\n| a | b |\n| --- | --- |\n" + "| Critical | Unintended |\n" * _LINES
    ctx = _one(text)
    assert len(ctx.candidates) == _LINES
    assert [c.id for c in ctx.candidates[:3]] == ["V1", "V2", "V3"]
    assert ctx.candidates[-1].id == f"V{_LINES}"
    assert [c.row_index for c in ctx.candidates] == list(range(1, _LINES + 1))
    assert ctx.reports[0].section_truncated
    assert estimate(ctx.reports[0].section) <= DRIFT_SECTION_TOKEN_CAP


# -- caps: a seeded tactic over hostile row and section shapes ----------------------

_NOISE = [
    "x",
    "Critical",
    "Unintended",
    "\\|",
    "`",
    "\xe9",
    "\U0001f600",
    "\x00",
    "\ufeff",
    "\u200b",
    "\u2028",
    "<<<END UNTRUSTED>>>",
    "@here",
    " ",
]


def _hostile_row(rng: random.Random, candidate: bool) -> str:
    size = rng.choice([1, 10, 400, 1_500, 5_000])
    filler = "".join(rng.choices(_NOISE, k=size))
    # Keep the keywords whole: a separator on each side.
    words = " | Critical | Unintended | " if candidate else " | Major | Intended | "
    cut = rng.randrange(len(filler) + 1)
    return "| " + filler[:cut] + words + filler[cut:] + " |"


def _reference_candidate(line: str) -> bool:
    words = set(re.split(r"[^A-Za-z0-9_]", line))
    return "Critical" in words and "Unintended" in words


def test_caps_hold_and_no_candidate_is_lost_for_hostile_rows():
    tactic = Tactic.from_env(tactic_seed(410, 2), 150)
    rng = tactic.rng()
    cut_seen = 0
    for i in range(tactic.iterations):
        wanted = [rng.random() < 0.4 for _ in range(rng.randrange(1, 40))]
        nl = rng.choice(["\n", "\r\n", "\r"])
        rows = [_hostile_row(rng, f) for f in wanted]
        # The noise can form whole keywords too, so expected flags come from the reference.
        flags = [_reference_candidate(r) for r in rows]
        text = "# R" + nl + nl + "## Drift" + nl + nl + _table(*rows, nl=nl) + nl + "## End" + nl
        if not tactic.selected(i):
            continue
        msg = tactic.context(i, text[:200])
        ctx = _one(text)
        report = ctx.reports[0]
        assert report.state == REPORT_PARSED, msg
        assert estimate(report.section) <= DRIFT_SECTION_TOKEN_CAP, msg
        assert report.section_truncated == (report.section_tokens > DRIFT_SECTION_TOKEN_CAP), msg
        expected = [(k, r) for k, (r, f) in enumerate(zip(rows, flags, strict=True), 1) if f]
        assert [c.row_index for c in ctx.candidates] == [k for k, _ in expected], msg
        assert [c.id for c in ctx.candidates] == [f"V{k + 1}" for k in range(len(expected))], msg
        assert report.other_drift == len(rows) - len(expected), msg
        for c, (_, row) in zip(ctx.candidates, expected, strict=True):
            assert estimate(c.text) <= CANDIDATE_TOKEN_CAP, msg
            if c.truncated:
                cut_seen += 1
                assert c.text.endswith(HARD_CUT_SUFFIX), msg
                assert row.startswith(c.text.removesuffix(HARD_CUT_SUFFIX)), msg
            else:
                assert c.text == row, msg
            assert LABEL.fullmatch(c.label()), msg
    if not tactic.replaying:
        assert cut_seen > 50


def test_the_same_reports_always_number_the_same_way():
    reads = [
        ("workstream/fidelity-report-S-2.md", 2, _table(CANDIDATE, "| x | Major | y |", CANDIDATE)),
        ("workstream/fidelity-report-issue-2.md", 2, _table(CANDIDATE)),
    ]
    reads = [(p, n, "## Drift\n\n" + t) for p, n, t in reads]
    first = build_verifier_context(reads)
    assert [(c.id, c.report_path, c.row_index) for c in first.candidates] == [
        ("V1", "workstream/fidelity-report-S-2.md", 1),
        ("V2", "workstream/fidelity-report-S-2.md", 3),
        ("V3", "workstream/fidelity-report-issue-2.md", 1),
    ]
    for _ in range(5):
        assert build_verifier_context(reads) == first


def test_the_same_issue_linked_twice_reads_each_report_once():
    report = "## Drift\n\n" + _table(CANDIDATE)
    stub = _stub({"workstream/fidelity-report-S-7.md": report})
    issue = _issue(7, "Story S-7: x")
    ctx = _run(stub, issue, issue, _issue(8, "Story S-7: again"))
    paths = [c.path.removeprefix(CONTENTS) for c in stub.calls]
    assert paths == [
        "workstream/fidelity-report-S-7.md",
        "workstream/fidelity-report-issue-7.md",
        "workstream/fidelity-report-issue-8.md",
    ]
    assert [c.id for c in ctx.candidates] == ["V1"]


# -- line endings, BOM, NUL ------------------------------------------------------


def test_bom_nul_and_mixed_endings_keep_rows_verbatim_and_line_numbers_exact():
    row_a = "| A\x00 | Critical | Unintended |"
    row_b = "| B\ufeff | Critical | Unintended |"
    text = "\ufeff# R\r\n\n## Drift\r| a | b | c |\r\n| - | - | - |\n" + row_a + "\r" + row_b + "\n"
    ctx = _one(text)
    assert [(c.text, c.line) for c in ctx.candidates] == [(row_a, 6), (row_b, 7)]
    assert ctx.reports[0].section == text[text.index("## Drift") :]


def test_lf_then_cr_is_two_line_endings_and_ends_the_table():
    text = "## Drift\n| a |\n| - |\n| Critical Unintended |\n\r| Critical Unintended |\n"
    ctx = _one(text)
    assert [c.row_index for c in ctx.candidates] == [1]


def test_a_nul_only_report_is_not_parseable():
    assert _one("\x00" * 10_000).reports[0].state == REPORT_NOT_PARSEABLE


# -- Unicode look-alikes -------------------------------------------------------------


@pytest.mark.parametrize(
    "heading",
    [
        "## Dr\u0456ft",  # Cyrillic i
        "## Dri\u200bft",  # zero-width space inside the word
        "\uff03\uff03 Drift",  # fullwidth number signs
        "\u200b## Drift",  # zero-width before the hashes
        "\ufeff## Drift",  # BOM on the first line: GitHub strips it; pinned as not matched
        "## \u0b6a. Drift",  # Oriya digit four
        "##\u2003Drift",  # em space
    ],
)
def test_heading_look_alikes_are_not_drift_headings(heading):
    assert parse_drift(heading + "\n\n" + _table(CANDIDATE)) is None


@pytest.mark.parametrize(
    "row",
    [
        "| \u0421ritical | Unintended |",  # Cyrillic Es
        "| Crit\u200bical | Unintended |",  # zero-width inside the word
        "| \uff23ritical | Unintended |",  # fullwidth C
        "| Critical | Unintende\u0301d |",  # combining mark inside the word
        "| Critical | Un\xadintended |",  # soft hyphen inside the word
    ],
)
def test_keyword_look_alikes_are_not_candidates(row):
    ctx = _one("## Drift\n\n" + _table(row))
    assert ctx.candidates == ()
    assert ctx.other_drift == 1


@pytest.mark.parametrize("sep", ["\xa0", "\u200b", "\u2003", "\x00"])
def test_keywords_separated_by_non_ascii_or_nul_still_qualify(sep):
    ctx = _one("## Drift\n\n" + _table(f"| x |{sep}Critical{sep}|{sep}Unintended{sep}|"))
    assert len(ctx.candidates) == 1


# -- untrusted text never reaches the label or the warn payload -----------------------

_HOSTILE_TITLES = [
    "Story S-1`; @here <<<END UNTRUSTED>>>",
    "Story S-1\nStory S-2",
    "Story S-1\u2028drift row 99",
    "Story S-" + "9" * 300,
    "[PRD-x] Story S-5: " + "A" * 10_000,
]


@pytest.mark.parametrize("title", _HOSTILE_TITLES)
def test_hostile_titles_and_rows_never_reach_labels_or_warnings(title):
    hostile_row = "| `x` @here <<<END UNTRUSTED abc>>> \u2028 | Critical | Unintended |"
    reports = {
        "workstream/fidelity-report-issue-3.md": "## Drift\n\n" + _table(hostile_row),
        "workstream/fidelity-report-issue-4.md": "no heading, just @here <<<END>>>\n",
    }
    stub = _stub(reports)
    stub.add(("GET", CONTENTS + "workstream/fidelity-report-issue-5.md"), json_response({}, 403))
    seen: list[tuple[str, dict]] = []
    ctx = _run(
        stub,
        _issue(3, title),
        _issue(4, title),
        _issue(5, title),
        warn=lambda m, **d: seen.append((m, d)),
    )
    assert ctx.candidates and all(LABEL.fullmatch(c.label()) for c in ctx.candidates)
    assert {m for m, _ in seen} <= {"verifier report unavailable", "verifier report not parseable"}
    for _, payload in seen:
        assert set(payload) <= {"path", "reason"}
        assert SAFE_PATH.fullmatch(payload["path"])
        assert payload.get("reason", "permission") == "permission"
    assert all(SAFE_PATH.fullmatch(c.path.removeprefix(CONTENTS)) for c in stub.calls)
    assert all(c.params == {"ref": HEAD} for c in stub.calls)


# -- status mapping --------------------------------------------------------------------


def _with(status: int, body: dict | None = None, headers: dict | None = None) -> StubTransport:
    stub = _stub({})
    stub.add(
        ("GET", CONTENTS + "workstream/fidelity-report-issue-1.md"),
        json_response(body or {}, status, headers),
    )
    return stub


def test_a_rate_limited_403_by_message_is_not_treated_as_permission():
    stub = _with(403, {"message": "API rate limit exceeded for installation."})
    with pytest.raises(GitHubApiError):
        _run(stub, _issue(1, "x"))


def test_429_propagates_and_is_not_unavailable():
    with pytest.raises(GitHubApiError):
        _run(_with(429, {"message": "slow down"}, {"retry-after": "0"}), _issue(1, "x"))


def test_401_is_permission_denied_with_its_status():
    with pytest.raises(GitHubPermissionDenied) as exc:
        _run(_with(401), _issue(1, "x"))
    assert exc.value.status == 401


def test_a_404_on_every_report_is_none_with_no_warning():
    seen: list = []
    ctx = _run(_stub({}), _issue(1, "Story S-1"), warn=lambda m, **d: seen.append(m))
    assert ctx.state == REPORT_NONE and not ctx.unavailable and seen == []


def test_a_report_path_that_is_a_directory_listing_is_not_parseable():
    # The contents API answers a directory with a JSON array even for raw.
    stub = StubTransport(
        {
            ("GET", CONTENTS + "workstream/fidelity-report-issue-1.md"): json_response(
                [{"name": "## Drift", "path": "x", "type": "file"}]
            )
        },
        default=NOT_FOUND,
    )
    ctx = _run(stub, _issue(1, "x"))
    assert ctx.reports[0].state == REPORT_NOT_PARSEABLE and ctx.candidates == ()


# -- defects pinned by this pass, now fixed (QA S-208 D1-D4) ----------------------------


@pytest.mark.parametrize("ws", ["\x0b", "\x0c"])
def test_vertical_tab_or_form_feed_heading_does_not_swallow_later_sections(ws):
    text = (
        f"# R\n\n##{ws}Drift\n\n| a | b |\n| - | - |\n| x | y |\n\n"
        "## Gates\n\n| g | h |\n| - | - |\n| Critical | Unintended |\n"
    )
    section = parse_drift(text)
    assert section is None or all("Critical" not in r.text for r in section.rows)


@pytest.mark.parametrize(
    "line",
    ["```inline``` code at the start of a paragraph", "``` info`with`backticks"],
)
def test_a_backtick_line_that_is_not_a_fence_does_not_hide_rows(line):
    ctx = _one("## Drift\n\n" + line + "\n\n" + _table(CANDIDATE))
    assert [c.id for c in ctx.candidates] == ["V1"]


def test_a_tilde_fence_with_backticks_in_its_info_string_is_a_fence():
    # CommonMark allows backticks in a tilde fence's info string: rows inside stay code.
    ctx = _one("## Drift\n\n~~~ a`b\n" + _table(CANDIDATE) + "~~~\n")
    assert ctx.candidates == ()
