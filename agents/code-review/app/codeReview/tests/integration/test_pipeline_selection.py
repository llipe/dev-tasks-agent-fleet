"""
PRD v1.4 end to end — context selection, docs-only skip, tiered drops (FR-32–FR-36).

Drives ``main.invoke`` with the S-213 harness. The ``riel`` scenario replays
``llipe/riel#889``: a ``GC-08`` story whose audit file
(``workstream/audit-gift-card-compensation-gc08.md``) follows no dev-tasks name,
so only the selection call can find it. The selection call is the first
Converse request and the review the second; the selection never counts toward
the review's calls, tokens or cost.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from bedrock_adapter import request_tokens
from context.selection import SELECTION_TOOL
from tests.fixtures.bedrock import throttled, tool_use_response
from tests.helpers.github_stub import json_response, text_response
from tests.helpers.pipeline_run import (
    COMMENT_URL,
    HEAD,
    SUPABASE_KEY,
    Harness,
    file_entry,
    review,
)

SPEC = "docs/requirements/prd-gift-cards.md"
AUDIT = "workstream/audit-gift-card-compensation-gc08.md"
FACADE = "modules/offer/src/offer.facade.ts"
CONTRACT = "packages/contracts/src/offer.ts"
GUIDE = "docs/offer-guide.md"

AUDIT_TEXT = """# Audit: gift card compensation (GC-08)

## 3. Drift catalog

| # | Item | Severity | Kind |
|---|------|----------|------|
| 1 | Refund path skips the ledger | Critical | Unintended |
"""


@pytest.fixture
def h(monkeypatch) -> Harness:
    return Harness(monkeypatch)


def _riel(h: Harness, *, tree: bool = True) -> None:
    """The riel#889 shape on the sample harness: two source files and a doc."""
    h.stub.default = text_response("", status=404)
    # Its own branch: the sample's ``issue/41-…`` would link #41 (and its S-001 report).
    h.set_pull(
        body="Implements GC-08.\n\nRefs #889",
        title="GC-08 compensation",
        head={"ref": "feature/gc-08", "sha": HEAD},
    )
    h.set_issue(889, title="GC-08: gift card compensation", labels=[], body="Compensate GC-08.")
    h.set_files(
        [
            file_entry(FACADE, 3, 0, status="added"),
            file_entry(CONTRACT, 2, 0, status="added"),
            file_entry(GUIDE, 1, 0, status="added"),
        ]
    )
    h.set_content(
        FACADE, HEAD, "export const facade = 1;\nexport const a = 2;\nexport const b = 3;\n"
    )
    h.set_content(CONTRACT, HEAD, "export type Offer = {};\nexport type X = {};\n")
    h.set_content(GUIDE, HEAD, "# Guide\n")
    h.set_content(SPEC, HEAD, "# PRD: gift cards\n\nGC-08 compensates the buyer.\n")
    h.set_content(AUDIT, HEAD, AUDIT_TEXT)
    if tree:
        h.set_tree([("docs/README.md", 300), (SPEC, 4000), (AUDIT, 2500), ("src/x.ts", 9)])


def _selection(documents: list[dict[str, Any]], priority: Sequence[int] = ()) -> dict[str, Any]:
    return tool_use_response(
        {"documents": documents, "file_priority": list(priority)},
        name=SELECTION_TOOL,
        usage=(700, 50),
    )


PICKS = [
    {"index": 2, "role": "spec", "reason": "The GC-08 PRD."},
    {"index": 3, "role": "verifier_report", "reason": "The GC-08 audit."},
]


def _context_line(body: str) -> str:
    return next(ln for ln in body.split("\n") if ln.startswith("**Context:** "))


# ---------------------------------------------------------------------------
# riel#889: the selection finds what the rules miss
# ---------------------------------------------------------------------------


def test_selection_brings_the_spec_and_the_audit_into_the_review(h):
    _riel(h)
    h.fake.push(_selection(PICKS, [2, 1]), review())
    result = h.drive()
    assert (result["status"], result["outcome"]) == ("succeeded", "no_findings")
    assert h.fake.calls == 2
    selection_req, review_req = h.fake.requests
    assert selection_req["toolConfig"]["toolChoice"] == {"tool": {"name": SELECTION_TOOL}}
    assert review_req["toolConfig"]["toolChoice"] == {"tool": {"name": "submit_review"}}

    user = h.prompts[-1].user
    assert f"Spec `{SPEC}`:" in user
    assert f"Verifier report `{AUDIT}`, drift section" in user
    assert "Refund path skips the ledger" in user  # V1, the audit's candidate row

    line = _context_line(h.posts()[-1])
    assert "no verifier report" not in h.posts()[-1]
    assert line.endswith(f"selected: spec `{SPEC}`, verifier report `{AUDIT}`")


