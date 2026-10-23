"""
S-212: review, budget and failure comments (spec §8.8, §13; D-28, D-29, D-36, D-38).

Test plan TC-212-01…18. Story AC mapping: AC-1 ``test_layout_*``, AC-2
``test_verifier_*``, AC-3 ``test_context_line_*``, AC-4 ``test_neutralize_*``,
AC-5 ``test_truncate_*``, AC-6 ``test_budget_msg*`` and ``test_failure_msg*``.

Snapshots are plain fixture files under ``__snapshots__/``, compared byte for
byte (the package has no snapshot helper). They were written by hand from the
spec §8.8 template before ``render.py`` existed. To regenerate after an
intended layout change, run with ``UPDATE_SNAPSHOTS=1`` and review the diff.
"""

from __future__ import annotations

import ast
import os
import re
import time
from pathlib import Path

import pytest

import render
from budget import BlockNote
from context.diff import NameOnlyFile, OverBudget
from render import (
    MAX_COMMENT_CHARS,
    TRUNCATION_NOTE,
    neutralize,
    render_budget,
    render_failure,
    render_review,
)
from tests.helpers.render_inputs import (
    HEAD,
    MODEL,
    PANEL,
    REPORT,
    REPORT_NONE,
    REPORT_NOT_PARSEABLE,
    REPORT_PARSED,
    RUN_ID,
    RUN_URL,
    SPEC,
    blocking_fixture,
    candidate,
    clear_fixture,
    context_data,
    diff_ctx,
    file_diff,
    finding,
    report,
    status,
    validation,
    verifier_ctx,
    with_context,
)
from validate import (
    STATUS_CONFIRMED,
    STATUS_DROPPED_FOR_BUDGET,
    STATUS_NOT_CHECKED,
    STATUS_NOT_REPRODUCED,
)

SNAPSHOTS = Path(__file__).parent / "__snapshots__"
ZW = "​"
NOTE = "Truncated; the full review is in the run's audit report."
WRAPPER_TAGS = ("<details><summary>", "</summary>", "</details>", "<sub>", "</sub>")


def review(fixture: dict, **overrides) -> render.Rendered:
    kwargs = {
        "context": fixture["context"],
        "diff": fixture["diff"],
        "verifier": fixture["verifier"],
        "run_id": RUN_ID,
        "head_sha": HEAD,
        "model_id": MODEL,
        "rubric_version": "1",
        "panel_base_url": PANEL,
    }
    kwargs.update(overrides)
    return render_review(fixture["validation"], **kwargs)


def body_of(fixture: dict, **overrides) -> str:
    return review(fixture, **overrides).body


def snapshot(name: str, body: str) -> None:
    path = SNAPSHOTS / name
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        path.write_bytes(body.encode("utf-8"))
    assert body.encode("utf-8") == path.read_bytes(), f"snapshot {name} differs"


def content_lt(body: str) -> int:
    """``<`` characters that are not the wrapper's own tags or the marker."""
    rest = body.split("\n", 1)[1] if body.startswith("<!--") else body
    for tag in WRAPPER_TAGS:
        rest = rest.replace(tag, "")
    return rest.count("<")


def unescaped_mentions(body: str) -> list[str]:
    return re.findall(r"@(?!​)\S", body)


def context_line(body: str) -> str:
    lines = [ln for ln in body.split("\n") if ln.startswith("**Context:** ")]
    assert len(lines) == 1, body
    return lines[0]


# ---------------------------------------------------------------------------
# AC-1: layout (TC-212-01…05, TC-212-18)
# ---------------------------------------------------------------------------


def test_layout_blocking_snapshot():
    """TC-212-01: the full spec §8.8 layout, byte for byte."""
    out = review(blocking_fixture())
    snapshot("review_blocking.md", out.body)
    assert not out.truncated
    assert out.stages == ()
    assert out.chars == len(out.body)


def test_layout_clear_snapshot_omits_empty_sections():
    """TC-212-02: header reads clear; Blocking and Suggestions are omitted."""
    body = body_of(clear_fixture())
    snapshot("review_clear.md", body)
    assert "### Blocking" not in body
    assert "<details>" not in body


def test_layout_first_lines_are_marker_then_verdict_header():
    lines = body_of(blocking_fixture()).split("\n")
    assert lines[0] == f"<!-- code-review-agent:v1 run={RUN_ID} sha={HEAD} -->"
    assert lines[1] == ""
    assert lines[2] == f"## Code review: **blocking** · `{HEAD[:7]}`"


def test_layout_section_order_is_spec_order():
    """TC-212-03 / DF-01: pinned to spec §8.8 (Verifier before Suggestions)."""
    body = body_of(blocking_fixture())
    marks = ["## Code review", "### Blocking", "### Verifier", "<details>", "**Context:**", "<sub>"]
    positions = [body.index(m) for m in marks]
    assert positions == sorted(positions)


def test_layout_footer_matches_rubric_out_of_scope_items():
    """TC-212-04: the footer names the rubric's three out-of-scope items (FR-21)."""
    rubric = (Path(render.__file__).parent / "rubric.md").read_text(encoding="utf-8")
    section = rubric.split("## Out of scope", 1)[1].split("##", 1)[0]
    items = [ln for ln in section.splitlines() if ln.startswith("- ")]
    assert len(items) == len(render.OUT_OF_SCOPE) == 3
    pairs = zip(items, render.OUT_OF_SCOPE, strict=True)
    owners = [("verifier",), ("CI",), ("CI", "security-analyst")]
    for (item, rendered), who in zip(pairs, owners, strict=True):
        for owner in who:
            assert owner in item and owner in rendered
    footer = body_of(blocking_fixture()).rstrip("\n").split("\n")[-1]
    assert footer.startswith("<sub>Not reviewed here: ") and footer.endswith("</sub>")
    for rendered in render.OUT_OF_SCOPE:
        assert rendered in footer
    assert f"Model `{MODEL}`" in footer
    assert "rubric v1" in footer
    assert f"[run]({RUN_URL})" in footer


def test_layout_rubric_version_comes_from_the_argument():
    body = body_of(clear_fixture(), rubric_version="7")
    assert "rubric v7" in body


def test_layout_single_line_location_and_suggestion_shape():
    """TC-212-05: ``file:120`` not ``file:120-120``; suggestion one-line shape."""
    fx = clear_fixture()
    fx["validation"] = validation(
        [finding("B1", line_start=120, line_end=120, title="t")],
        [finding("S1", category="intent", line_start=3, title="Title", consequence="Cons.")],
    )
    body = body_of(fx)
    assert "`src/app.py:120`**" in body
    assert "120-120" not in body
    assert "**S1 · intent · `src/app.py:3`** — Title. Cons." in body


def test_layout_title_ending_in_punctuation_gets_no_second_period():
    fx = clear_fixture()
    fx["validation"] = validation([], [finding("S1", title="Why?", consequence="Because.")])
    assert "— Why? Because." in body_of(fx)


def test_layout_downgrade_wording():
    """D-50: ``outside_diff`` reads "not located in the diff"."""
    fx = clear_fixture()
    fx["validation"] = validation(
        [],
        [
            finding("S1", downgraded="outside_diff"),
            finding("S2", downgraded="no_scenario"),
        ],
    )
    body = body_of(fx)
    assert "(Downgraded: not located in the diff.)" in body
    assert "(Downgraded: no failure scenario.)" in body
    assert "outside_diff" not in body


def test_layout_suggestions_only_is_clear_with_details():
    fx = clear_fixture()
    fx["validation"] = validation([], [finding("S1")])
    body = body_of(fx)
    assert "**clear**" in body
    assert "<details><summary>Suggestions (1)</summary>" in body
    assert "### Blocking" not in body


