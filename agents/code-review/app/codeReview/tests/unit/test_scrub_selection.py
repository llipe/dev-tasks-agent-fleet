"""
PRD v1.4 FR-34 — the context selection is scrubbed before it is rendered or recorded.

``pipeline._scrub_selection`` scrubs each pick's path and the model's reason,
and the ranked changed-file paths, before ``render_review`` and the
``audit_report`` metadata see them. The posted body and the metadata are
scrubbed again afterwards, but that back-stop matches whole secrets only: the
context line cuts a path at ``render.CONTEXT_PATH_MAX`` characters while a
candidate path may be up to ``CANDIDATE_PATH_MAX_CHARS``, so a secret that
straddles the cut leaves a prefix no later scrub can recognize. Scrubbing the
selection first is what keeps that prefix out of the comment.
"""

from __future__ import annotations

from context.selection import (
    CANDIDATE_PATH_MAX_CHARS,
    ROLE_SPEC,
    ROLE_VERIFIER,
    STATUS_PICKED,
    Pick,
    Selection,
)
from pipeline import _scrub_selection
from render import CONTEXT_PATH_MAX, render_review
from tests.helpers.render_inputs import HEAD, MODEL, PANEL, RUN_ID, clear_fixture

SECRET = "ghs_SELECTIONtokenSENTINEL0123456789"
PREFIX = SECRET[:20]


def _selection(path: str, reason: str = "r", ranked: tuple[str, ...] = ()) -> Selection:
    return Selection(
        status=STATUS_PICKED,
        picks=(Pick(path, ROLE_SPEC, reason),),
        file_priority=ranked,
        candidates=1,
    )


def _body(selection: Selection) -> str:
    fx = clear_fixture()
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
        selection=selection,
    ).body


def test_no_selection_stays_none():
    assert _scrub_selection(None, [SECRET]) is None


def test_paths_reasons_and_ranking_are_scrubbed():
    selection = Selection(
        status=STATUS_PICKED,
        picks=(
            Pick(f"docs/{SECRET}.md", ROLE_SPEC, f"names {SECRET}"),
            Pick("workstream/audit.md", ROLE_VERIFIER, "clean"),
        ),
        file_priority=(f"src/{SECRET}.py", "src/app.py"),
        discarded=1,
        candidates=7,
    )
    clean = _scrub_selection(selection, [SECRET])
    assert clean is not None
    assert SECRET not in repr(clean)
    assert [p.path for p in clean.picks] == ["docs/***.md", "workstream/audit.md"]
    assert [p.reason for p in clean.picks] == ["names ***", "clean"]
    assert [p.role for p in clean.picks] == [ROLE_SPEC, ROLE_VERIFIER]
    assert clean.file_priority == ("src/***.py", "src/app.py")
    # Everything that is not model or repository text is kept as is.
    assert (clean.status, clean.discarded, clean.candidates) == (STATUS_PICKED, 1, 7)


def test_a_secret_hidden_by_invisible_characters_is_scrubbed():
    hidden = SECRET[:10] + "​" + SECRET[10:]
    clean = _scrub_selection(_selection(f"docs/{hidden}.md", f"see {hidden}"), [SECRET])
    assert clean is not None
    assert SECRET not in clean.picks[0].path.replace("​", "")
    assert SECRET not in clean.picks[0].reason.replace("​", "")


def test_a_secret_cut_by_the_context_line_leaves_no_prefix():
    # The secret starts a few characters before the context line's path cut.
    lead = "docs/" + "a" * (CONTEXT_PATH_MAX - 5 - 8) + "/"
    path = f"{lead}{SECRET}.md"
    assert len(path) <= CANDIDATE_PATH_MAX_CHARS  # a path the selection can pick
    assert len(lead) < CONTEXT_PATH_MAX < len(lead) + len(SECRET)

    # Unscrubbed, the cut leaves a prefix a whole-secret scrub cannot match.
    raw = _body(_selection(path))
    assert SECRET not in raw and SECRET[:6] in raw

    clean = _scrub_selection(_selection(path), [SECRET])
    assert clean is not None
    body = _body(clean)
    assert SECRET[:6] not in body
    assert PREFIX not in body