def test_selection_metrics_are_recorded_apart_from_the_review(h):
    _riel(h)
    h.fake.push(_selection(PICKS), review())
    h.drive()
    m = h.reporter.terminal["metrics"]
    assert m["bedrock_calls"] == 1
    assert (m["input_tokens"], m["output_tokens"]) == (1000, 200)
    assert (m["selection_input_tokens"], m["selection_output_tokens"]) == (700, 50)
    assert m["selection_status"] == "picked"
    assert m["selection_picks"] == 2
    assert m["selection_candidates"] == 3
    # The review's request estimate does not include the selection request.
    assert m["estimated_input_tokens"] == request_tokens(h.fake.requests[1])
    events = [e for e in h.reporter.events() if e["message"] == "context selection done"]
    assert len(events) == 1


def test_the_artifact_records_the_picks(h):
    _riel(h)
    h.fake.push(_selection(PICKS), review())
    h.drive()
    selection = h.reporter.artifacts()[-1]["metadata"]["selection"]
    assert selection["status"] == "picked"
    assert selection["picks"] == [
        {"path": SPEC, "role": "spec", "reason": "The GC-08 PRD."},
        {"path": AUDIT, "role": "verifier_report", "reason": "The GC-08 audit."},
    ]


def test_selection_model_id_is_used_when_set(h, monkeypatch):
    monkeypatch.setenv("SELECTION_MODEL_ID", "us.anthropic.claude-haiku-4-5")
    _riel(h)
    h.fake.push(_selection(PICKS), review())
    h.drive()
    assert h.fake.requests[0]["modelId"] == "us.anthropic.claude-haiku-4-5"
    assert h.fake.requests[1]["modelId"] == h.model_id


def test_the_selection_ranking_orders_full_file_drops(h):
    _riel(h)
    h.fake.push(_selection([], [1, 2, 3]), review())
    h.drive()
    ctx = h.prompts[-1].context
    order = list(ctx.full_files_included) + list(ctx.full_files_dropped)
    assert order == [FACADE, CONTRACT]  # GUIDE is a docs file: diff only (D-67)


# ---------------------------------------------------------------------------
# Fail open (FR-33)
# ---------------------------------------------------------------------------


def test_an_invalid_selection_falls_back_to_the_rules(h):
    _riel(h)
    h.fake.push(tool_use_response({"documents": "everything"}, name=SELECTION_TOOL), review())
    result = h.drive()
    assert result["status"] == "succeeded"
    assert h.fake.calls == 2  # no repair call for the selection
    assert f"Spec `{SPEC}`" not in h.prompts[-1].user
    assert "context selection failed; using rule-based context" in h.reporter.messages("warn")
    assert _context_line(h.posts()[-1]).endswith("selection failed; rule-based context only")
    assert h.reporter.terminal["metrics"]["selection_status"] == "failed"


def test_a_throttled_selection_falls_back_to_the_rules(h):
    _riel(h)
    h.fake.push(throttled(), review())
    result = h.drive()
    assert result["status"] == "succeeded"
    assert h.fake.calls == 2


def test_rules_mode_makes_no_selection_call(h):
    _riel(h)
    h.fake.push(review())
    result = h.drive({"pr_number": 42, "context_selection": "rules"})
    assert result["status"] == "succeeded"
    assert h.fake.calls == 1
    assert _context_line(h.posts()[-1]).endswith("selection off (rules)")


def test_empty_context_folders_make_no_selection_call(h):
    _riel(h)
    h.fake.push(review())
    h.drive({"pr_number": 42, "context_folders": ""})
    assert h.fake.calls == 1
    assert _context_line(h.posts()[-1]).endswith("selection off (no context folders)")


def test_context_folders_limit_the_candidates(h):
    _riel(h)
    h.fake.push(_selection([{"index": 1, "role": "verifier_report", "reason": "r"}]), review())
    h.drive({"pr_number": 42, "context_folders": "workstream"})
    user = h.fake.requests[0]["messages"][0]["content"][0]["text"]
    assert AUDIT in user and SPEC not in user
    assert f"Verifier report `{AUDIT}`" in h.prompts[-1].user