def test_layout_verdict_comes_from_validation():
    fx = clear_fixture()
    fx["validation"] = validation(verdict="blocking")
    assert "## Code review: **blocking**" in body_of(fx)


def test_layout_unknown_verdict_raises():
    fx = clear_fixture()
    fx["validation"] = validation(verdict="approved")
    with pytest.raises(ValueError):
        body_of(fx)


@pytest.mark.parametrize(
    "run_id, head_sha, marker",
    [
        ("not-a-uuid --> <b>", HEAD, f"run=invalid sha={HEAD}"),
        (RUN_ID, "zzz --> x", f"run={RUN_ID} sha=invalid"),
        (RUN_ID, "ABCDEF" + HEAD[6:], f"run={RUN_ID} sha=invalid"),
    ],
)
def test_layout_marker_fields_are_validated(run_id, head_sha, marker):
    body = body_of(clear_fixture(), run_id=run_id, head_sha=head_sha)
    assert body.split("\n")[0] == f"<!-- code-review-agent:v1 {marker} -->"
    assert body.count("<!--") == 1 and body.count("-->") == 1


def test_layout_sha256_head_is_accepted():
    sha = "a" * 64
    body = body_of(clear_fixture(), head_sha=sha)
    assert f"sha={sha} -->" in body
    assert "· `aaaaaaa`" in body


def test_layout_bodies_never_start_with_review_command():
    """TC-212-18: the agent's own comment can never match ``/review``."""
    fx = blocking_fixture()
    fx["validation"] = validation([finding("B1", title="/review now")])
    assert body_of(fx).startswith("<!-- code-review-agent:v1 ")
    assert render_failure("INTERNAL_ERROR", run_id=RUN_ID, panel_base_url=PANEL).startswith(
        "Code review failed"
    )
    over = OverBudget(lines=10, files=1, max_diff_lines=5)
    assert render_budget(over, run_id=RUN_ID, panel_base_url=PANEL).startswith("This PR changes")


# ---------------------------------------------------------------------------
# AC-2: Verifier section (TC-212-06, TC-212-07; D-38)
# ---------------------------------------------------------------------------


def _verifier_only(statuses, reports, *, unavailable=False, state=REPORT_PARSED):
    fx = clear_fixture()
    fx["validation"] = validation([], [], statuses)
    fx["verifier"] = verifier_ctx(*reports, unavailable=unavailable)
    fx["context"] = context_data(verifier_state=state, verifier_unavailable=unavailable)
    return body_of(fx)


def test_verifier_states_render_with_status_and_reason():
    """TC-212-06: confirmed, not reproduced, not checked, dropped for budget."""
    cands = [candidate(k, f"| row {k} | Critical | Unintended |") for k in range(1, 5)]
    body = _verifier_only(
        [
            status(cands[0], STATUS_CONFIRMED, "seen at head"),
            status(cands[1], STATUS_NOT_REPRODUCED, "report predates the fix"),
            status(cands[2], STATUS_NOT_CHECKED),
            status(cands[3], STATUS_DROPPED_FOR_BUDGET),
        ],
        [report(REPORT, REPORT_PARSED, candidates=cands, other_drift=2)],
    )
    assert "- **V1 (confirmed)** from `" + REPORT + "`: \\| row 1 \\|" in body
    assert "— seen at head" in body
    assert "- **V2 (not reproduced)**" in body and "— report predates the fix" in body
    assert "- **V3 (unchecked)**" in body
    assert "- **V4 (unchecked)**" in body
    assert body.count("— not checked by the model") == 2
    assert "- Other drift: 2 items, see the report." in body
    assert "**blocking**" in body


def test_verifier_row_text_comes_from_wrapper_not_model_reason():
    """D-38: the row is ``candidate.text``; a reason quoting other text stays a reason."""
    c = candidate(1, "| DR-1 | Critical | Unintended | real row |")
    body = _verifier_only(
        [status(c, STATUS_CONFIRMED, "| DR-9 | Critical | Unintended | invented row |")],
        [report(REPORT, REPORT_PARSED, candidates=[c])],
    )
    line = next(ln for ln in body.split("\n") if ln.startswith("- **V1"))
    row_part, reason_part = line.split(" — ", 1)
    assert "real row" in row_part and "invented row" not in row_part
    assert "invented row" in reason_part


@pytest.mark.parametrize("state", [STATUS_NOT_CHECKED, STATUS_DROPPED_FOR_BUDGET])
def test_verifier_reason_from_model_only_when_flagged(state):
    """A not-checked candidate never shows a model reason, even if one is set."""
    c = candidate(1, "| r | Critical | Unintended |")
    from validate import CandidateStatus

    forged = CandidateStatus(c, state, "MODEL SAYS HI", True)
    assert not forged.reason_from_model
    body = _verifier_only([forged], [report(REPORT, REPORT_PARSED, candidates=[c])])
    assert "MODEL SAYS HI" not in body
    assert "— not checked by the model" in body


def test_verifier_row_with_pipes_backticks_and_bold_stays_one_item():
    """TC-212-07."""
    c = candidate(1, "| a `b` **c** | Critical | Unintended |\n[truncated]\n")
    body = _verifier_only(
        [status(c, STATUS_CONFIRMED, "ok")], [report(REPORT, REPORT_PARSED, candidates=[c])]
    )
    lines = [ln for ln in body.split("\n") if "V1" in ln]
    assert len(lines) == 1
    assert "\\| a \\`b\\` \\*\\*c\\*\\* \\| Critical \\| Unintended \\| \\[truncated\\]" in lines[0]


def test_verifier_other_drift_omitted_when_zero_and_singular_when_one():
    c = candidate(1, "| r | Critical | Unintended |")
    body = _verifier_only(
        [status(c, STATUS_CONFIRMED, "ok")], [report(REPORT, REPORT_PARSED, candidates=[c])]
    )
    assert "Other drift" not in body
    body = _verifier_only([], [report(REPORT, REPORT_PARSED, other_drift=1)])
    assert "- Other drift: 1 item, see the report." in body


def test_verifier_other_drift_across_reports_says_reports():
    body = _verifier_only(
        [],
        [
            report(REPORT, REPORT_PARSED, other_drift=2),
            report("workstream/fidelity-report-issue-9.md", REPORT_PARSED, other_drift=1),
        ],
    )
    assert "- Other drift: 3 items, see the reports." in body


def test_verifier_parsed_report_without_candidates():
    body = _verifier_only([], [report(REPORT, REPORT_PARSED)])
    assert "### Verifier" in body
    assert f"- `{REPORT}`: no Critical Unintended drift." in body


def test_verifier_no_report():
    body = _verifier_only([], [report(REPORT, REPORT_NONE)], state=REPORT_NONE)
    assert "**Verifier:** no verifier report." in body
    assert "### Verifier" not in body


def test_verifier_no_context_at_all_is_no_report():
    fx = clear_fixture()
    fx["verifier"] = None
    assert "**Verifier:** no verifier report." in body_of(fx)


def test_verifier_not_parseable():
    body = _verifier_only([], [report(REPORT, REPORT_NOT_PARSEABLE)], state=REPORT_NOT_PARSEABLE)
    assert f"**Verifier:** report not parseable (`{REPORT}`)." in body


def test_verifier_not_parseable_without_context_uses_the_flag():
    fx = clear_fixture()
    fx["verifier"] = None
    fx["context"] = context_data(verifier_state=REPORT_NOT_PARSEABLE)
    assert "**Verifier:** report not parseable." in body_of(fx)


