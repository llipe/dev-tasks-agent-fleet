"""
PRD v1.4 FR-34 and FR-35 — the selection on the context line, the docs-only note.

The context line names every document the selection call picked, with its
role, neutralized like any repository path, and says when selection was off,
skipped or failed. Without a selection (older callers) the line is unchanged.
"""

from __future__ import annotations

from context.selection import (
    ROLE_SPEC,
    ROLE_VERIFIER,
    SKIP_NO_CANDIDATES,
    SKIP_NO_FOLDERS,
    SKIP_NO_TIME,
    SKIP_RULES,
    SKIP_TREE_UNAVAILABLE,
    STATUS_EMPTY,
    STATUS_FAILED,
    STATUS_PICKED,
    STATUS_SKIPPED,
    Pick,
    Selection,
)
from render import render_docs_only, render_review
from tests.helpers.render_inputs import HEAD, MODEL, PANEL, RUN_ID, RUN_URL, clear_fixture


def _line(selection: Selection | None) -> str:
    fx = clear_fixture()
    body = render_review(
        fx["validation"],
        context=fx["context"],
        diff=fx["diff"],
        verifier=fx["verifier"],
        run_id=RUN_ID,
        head_sha=HEAD,
        model_id=MODEL,
        rubric_version="1",
        panel_base_url=PANEL,
        selection=selection,
    ).body
    lines = [ln for ln in body.split("\n") if ln.startswith("**Context:** ")]
    assert len(lines) == 1
    return lines[0]


def _sel(status: str, reason: str | None = None, picks=()) -> Selection:
    return Selection(status=status, reason=reason, picks=tuple(picks), file_priority=())


def test_without_a_selection_the_line_is_unchanged():
    assert _line(None) == "**Context:** no linked issues · no spec found"


def test_picks_are_named_with_their_role():
    line = _line(
        _sel(
            STATUS_PICKED,
            picks=[
                Pick("docs/requirements/prd-gift-cards.md", ROLE_SPEC, "r"),
                Pick("workstream/audit-gift-card-compensation-gc08.md", ROLE_VERIFIER, "r"),
            ],
        )
    )
    assert line.endswith(
        " · selected: spec `docs/requirements/prd-gift-cards.md`,"
        " verifier report `workstream/audit-gift-card-compensation-gc08.md`"
    )


def test_hostile_pick_paths_are_neutralized():
    line = _line(_sel(STATUS_PICKED, picks=[Pick("docs/`x`<!-- @me #1.md", ROLE_SPEC, "")]))
    assert "<!--" not in line
    assert "spec `docs/x&lt;!-- @​me #1.md`" in line


def test_the_model_reason_is_never_rendered():
    line = _line(_sel(STATUS_PICKED, picks=[Pick("docs/a.md", ROLE_SPEC, "REASON-SENTINEL")]))
    assert "REASON-SENTINEL" not in line


def test_nothing_picked():
    assert _line(_sel(STATUS_EMPTY)).endswith(" · selection picked no documents")


def test_failed():
    assert _line(_sel(STATUS_FAILED)).endswith(" · selection failed; rule-based context only")


def test_skipped_reasons():
    cases = {
        SKIP_RULES: "selection off (rules)",
        SKIP_NO_FOLDERS: "selection off (no context folders)",
        SKIP_NO_CANDIDATES: "selection skipped (no candidate documents)",
        SKIP_NO_TIME: "selection skipped (no time left)",
        SKIP_TREE_UNAVAILABLE: "selection skipped (repository tree unavailable)",
    }
    for reason, text in cases.items():
        assert _line(_sel(STATUS_SKIPPED, reason)).endswith(" · " + text)


def test_docs_only_note():
    body = render_docs_only(3, run_id=RUN_ID, panel_base_url=PANEL)
    assert body == (
        "Documentation-only PR: all 3 changed files are documentation or images."
        f" Not reviewed. [run]({RUN_URL})\n"
    )
    assert "\n" not in body.rstrip("\n")
    assert render_docs_only(1, run_id=RUN_ID, panel_base_url=PANEL).startswith(
        "Documentation-only PR: the 1 changed file is documentation or an image."
    )