def test_a_tree_read_failure_skips_the_selection(h):
    _riel(h, tree=False)
    h.stub.add(
        ("GET", f"{h.prefix}/git/trees/{HEAD}", (("recursive", "1"),)),
        json_response({"message": "boom"}, status=500),
    )
    h.fake.push(review())
    result = h.drive()
    assert result["status"] == "succeeded"
    assert h.fake.calls == 1
    assert "repository tree unavailable" in h.reporter.messages("warn")
    assert _context_line(h.posts()[-1]).endswith("selection skipped (repository tree unavailable)")


def test_a_truncated_tree_is_used_with_a_warning(h):
    _riel(h)
    h.set_tree([(SPEC, 4000)], truncated=True)
    h.fake.push(_selection([{"index": 1, "role": "spec", "reason": "r"}]), review())
    h.drive()
    assert "repository tree truncated" in h.reporter.messages("warn")
    assert f"Spec `{SPEC}`" in h.prompts[-1].user


def test_a_suffixed_issue_report_is_found_without_the_model(h):
    name = "workstream/fidelity-report-issue-889-gift-card-compensation.md"
    _riel(h)
    h.set_tree([(name, 100)])
    h.set_content(name, HEAD, AUDIT_TEXT)
    h.fake.push(review())
    h.drive({"pr_number": 42, "context_selection": "rules"})
    assert f"Verifier report `{name}`" in h.prompts[-1].user


# ---------------------------------------------------------------------------
# Docs-only PRs (FR-35)
# ---------------------------------------------------------------------------


def test_a_docs_only_pr_gets_a_note_and_no_model_call(h):
    h.set_files([file_entry("docs/a.md"), file_entry("README.md"), file_entry("docs/img/flow.png")])
    result = h.drive()
    assert (result["status"], result["outcome"]) == ("succeeded", "not_applicable")
    assert result["comment_url"] == COMMENT_URL
    assert h.fake.calls == 0
    (body,) = h.posts()
    assert body.startswith("Documentation-only PR: all 3 changed files are documentation")
    assert h.reporter.artifacts() == []
    assert not [c for c in h.stub.calls if "/contents/" in c.path or "/git/trees/" in c.path]


def test_a_shell_script_among_docs_is_reviewed(h):
    h.stub.default = text_response("", status=404)
    h.set_files(
        [file_entry("docs/a.md", status="added"), file_entry("ops/rollback.sh", status="added")]
    )
    h.set_content("docs/a.md", HEAD, "# A\n")
    h.set_content("ops/rollback.sh", HEAD, "#!/bin/sh\nexit 0\n")
    h.fake.push(review(checks=[]))
    result = h.drive({"pr_number": 42, "context_selection": "rules"})
    assert result["status"] == "succeeded"
    assert h.fake.calls == 1
    assert not h.posts()[-1].startswith("Documentation-only PR")


def test_invalid_context_folders_are_invalid_params(h):
    result = h.drive({"pr_number": 42, "context_folders": "../secrets"})
    assert (result["status"], result["error_code"]) == ("failed", "INVALID_PARAMS")
    assert h.posts() == []
    assert h.fake.calls == 0


def test_a_secret_in_a_picked_path_or_reason_is_scrubbed(h):
    leaky = f"docs/{SUPABASE_KEY}.md"
    _riel(h)
    h.set_tree([(leaky, 10)])
    h.set_content(leaky, HEAD, "# Leaky spec\n")
    h.fake.push(
        _selection([{"index": 1, "role": "spec", "reason": f"has {SUPABASE_KEY}"}]), review()
    )
    h.drive()
    body = h.posts()[-1]
    assert SUPABASE_KEY not in body
    assert "selected: spec `docs/***.md`" in body
    meta = h.reporter.artifacts()[-1]["metadata"]
    assert SUPABASE_KEY not in str(meta["selection"])
    assert SUPABASE_KEY not in h.reporter.dump()


def test_more_than_400_candidates_are_capped_with_a_warning(h):
    _riel(h)
    h.set_tree([(f"docs/f{k:04d}.md", 10) for k in range(450)])
    h.fake.push(_selection([]), review())
    h.drive()
    assert "context selection candidates capped" in h.reporter.messages("warn")
    user = h.fake.requests[0]["messages"][0]["content"][0]["text"]
    assert "400. docs/f0399.md" in user and "docs/f0400.md" not in user