def test_verifier_unavailable_is_not_called_no_report():
    """S-208 DR-3: a 403 on the only report looks like ``none``; say so."""
    body = _verifier_only([], [report(REPORT, REPORT_NONE)], unavailable=True, state=REPORT_NONE)
    assert "**Verifier:** verifier reports unavailable (permission)." in body
    assert "no verifier report" not in body


def test_verifier_unavailable_without_context_uses_the_flag():
    fx = clear_fixture()
    fx["verifier"] = None
    fx["context"] = context_data(verifier_unavailable=True)
    assert "**Verifier:** verifier reports unavailable (permission)." in body_of(fx)


def test_verifier_mixed_states_are_listed_per_report():
    """S-208 DR-6: one parsed report must not hide an unparseable one or a 403."""
    c = candidate(1, "| r | Critical | Unintended |")
    other = "workstream/fidelity-report-issue-315.md"
    body = _verifier_only(
        [status(c, STATUS_CONFIRMED, "ok")],
        [
            report(REPORT, REPORT_PARSED, candidates=[c]),
            report(other, REPORT_NOT_PARSEABLE),
        ],
        unavailable=True,
    )
    assert f"- `{other}`: report not parseable." in body
    assert "- Some verifier reports unavailable (permission)." in body


def test_verifier_not_parseable_and_unavailable_without_parsed():
    body = _verifier_only(
        [], [report(REPORT, REPORT_NOT_PARSEABLE)], unavailable=True, state=REPORT_NOT_PARSEABLE
    )
    assert (
        f"**Verifier:** report not parseable (`{REPORT}`); "
        "some verifier reports unavailable (permission)." in body
    )


# ---------------------------------------------------------------------------
# AC-3: context line (TC-212-08; S-209 DR-5, S-210 DR-12, S-206 D4/D7)
# ---------------------------------------------------------------------------


def _ctx_line(**kwargs) -> str:
    diff = kwargs.pop("diff", None)
    fx = clear_fixture()
    fx["context"] = context_data(**kwargs)
    if diff is not None:
        fx["diff"] = diff
    return context_line(body_of(fx))


def test_context_line_issues_spec_files_and_names():
    """TC-212-08 (the blocking snapshot holds the full line)."""
    line = context_line(body_of(blocking_fixture()))
    assert line.startswith("**Context:** issue #315 · spec `" + SPEC + "` (trimmed)")
    assert "2 files too large to include in full: `src/app.py`, `src/old.py`" in line
    assert "listed by name only: `pnpm-lock.yaml` (lockfile)" in line


def test_context_line_several_issues():
    assert _ctx_line(issue_numbers=(315, 316)).startswith("**Context:** issues #315, #316 · ")


def test_context_line_no_issues_and_no_spec():
    assert _ctx_line() == "**Context:** no linked issues · no spec found"


def test_context_line_issues_unavailable():
    line = _ctx_line(issues_unavailable=True, no_issues=True)
    assert "issues unavailable (permission)" in line
    assert "no linked issues" not in line
    line = _ctx_line(issue_numbers=(5,), issues_unavailable=True)
    assert line.startswith("**Context:** issue #5 · issues unavailable (permission) · ")


def test_context_line_block_notes():
    """Every truncated or omitted block is named (spec §8.4 step 4)."""
    other = "workstream/specification-prd-other.md"
    line = _ctx_line(
        issue_numbers=(1, 2),
        spec_paths=(SPEC,),
        notes=(
            BlockNote("pr", None, "truncated", "cap"),
            BlockNote("issue", "#1", "truncated", "budget"),
            BlockNote("issue", "#3", "omitted", "budget"),
            BlockNote("verifier", REPORT, "truncated", "cap"),
            BlockNote("spec", SPEC, "truncated", "budget"),
            BlockNote("spec", other, "omitted", "empty"),
            BlockNote("conventions", None, "omitted", "budget"),
        ),
    )
    assert "issues #1 (truncated for budget), #2" in line
    assert "issue #3 omitted (budget)" in line
    assert f"spec `{SPEC}` (truncated for budget)" in line
    assert f"spec `{other}` (empty, not included)" in line
    assert "PR description (truncated)" in line
    assert f"verifier report `{REPORT}` (truncated)" in line
    assert "conventions omitted (budget)" in line


def test_context_line_spec_omitted_for_budget_and_cap_truncation():
    line = _ctx_line(
        spec_paths=(),
        no_spec=False,
        notes=(BlockNote("spec", SPEC, "omitted", "budget"),),
    )
    assert f"spec `{SPEC}` omitted (budget)" in line
    assert "no spec found" not in line
    line = _ctx_line(spec_paths=(SPEC,), notes=(BlockNote("spec", SPEC, "truncated", "cap"),))
    assert f"spec `{SPEC}` (truncated)" in line


def test_context_line_empty_pr_and_conventions():
    line = _ctx_line(
        notes=(
            BlockNote("pr", None, "omitted", "empty"),
            BlockNote("conventions", None, "truncated", "budget"),
        )
    )
    assert "PR description (empty, not included)" in line
    assert "conventions (truncated for budget)" in line


def test_context_line_name_only_listing_cut_note():
    line = _ctx_line(notes=(BlockNote("diff", "name-only", "truncated", "cap"),))
    assert "name-only list truncated for the model" in line


def test_context_line_all_full_files_dropped_after_retry_or_repair():
    """S-210 DR-12: with no full file left, say why without claiming size."""
    line = _ctx_line(full_files_dropped=("a.py", "b.py", "c.py"))
    assert "full files omitted to fit the model's context (3 files)" in line
    assert "too large" not in line
    line = _ctx_line(full_files_dropped=("a.py",))
    assert "full files omitted to fit the model's context (1 file)" in line


def test_context_line_one_file_too_large():
    line = _ctx_line(full_files_included=("a.py",), full_files_dropped=("b.py",))
    assert "1 file too large to include in full: `b.py`" in line


def test_context_line_name_only_reasons_and_binary_label():
    """S-206 D7: an empty or mode-only file is never called "binary"."""
    diff = diff_ctx(
        files=(file_diff("src/app.py"),),
        name_only=(
            NameOnlyFile("pkg/__init__.py", "added", "binary"),
            NameOnlyFile("dist/app.js", "modified", "generated"),
            NameOnlyFile("workstream/tasks-x.md", "modified", "excluded"),
            NameOnlyFile(
                "src/gone.py", "modified", "content_unavailable", "not found at the reviewed commit"
            ),
        ),
    )
    line = _ctx_line(diff=diff)
    assert "`pkg/__init__.py` (no text diff)" in line
    assert "binary" not in line
    assert "`dist/app.js` (generated)" in line
    assert "`workstream/tasks-x.md` (excluded)" in line
    assert "`src/gone.py` (content unavailable: not found at the reviewed commit)" in line


def test_context_line_base_withheld():
    """S-206 D4 / D-42."""
    diff = diff_ctx(
        files=(
            file_diff("a.py", base_withheld="excluded"),
            file_diff("b.py", base_withheld="lockfile"),
            file_diff("c.py", base_withheld="generated"),
        )
    )
    line = _ctx_line(diff=diff)
    assert (
        "base withheld: `a.py` (previous name is excluded), `b.py` (previous name is a lockfile),"
        " `c.py` (previous name is generated)" in line
    )


def test_context_line_lists_are_capped():
    names = [NameOnlyFile(f"gen/f{k}.min.js", "added", "generated") for k in range(25)]
    line = _ctx_line(diff=diff_ctx(files=(file_diff("x.py"),), name_only=names))
    assert line.count("(generated)") == render.LIST_MAX
    assert "and 5 more" in line
    line = _ctx_line(
        full_files_included=("k.py",), full_files_dropped=tuple(f"f{k}.py" for k in range(23))
    )
    assert "23 files too large to include in full: " in line
    assert "and 3 more" in line


