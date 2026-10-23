"""
S-213 / DF-16 — the "nothing to review" note for a PR with no reviewed file.

A PR whose changed files are all listed by name only (lockfiles, generated,
binary, excluded) is not sent to the model. Rather than going silent, the run
posts this one short note and ends ``succeeded``/``not_applicable`` (pinned in
S-213; the spec is silent, test plan DF-16 / TC-213-30). Same guarantees as the
budget comment: fixed text, neutralized names, the run link, a trailing
newline, never ``/review`` at the start.
"""

from __future__ import annotations

import render
from context.diff import NameOnlyFile
from render import render_nothing_to_review

RUN_ID = "0b7c4e9a-1d2f-4a3b-8c5d-6e7f8091a2b3"
PANEL = "https://dt-agent-fleet-panel.fly.dev"
RUN_URL = f"{PANEL}/runs/{RUN_ID}"


def test_lockfile_only_note():
    names = (
        NameOnlyFile("pnpm-lock.yaml", "modified", "lockfile"),
        NameOnlyFile("uv.lock", "modified", "lockfile"),
    )
    body = render_nothing_to_review(names, run_id=RUN_ID, panel_base_url=PANEL)
    assert body == (
        "Nothing to review: this PR changes only files listed by name (2 files)."
        f" Not reviewed. [run]({RUN_URL})\n"
        "\nListed by name only: `pnpm-lock.yaml` (lockfile), `uv.lock` (lockfile).\n"
    )


def test_no_files_note_is_one_line():
    body = render_nothing_to_review((), run_id=RUN_ID, panel_base_url=PANEL)
    assert body == f"Nothing to review: this PR changes no files. Not reviewed. [run]({RUN_URL})\n"


def test_names_are_neutralized_and_capped():
    names = [NameOnlyFile(f"@u{k}<b>`x`.min.js", "added", "generated") for k in range(30)]
    body = render_nothing_to_review(names, run_id=RUN_ID, panel_base_url=PANEL)
    assert body.count("(generated)") == render.LIST_MAX
    assert "and 10 more" in body
    assert "<b>" not in body
    assert "@u" not in body.replace("@​u", "")
    assert body.endswith("\n")
    assert not body.startswith("/review")


def test_bad_link_inputs_never_inject_markdown():
    body = render_nothing_to_review((), run_id="not-a-uuid", panel_base_url="javascript:x")
    assert "(run link unavailable)" in body