def test_context_line_long_paths_are_cut():
    long = "d/" * 400 + "x.py"
    line = _ctx_line(
        diff=diff_ctx(
            files=(file_diff("x.py"),), name_only=[NameOnlyFile(long, "added", "generated")]
        )
    )
    assert len(line) < 400
    assert "…" in line


def test_context_line_paths_are_neutralized():
    """S-209: ``ContextData`` paths are raw repository text."""
    evil = "a`b@c<d>.py"
    line = _ctx_line(full_files_included=("k.py",), full_files_dropped=(evil,))
    assert f"`ab@{ZW}c&lt;d&gt;.py`" in line


# ---------------------------------------------------------------------------
# AC-4: neutralization (TC-212-09…11; spec §8.8; DF-19)
# ---------------------------------------------------------------------------


HOSTILE = (
    "@user @org/team @everyone </details> <script>x</script> <img src=x onerror=alert(1)> "
    "--> <!-- code-review-agent:v1 run=x sha=y --> [x](javascript:alert(1)) ![](http://t/p.png) "
    "<https://evil.example> https://evil.example www.evil.example a@b.example "
    "&#64;user &lt; \\*x\\* *em* _u_ ~~s~~ | a | b | $x$ owner/repo#12 #34 `code`\n"
    "# heading\n> quote\n- item\n=====\r\n next\u0085end\x1b[31m‮RTL"
)


def _hostile_fixture() -> dict:
    c = candidate(1, HOSTILE)
    fx = blocking_fixture()
    fx["validation"] = validation(
        [
            finding(
                "B1",
                category="correctness",
                file="src/`app`@x</details>.py\n# h",
                title=HOSTILE,
                failure_scenario=HOSTILE,
                consequence=HOSTILE,
            )
        ],
        [finding("S1", file="@s.py", title=HOSTILE, consequence=HOSTILE)],
        [status(c, STATUS_CONFIRMED, HOSTILE)],
    )
    fx["context"] = context_data(
        issue_numbers=(1,),
        spec_paths=("workstream/specification-@x<y>.md",),
        full_files_included=("k.py",),
        full_files_dropped=("@d</details>.py",),
        verifier_state=REPORT_PARSED,
        notes=(BlockNote("verifier", "r@x<y>.md", "truncated", "cap"),),
    )
    fx["diff"] = diff_ctx(
        files=(file_diff("@w.py", base_withheld="excluded"),),
        name_only=(NameOnlyFile("@n<x>.lock", "added", "content_unavailable", "<b>@d</b>"),),
    )
    fx["verifier"] = verifier_ctx(
        report(REPORT, REPORT_PARSED, candidates=[c]),
        report("@bad<x>.md", REPORT_NOT_PARSEABLE),
    )
    return fx


def test_neutralize_mentions_everywhere():
    """TC-212-09."""
    body = body_of(_hostile_fixture(), model_id="@model<x>")
    assert unescaped_mentions(body) == []
    assert f"@{ZW}everyone" in body
    assert f"@{ZW}org/team" in body


def test_neutralize_html_and_marker_cannot_be_forged_or_closed():
    """TC-212-10."""
    body = body_of(_hostile_fixture(), model_id="<!-- x -->")
    assert content_lt(body) == 0
    assert body.count("<!--") == 1
    assert body.count("-->") == 1
    assert body.count("</details>") == 1
    assert body.count("<details>") == 1
    assert "&lt;/details&gt;" in body


def test_neutralize_backticks_stripped_from_paths():
    """TC-212-11 (paths)."""
    body = body_of(_hostile_fixture())
    assert f"`src/app@{ZW}x&lt;/details&gt;.py\\n# h:1`" in body


def test_neutralize_links_images_and_autolinks_are_inert():
    """TC-212-11 / DF-19: no link, image or autolink can form from content."""
    text = neutralize(
        "[x](javascript:alert(1)) ![](http://t/p.png) <https://e.x> https://e.x www.e.x"
    )
    assert "\\[x\\]" in text
    assert "\\!\\[\\]" in text
    assert "&lt;https:" in text
    assert "https://" not in text and "http://" not in text
    assert f"https:{ZW}//" in text
    assert "www." not in text and f"www{ZW}." in text


def test_neutralize_markdown_breakers_stay_in_slot():
    text = neutralize("a\nb\r\nc\rd e f\u0085g\x0bh\x0ci # j | k ~ l $ m _ n * o \\ p ` q")
    assert "\n" not in text and "\r" not in text and " " not in text and "\x85" not in text
    for token in ("\\|", "\\~", "\\$", "\\_", "\\*", "\\\\", "\\`"):
        assert token in text
    assert f"#{ZW} j" in text


def test_neutralize_issue_references_are_broken():
    text = neutralize("owner/repo#12 and #34 and GH-5")
    assert "#12" not in text and "#34" not in text
    assert f"#{ZW}12" in text


def test_neutralize_entities_cannot_rebuild_mentions_or_tags():
    text = neutralize("&#64;user &lt;b&gt;")
    assert text == f"&amp;#{ZW}64;user &amp;lt;b&amp;gt;"


def test_neutralize_controls_and_bidi_are_removed():
    text = neutralize("a\x00b\x1b[31mc‮d⁦e\x7ff\x9bg")
    assert text == "a b \\[31mcde f g"


def test_neutralize_strips_surrounding_whitespace():
    assert neutralize("  \n hi \t ") == "hi"


def test_neutralize_hostile_body_renders_as_inert_markdown():
    """A CommonMark parse of the hostile body finds only the wrapper's structure."""
    markdown_it = pytest.importorskip("markdown_it")
    body = body_of(_hostile_fixture())
    md = markdown_it.MarkdownIt("commonmark").enable("table").enable("strikethrough")
    tokens = md.parse(body)
    flat = [t for tok in tokens for t in ([tok] + list(tok.children or []))]
    links = [t for t in flat if t.type == "link_open"]
    assert [t.attrGet("href") for t in links] == [RUN_URL]
    assert not [t for t in flat if t.type == "image"]
    assert not [t for t in flat if t.type.startswith("table")]
    assert not [t for t in flat if t.type in ("s_open", "blockquote_open")]
    headings = [t for t in tokens if t.type == "heading_open"]
    assert [t.tag for t in headings] == ["h2", "h3", "h3"]
    html = [t.content.strip() for t in flat if t.type in ("html_block", "html_inline")]
    allowed = {"<details><summary>", "</summary>", "</details>", "<sub>", "</sub>"}
    for chunk in html:
        if chunk.startswith("<!--"):
            assert chunk == f"<!-- code-review-agent:v1 run={RUN_ID} sha={HEAD} -->"
            continue
        assert chunk in allowed or chunk.startswith("<details><summary>Suggestions"), chunk


def test_neutralize_model_id_and_rubric_version():
    body = body_of(clear_fixture(), model_id="m`x`@y<z>\nq", rubric_version="1 @x <b>")
    footer = body.rstrip("\n").split("\n")[-1]
    assert f"Model `mx@{ZW}y&lt;z&gt;\\nq`" in footer
    assert f"rubric v1 @{ZW}x &lt;b&gt;" in footer


def test_neutralize_empty_code_text_gets_no_empty_code_span():
    body = body_of(clear_fixture(), model_id="``")
    assert "Model (unknown)" in body
    assert "``" not in body


def test_neutralize_empty_title_is_placeholder():
    fx = clear_fixture()
    fx["validation"] = validation([finding("B1", title="  \n ")])
    assert "`src/app.py:1`** — (untitled)" in body_of(fx)


# ---------------------------------------------------------------------------
# Line numbers (S-211 integration note 3)
# ---------------------------------------------------------------------------


def test_huge_line_numbers_render_compactly():
    fx = clear_fixture()
    fx["validation"] = validation(
        [finding("B1", line_start=10**300, line_end=10**300 + 5)],
        [finding("S1", line_start=1, line_end=10**300)],
    )
    body = body_of(fx)
    assert "`src/app.py:999999999+`" in body
    assert "`src/app.py:1-999999999+`" in body
    assert "0" * 20 not in body


def test_line_numbers_over_4300_digits_never_reach_str():
    huge = 10**5000
    with pytest.raises(ValueError):
        str(huge)
    fx = clear_fixture()
    fx["validation"] = validation([finding("B1", line_start=huge, line_end=huge * 3)])
    assert "999999999+" in body_of(fx)


def test_escaped_path_equals_escape_path_then_cut():
    """The prefix shortcut in ``_escaped_path`` gives exactly ``escape_path`` then the cut."""
    import random

    from context.diff import escape_path

    rng = random.Random(414002)
    alphabet = ["a", "\\", "\n", "\x1b", "\u2028", "\x85", "`", "é", "/", "\x7f", "\xa0"]
    for _ in range(5000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30)))
        for limit in (None, 1, 2, 5, 10, 400):
            expected = render._cut(escape_path(text).replace("`", ""), limit)
            assert render._escaped_path(text, limit) == expected, (text, limit)


def test_line_number_boundaries():
    assert render.format_line(999_999_999) == "999999999"
    assert render.format_line(1_000_000_000) == "999999999+"
    assert render.format_line(1) == "1"


# ---------------------------------------------------------------------------
# AC-5: size guarantee (TC-212-12…15; D-28, D-36)
# ---------------------------------------------------------------------------


def _filler(n: int, prefix: str = "x") -> str:
    return (prefix * n)[:n]


def _len_unlimited(fx: dict) -> int:
    return len(body_of(fx, limit=10**9))


def test_truncate_limit_is_60000():
    assert MAX_COMMENT_CHARS == 60_000
    assert NOTE == TRUNCATION_NOTE


def test_truncate_stage1_drops_suggestions_from_the_end():
    """TC-212-12."""
    fx = clear_fixture()
    blocking = [
        finding(f"B{k}", failure_scenario=_filler(1500), title=f"b{k}") for k in range(1, 31)
    ]
    suggestions = [
        finding(f"S{k}", title=_filler(200, chr(ord("a") + k)), consequence=_filler(500, "c"))
        for k in range(1, 21)
    ]
    fx["validation"] = validation(blocking, suggestions)
    out = review(fx)
    assert len(out.body) <= MAX_COMMENT_CHARS
    assert out.truncated and out.stages == (1,)
    assert NOTE in out.body
    kept = [s for s in suggestions if f"**{s.id} · " in out.body]
    assert kept == suggestions[: len(kept)]
    assert 0 < len(kept) < 20
    assert f"<details><summary>Suggestions ({len(kept)} of 20)</summary>" in out.body
    for b in blocking:  # blocking text untouched
        assert _filler(1500) in out.body.split(f"**{b.id} · ", 1)[1]


def test_truncate_stage1_drops_all_and_removes_the_details():
    fx = clear_fixture()
    blocking = [finding(f"B{k}", failure_scenario=_filler(1500)) for k in range(1, 40)]
    fx["validation"] = validation(blocking, [finding("S1", title="t", consequence="c")])
    out = review(fx)
    assert 1 in out.stages and 2 in out.stages
    assert "<details>" not in out.body


def test_truncate_stage2_cuts_scenarios_and_consequences():
    """TC-212-13: 40 blocking findings with 1,500-char scenarios."""
    fx = clear_fixture()
    blocking = [
        finding(f"B{k}", failure_scenario=_filler(1500, "s"), consequence=_filler(500, "c"))
        for k in range(1, 41)
    ]
    fx["validation"] = validation(blocking)
    out = review(fx)
    assert out.stages == (2,)
    assert len(out.body) <= MAX_COMMENT_CHARS
    scen = re.findall(r"\*\*Fails when:\*\* (s+…?)\n", out.body)
    cons = re.findall(r"\*\*Consequence:\*\* (c+…?)\n", out.body)
    assert len(scen) == len(cons) == 40
    assert all(len(s) == 500 and s.endswith("…") for s in scen)
    assert all(len(c) == 200 and c.endswith("…") for c in cons)
    assert NOTE in out.body


def test_truncate_stage3_cuts_verifier_rows_and_reasons():
    fx = clear_fixture()
    cands = [candidate(k, "r" * 1000) for k in range(1, 80)]
    fx["validation"] = validation([], [], [status(c, STATUS_CONFIRMED, "q" * 300) for c in cands])
    fx["verifier"] = verifier_ctx(report(REPORT, REPORT_PARSED, candidates=cands))
    out = review(fx)
    assert 3 in out.stages and 5 not in out.stages
    assert len(out.body) <= MAX_COMMENT_CHARS
    rows = re.findall(r"`: (r+…?) — ", out.body)
    assert len(rows) == 79 and all(len(r) == 300 for r in rows)
    assert re.findall(r" — (q+…?)\n", out.body)[0] == "q" * 300


def test_truncate_stage4_renders_the_rest_as_one_line_entries():
    fx = clear_fixture()
    blocking = [
        finding(
            f"B{k}",
            file=_filler(394, "p") + f"{k:02d}.py",
            title="<" * 200,
            failure_scenario=_filler(1500, "s"),
            consequence=_filler(500, "c"),
        )
        for k in range(1, 41)
    ]
    fx["validation"] = validation(blocking)
    out = review(fx)
    assert out.stages == (2, 4)
    assert len(out.body) <= MAX_COMMENT_CHARS
    full = out.body.count("**Fails when:**")
    assert 0 < full < 40
    more = 40 - full
    assert f"{more} more blocking findings are listed by title only:" in out.body
    one_liners = re.findall(r"^- \*\*B(\d+) · correctness · `", out.body, re.M)
    assert [int(n) for n in one_liners] == list(range(full + 1, 41))
    # rank order: full detail first
    assert out.body.index("**B1 · ") < out.body.index(f"- **B{full + 1} · ")


def test_truncate_stage5_hard_cut_at_line_boundary_keeps_header_and_footer():
    fx = clear_fixture()
    cands = [candidate(k, "<" * 1050) for k in range(1, 3000)]
    fx["validation"] = validation([], [], [status(c, STATUS_CONFIRMED, "<" * 300) for c in cands])
    fx["verifier"] = verifier_ctx(report(REPORT, REPORT_PARSED, candidates=cands))
    out = review(fx)
    assert 5 in out.stages
    assert len(out.body) <= MAX_COMMENT_CHARS
    assert out.body.startswith("<!-- code-review-agent:v1 ")
    assert "## Code review: **blocking** · `9f2c4e1`" in out.body
    assert out.body.endswith("</sub>\n")
    assert NOTE in out.body
    lines = out.body.split("\n")
    vlines = [ln for ln in lines if ln.startswith("- **V")]
    assert vlines and all(ln.endswith("…") or ln.endswith(";") for ln in vlines)


def test_truncate_worst_case_at_schema_maxima_escape_heavy():
    """TC-212-14: 40 blocking at schema maxima, all ``<``, huge candidate counts and lines."""
    fx = blocking_fixture()
    lt = "<"
    blocking = [
        finding(
            f"B{k}",
            file=lt * 400,
            line_start=10**300,
            line_end=10**300 + 1,
            title=lt * 200,
            failure_scenario=lt * 1500,
            consequence=lt * 500,
        )
        for k in range(1, 41)
    ]
    suggestions = [
        finding(
            f"S{k}",
            file="&" * 400,
            line_start=1,
            line_end=10**300,
            title="&" * 200,
            consequence="&" * 500,
        )
        for k in range(1, 21)
    ]
    cands = [candidate(k, "&" * 1050, report="@" * 400) for k in range(1, 5001)]
    statuses = [status(c, STATUS_CONFIRMED, "&" * 300) for c in cands]
    fx["validation"] = validation(blocking, suggestions, statuses)
    fx["verifier"] = verifier_ctx(
        report("@" * 400, REPORT_PARSED, candidates=cands, other_drift=10**6)
    )
    names = [NameOnlyFile("<" * 2000, "added", "generated") for _ in range(5000)]
    fx["diff"] = diff_ctx(
        files=tuple(file_diff("&" * 2000, base_withheld="excluded") for _ in range(5000)),
        name_only=names,
    )
    fx["context"] = context_data(
        issue_numbers=tuple(range(1, 6)),
        spec_paths=("<" * 2000,) * 50,
        full_files_included=("k",),
        full_files_dropped=("<" * 2000,) * 5000,
        issues_unavailable=True,
        verifier_state=REPORT_PARSED,
        verifier_unavailable=True,
        notes=tuple(BlockNote("spec", "<" * 2000, "omitted", "budget") for _ in range(200)),
    )
    started = time.perf_counter()
    out = review(fx, model_id="<" * 10_000, panel_base_url=PANEL)
    elapsed = time.perf_counter() - started
    assert len(out.body) <= MAX_COMMENT_CHARS < 65_536
    assert out.stages == (1, 2, 3, 4, 5)
    assert out.body.startswith(f"<!-- code-review-agent:v1 run={RUN_ID} sha={HEAD} -->\n\n")
    assert "## Code review: **blocking** · `9f2c4e1`\n" in out.body
    assert NOTE in out.body
    assert out.body.endswith("</sub>\n")
    assert content_lt(out.body) == 0
    assert unescaped_mentions(out.body) == []
    assert elapsed < 5


def test_truncate_exactly_60000_untouched_and_60001_truncated():
    """TC-212-15, tuned with schema-valid scenario lengths (≤ 1,500)."""
    fx = clear_fixture()
    lengths = [1500] * 40
    fx["validation"] = validation(
        [finding(f"B{k}", failure_scenario=_filler(1500)) for k in range(1, 41)]
    )
    excess = _len_unlimited(fx) - MAX_COMMENT_CHARS
    assert excess > 0
    for k in range(40):  # shrink scenarios from the front until the body is exactly 60,000
        take = min(excess, lengths[k] - 1)
        lengths[k] -= take
        excess -= take
        if not excess:
            break

    def build(extra: int) -> None:
        sizes = [lengths[0] + extra, *lengths[1:]]
        fx["validation"] = validation(
            [finding(f"B{k + 1}", failure_scenario=_filler(n)) for k, n in enumerate(sizes)]
        )

    build(0)
    out = review(fx)
    assert len(out.body) == MAX_COMMENT_CHARS
    assert not out.truncated and NOTE not in out.body
    build(1)
    out = review(fx)
    assert out.truncated and out.stages == (2,)
    assert len(out.body) <= MAX_COMMENT_CHARS


def _suggestions_size(entries: list[str], k: int) -> int:
    return 0 if k == 0 else 2 + len(render._suggestions_section(entries, k) or "")


def _blocking_size(full: list[str], lines: list[str], j: int) -> int:
    return 2 + len(render._blocking_section(full, lines, j))


def test_truncate_fit_arithmetic_matches_a_brute_force_render():
    """Stages 1 and 4 keep the longest prefix that fits, computed from lengths only."""
    import random

    rng = random.Random(414003)
    for _ in range(60):
        n = rng.randint(1, 25)
        entries = ["e" * rng.randint(1, 3000) for _ in range(n)]
        fixed = rng.randint(0, 40_000)
        limit = 60_000
        k = render._fit_suggestions(fixed, entries, limit)
        assert fixed + _suggestions_size(entries, k) <= limit or k == 0
        if k + 1 < n:
            assert fixed + _suggestions_size(entries, k + 1) > limit
        full = ["f" * rng.randint(1, 3000) for _ in range(n)]
        lines = ["- " + "l" * rng.randint(1, 900) for _ in range(n)]
        j = render._fit_blocking(fixed, full, lines, limit)
        assert fixed + _blocking_size(full, lines, j) <= limit or j == 0
        if j + 1 < n:
            assert fixed + _blocking_size(full, lines, j + 1) > limit


def test_truncate_measures_after_escaping():
    """A body short in raw text but long once escaped is still cut."""
    fx = clear_fixture()
    blocking = [
        finding(f"B{k}", failure_scenario="&" * 1500, consequence="&" * 500) for k in range(1, 9)
    ]
    fx["validation"] = validation(blocking)
    raw = sum(len(b.failure_scenario) + len(b.consequence) for b in blocking)
    assert raw < MAX_COMMENT_CHARS
    out = review(fx)
    assert out.truncated
    assert len(out.body) <= MAX_COMMENT_CHARS


def test_truncate_never_changes_the_verdict():
    fx = clear_fixture()
    fx["validation"] = validation(
        [], [finding(f"S{k}", title="<" * 200, consequence="<" * 500) for k in range(1, 21)] * 4
    )
    out = review(fx)
    assert out.truncated
    assert "## Code review: **clear**" in out.body


def test_truncate_limit_keyword_validation():
    with pytest.raises(ValueError):
        review(clear_fixture(), limit=100)


# ---------------------------------------------------------------------------
# AC-6: budget and failure comments (TC-212-16, TC-212-17; D-29, DF-08)
# ---------------------------------------------------------------------------


def test_budget_msg_lines_snapshot():
    """TC-212-16."""
    over = OverBudget(lines=2412, files=31, max_diff_lines=2000)
    names = (
        NameOnlyFile("pnpm-lock.yaml", "modified", "lockfile"),
        NameOnlyFile("pkg/__init__.py", "added", "binary"),
    )
    body = render_budget(over, run_id=RUN_ID, panel_base_url=PANEL, name_only=names)
    snapshot("budget_lines.md", body)


def test_budget_msg_without_name_only_is_one_line():
    over = OverBudget(lines=2412, files=31, max_diff_lines=2000)
    body = render_budget(over, run_id=RUN_ID, panel_base_url=PANEL)
    assert body == (
        "This PR changes 2412 lines in 31 files, over the review budget of 2000 lines."
        f" Not reviewed. [run]({RUN_URL})\n"
    )


def test_budget_msg_tokens_snapshot():
    """TC-212-17 / DF-08: the token path states token counts."""
    over = OverBudget(
        lines=1500,
        files=12,
        max_diff_lines=2000,
        reason="tokens",
        tokens=166_250,
        diff_tokens=160_000,
        max_context_tokens=150_000,
    )
    body = render_budget(over, run_id=RUN_ID, panel_base_url=PANEL)
    snapshot("budget_tokens.md", body)
    assert "over the review budget of 2000 lines" not in body


def test_budget_msg_truncated_listing_says_at_least():
    """S-206 D2: the counts are lower bounds when the listing hit the cap."""
    over = OverBudget(lines=1200, files=3000, max_diff_lines=2000, truncated=True)
    body = render_budget(over, run_id=RUN_ID, panel_base_url=PANEL)
    assert body.startswith("This PR changes at least 1200 lines in at least 3000 files.")
    assert "Its file list is longer than GitHub returns" in body
    assert "review budget of 2000 lines. Not reviewed." in body


def test_budget_msg_name_only_list_is_capped_and_neutralized():
    names = [NameOnlyFile(f"@g{k}<x>.min.js", "added", "generated") for k in range(30)]
    over = OverBudget(lines=9, files=1, max_diff_lines=5)
    body = render_budget(over, run_id=RUN_ID, panel_base_url=PANEL, name_only=names)
    assert body.count("(generated)") == render.LIST_MAX
    assert "and 10 more" in body
    assert unescaped_mentions(body) == [] and content_lt(body) == 0


def test_budget_msg_huge_counts_are_compact():
    over = OverBudget(lines=10**5000, files=10**400, max_diff_lines=2000)
    body = render_budget(over, run_id=RUN_ID, panel_base_url=PANEL)
    assert "999999999+ lines in 999999999+ files" in body


def test_budget_msg_tokens_with_missing_fields_falls_back_to_lines_wording():
    over = OverBudget(lines=10, files=1, max_diff_lines=5, reason="tokens")
    body = render_budget(over, run_id=RUN_ID, panel_base_url=PANEL)
    assert body.startswith(
        "This PR changes 10 lines in 1 file; its expanded diff is over the context budget."
    )


def test_failure_msg_snapshot():
    """TC-212-16."""
    snapshot("failure.md", render_failure("BEDROCK_ERROR", run_id=RUN_ID, panel_base_url=PANEL))


@pytest.mark.parametrize("code", render.ERROR_CODES)
def test_failure_msg_every_spec_code(code):
    body = render_failure(code, run_id=RUN_ID, panel_base_url=PANEL)
    assert body == f"Code review failed (`{code}`). [run]({RUN_URL})\n"


def test_failure_msg_codes_are_spec_13():
    assert render.ERROR_CODES == (
        "INVALID_PARAMS",
        "GITHUB_PERMISSION_DENIED",
        "GITHUB_API_ERROR",
        "BEDROCK_ACCESS_DENIED",
        "BEDROCK_ERROR",
        "MODEL_OUTPUT_INVALID",
        "RUN_TIMEOUT",
        "COMMENT_POST_FAILED",
        "INTERNAL_ERROR",
    )


@pytest.mark.parametrize(
    "code",
    ["boom: KeyError('x') @here", "", "GITHUB_NOT_FOUND", "bedrock_error", None, 42],
)
def test_failure_msg_unknown_codes_render_internal_error(code):
    """Fixed text only: an exception message or unknown code never reaches the comment."""
    body = render_failure(code, run_id=RUN_ID, panel_base_url=PANEL)  # type: ignore[arg-type]
    assert body == f"Code review failed (`INTERNAL_ERROR`). [run]({RUN_URL})\n"


def test_failure_msg_never_includes_an_exception_message():
    from bedrock_adapter import BedrockError

    exc = BedrockError("secret detail @user <b>")
    body = render_failure(exc.code, run_id=RUN_ID, panel_base_url=PANEL)
    assert "secret" not in body


@pytest.mark.parametrize(
    "base",
    [PANEL + "/", PANEL + "///", PANEL + "/panel/"],
)
def test_run_link_trailing_slash_has_no_double_slash(base):
    """TC-212-17."""
    body = render_failure("RUN_TIMEOUT", run_id=RUN_ID, panel_base_url=base)
    assert "//runs" not in body
    assert f"/runs/{RUN_ID})" in body


@pytest.mark.parametrize(
    "base, run_id",
    [
        ("javascript:alert(1)", RUN_ID),
        ("https://x.example) [evil](https://e", RUN_ID),
        ("https://x.example/a b", RUN_ID),
        ("https://x.example/<b>", RUN_ID),
        ("ftp://x.example", RUN_ID),
        ("https://user@x.example", RUN_ID),
        ("https://" + "a" * 300, RUN_ID),
        ("", RUN_ID),
        (PANEL, "../../admin"),
        (PANEL, RUN_ID + ")"),
        (PANEL, ""),
    ],
)
def test_run_link_rejects_injection(base, run_id):
    """D-29: a malformed ``PANEL_BASE_URL`` or ``run_id`` gives no link at all."""
    body = render_failure("RUN_TIMEOUT", run_id=run_id, panel_base_url=base)
    assert body == "Code review failed (`RUN_TIMEOUT`). (run link unavailable)\n"
    over = OverBudget(lines=10, files=1, max_diff_lines=5)
    assert "(run link unavailable)" in render_budget(over, run_id=run_id, panel_base_url=base)
    footer = (
        body_of(clear_fixture(), run_id=run_id, panel_base_url=base).rstrip("\n").split("\n")[-1]
    )
    assert footer.endswith("· (run link unavailable)</sub>")


def test_run_link_accepts_http_localhost_with_port():
    assert (
        render.run_link("http://localhost:3000", RUN_ID) == f"http://localhost:3000/runs/{RUN_ID}"
    )


# ---------------------------------------------------------------------------
# Purity (no I/O) and the integration contract with the real builders
# ---------------------------------------------------------------------------


def test_render_module_is_pure():
    """Rendering imports nothing that does I/O and opens nothing."""
    source = Path(render.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {
        "__future__",
        "re",
        "collections",
        "dataclasses",
        "typing",
        "budget",
        "context",
        "validate",
    }
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"open", "print", "input", "eval", "exec"}


def test_render_is_deterministic():
    assert body_of(blocking_fixture()) == body_of(blocking_fixture())


def test_render_with_real_prompt_context():
    """The renderer reads the ``ContextData`` ``build_prompt`` really produces."""
    from prompt import build_prompt
    from tests.helpers import prompt_inputs as pi

    inputs = pi.inputs()
    prompt = build_prompt(inputs, max_context_tokens=150_000, max_diff_lines=2000, nonce=pi.NONCE)
    assert not isinstance(prompt, OverBudget)
    fx = {
        "validation": validation(),
        "context": prompt.context,
        "diff": inputs.diff,
        "verifier": inputs.verifier,
    }
    body = body_of(fx, rubric_version=prompt.rubric_version)
    assert body.startswith("<!-- code-review-agent:v1 ")
    assert "**Context:** " in body
    assert f"rubric v{prompt.rubric_version}" in body


def test_context_variant_helper_is_used():
    """``with_context`` keeps other fixture parts."""
    fx = with_context(blocking_fixture(), issue_numbers=(9,))
    assert context_line(body_of(fx)).startswith("**Context:** issue #9 · ")


def test_run_link_non_string_inputs_give_no_link():
    assert render.run_link(None, RUN_ID) is None  # type: ignore[arg-type]
    assert render.run_link(PANEL, 7) is None  # type: ignore[arg-type]


def test_verifier_parsed_state_without_context_or_rows():
    fx = clear_fixture()
    fx["verifier"] = None
    fx["context"] = context_data(verifier_state=REPORT_PARSED)
    assert "### Verifier\n\n- No Critical Unintended drift." in body_of(fx)


def test_context_line_malformed_issue_note_ref_is_neutralized():
    line = _ctx_line(notes=(BlockNote("issue", "#1 @x <b>", "omitted", "budget"),))
    assert f"issue #{ZW}1 @{ZW}x &lt;b&gt; omitted (budget)" in line
    line = _ctx_line(notes=(BlockNote("issue", None, "omitted", "budget"),))
    assert "issue (unknown) omitted (budget)" in line


# ---------------------------------------------------------------------------
# QA follow-ups (planner extras on QA residuals 4 and 5, S-213 carry)
# ---------------------------------------------------------------------------

HUGE = "x" * 20_000


def test_every_rendered_field_is_length_bounded():
    """QA residual 4: no single field can grow a line past its fixed cap."""
    from dataclasses import replace

    from validate import CandidateStatus

    c = replace(candidate(1, HUGE), id=HUGE)
    fx = clear_fixture()
    fx["validation"] = validation(
        [
            replace(
                finding("B1", title=HUGE, failure_scenario=HUGE, consequence=HUGE),
                id=HUGE,
                category=HUGE,
            )
        ],
        [replace(finding("S1", title=HUGE, consequence=HUGE, downgraded=HUGE), category=HUGE)],
        [CandidateStatus(c, HUGE, HUGE, True)],
    )
    fx["verifier"] = verifier_ctx(report(REPORT, REPORT_PARSED, candidates=[c]))
    fx["context"] = context_data(
        verifier_state=REPORT_PARSED,
        notes=(BlockNote("issue", "#" + "9" * 20_000, "omitted", "budget"),),
    )
    fx["diff"] = diff_ctx(
        files=(file_diff("w.py", base_withheld=HUGE),),
        name_only=(NameOnlyFile("n.py", "added", HUGE, HUGE),),
    )
    body = body_of(fx, limit=10**9)
    longest = max(len(line) for line in body.split("\n"))
    assert longest <= 3_000, longest  # the longest slot: a 1,500-char scenario
    assert len(context_line(body)) < 1_500


def test_invisible_characters_are_removed_before_the_wrapper_inserts_its_own():
    """QA residual 5: content zero-width and tag characters are dropped."""
    invisible = "​‌‍⁠﻿\U000e0001\U000e0041\U000e007f"
    assert neutralize(f"a{invisible}b") == "ab"
    assert neutralize(f"@{invisible}everyone") == f"@{ZW}everyone"
    assert neutralize(f"www{invisible}.e.x") == f"www{ZW}.e.x"
    assert neutralize("a️b") == "a️b"  # variation selectors are kept
    assert render.code_span(f"p{invisible}@x.py") == f"`p@{ZW}x.py`"
    assert render.code_span(invisible) == "(unknown)"


def test_marker_run_id_is_lowercased():
    """S-213 carry: the marker's run_id compares exactly against the lowercase run id."""
    body = body_of(clear_fixture(), run_id=RUN_ID.upper())
    assert body.startswith(f"<!-- code-review-agent:v1 run={RUN_ID} sha={HEAD} -->\n")


def test_stage5_keeps_every_blocking_one_liner_when_the_list_fits():
    """QA-212-D2: with a huge Verifier section, blocking entries stay whole and counted."""
    fx = clear_fixture()
    cands = [candidate(k, "<" * 1050) for k in range(1, 3000)]
    blocking = [finding(f"B{k}", title=f"t{k}") for k in range(1, 6)]
    fx["validation"] = validation(blocking, [], [status(c, STATUS_CONFIRMED, "r") for c in cands])
    fx["verifier"] = verifier_ctx(report(REPORT, REPORT_PARSED, candidates=cands))
    out = review(fx)
    assert 5 in out.stages and len(out.body) <= MAX_COMMENT_CHARS
    assert "5 more blocking findings are listed by title only:" in out.body
    assert len(re.findall(r"^- \*\*B\d+ · ", out.body, re.M)) == 5
    assert "blocking findings not shown" not in out.body
    assert "### Verifier" in out.body
    assert _counted_candidates(out.body) == 2999  # DR-4: the cut candidates are counted


def test_stage5_helpers_cut_lines_and_trim_blocking():
    """QA-212-D2 helpers: line cuts, and every blocking entry listed or counted."""
    assert render._cut_lines("ab\ncd", 10) == "ab\ncd"
    assert render._cut_lines("ab\ncd", 0) == ""
    assert render._cut_lines("ab\ncd", 3) == "ab"
    assert render._cut_lines("abcdef", 3) == ""
    lines = [f"- **B{k} · c · `p:1`** — t" for k in range(1, 4)]
    whole = render._trim_blocking(lines, 10_000)
    assert "3 more blocking findings are listed by title only:" in whole
    assert "not shown" not in whole
    for room in range(20, len(whole)):
        out = render._trim_blocking(lines, room)
        assert len(out) <= room or out == "### Blocking\n\n3 blocking findings not shown."
        listed = len(re.findall(r"^- \*\*B", out, re.M))
        lead = re.search(r"^(\d+) more blocking", out, re.M)
        assert (int(lead.group(1)) if lead else 0) == listed
        missing = re.search(r"(\d+) (?:more )?blocking findings? not shown", out)
        assert listed + (int(missing.group(1)) if missing else 0) == 3
    none = render._trim_blocking(lines, 20)
    assert none == "### Blocking\n\n3 blocking findings not shown."


# ---------------------------------------------------------------------------
# Verifier follow-ups: DR-4 (count hidden candidates), DR-9 (UTF-16 size)
# ---------------------------------------------------------------------------


def _counted_candidates(body: str) -> int:
    listed = len(re.findall(r"^- \*\*V\d+ \(", body, re.M))
    missing = re.search(r"(\d+) (?:more )?verifier candidates? not shown\.$", body, re.M)
    return listed + (int(missing.group(1)) if missing else 0)


def test_dr4_stage5_counts_the_verifier_candidates_it_cuts():
    """Probe P1: 2,000 unchecked escape-heavy candidates, no findings."""
    fx = clear_fixture()
    cands = [candidate(k, "<" * 1050) for k in range(1, 2001)]
    fx["validation"] = validation([], [], [status(c, STATUS_NOT_CHECKED) for c in cands])
    fx["verifier"] = verifier_ctx(report(REPORT, REPORT_PARSED, candidates=cands))
    out = review(fx)
    assert 5 in out.stages and len(out.body) <= MAX_COMMENT_CHARS
    assert _counted_candidates(out.body) == 2000
    assert re.search(r"^and \d+ more verifier candidates not shown\.$", out.body, re.M)


def test_dr4_dropped_verifier_section_leaves_one_count_line():
    """Probe P2: 40 blocking findings at the maxima crowd out every candidate."""
    fx = clear_fixture()
    blocking = [
        finding(
            f"B{k}",
            file="&" * 400,
            title="&" * 200,
            failure_scenario="&" * 1500,
            consequence="&" * 500,
        )
        for k in range(1, 41)
    ]
    cands = [candidate(k, "&" * 1050) for k in range(1, 51)]
    fx["validation"] = validation(
        blocking, [], [status(c, STATUS_CONFIRMED, "&" * 300) for c in cands]
    )
    fx["verifier"] = verifier_ctx(report(REPORT, REPORT_PARSED, candidates=cands))
    out = review(fx)
    assert len(out.body) <= MAX_COMMENT_CHARS
    assert _counted_candidates(out.body) == 50
    listed = len(re.findall(r"^- \*\*V\d+ \(", out.body, re.M))
    if listed == 0:
        assert re.search(r"^50 verifier candidates not shown\.$", out.body, re.M)


def test_dr9_size_is_the_larger_of_code_points_and_utf16_units():
    assert render.comment_size("ab") == 2
    assert render.comment_size("\U0001f600") == 2  # one code point, two UTF-16 units
    assert render.comment_size("é漢") == 2


def test_dr9_all_emoji_body_stays_under_the_limit_in_utf16_units():
    """Probe P4: emoji text doubles in UTF-16; the limit must hold in either unit."""
    emoji = "\U0001f600"
    fx = clear_fixture()
    fx["validation"] = validation(
        [
            finding(
                f"B{k}", title=emoji * 200, failure_scenario=emoji * 1500, consequence=emoji * 500
            )
            for k in range(1, 41)
        ],
        [finding(f"S{k}", title=emoji * 200, consequence=emoji * 500) for k in range(1, 21)],
    )
    out = review(fx)
    units = len(out.body.encode("utf-16-le")) // 2
    assert units <= MAX_COMMENT_CHARS
    assert out.chars == max(len(out.body), units)
    assert out.truncated
