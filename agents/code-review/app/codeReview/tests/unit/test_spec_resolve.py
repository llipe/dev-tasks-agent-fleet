"""
S-207 AC4 — spec resolution (TC-207-11..16, CT-12; spec §8.3 step 3, D-24).

Per issue, first hit wins: (a) the first ``workstream/specification-*.md``
path in the (checklist-stripped) body; (b) title ``[PRD-<name>]``; (c) label
``prd:<name>``; (b) and (c) map to ``workstream/specification-prd-<name>.md``.
Each is read at ``head_sha``; a 404 falls through to the next rule. Specs are
deduped across issues and each path is fetched at most once.
"""

from __future__ import annotations

import pytest

from context.conventions import spec_path_for_prd
from context.issues import LinkedIssue, fetch_issues
from context.spec import ResolvedSpec, SpecContext, resolve_specs, spec_candidates
from github_client import GitHubClient, GitHubPermissionDenied
from tests.helpers.github_stub import StubTransport, json_response, text_response

HEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d"
CONTENTS = "/repos/acme/widgets/contents/"
BIG = 150_000


def _issue(
    number: int = 1, *, title: str = "An issue", body: str = "", labels: tuple[str, ...] = ()
) -> LinkedIssue:
    return LinkedIssue(
        number=number,
        title=title,
        labels=labels,
        body=body,
        stripped_body=body,
        checklist_stripped=False,
        truncated=False,
    )


def _client(stub: StubTransport) -> GitHubClient:
    return GitHubClient("ghs_test", "acme", "widgets", 42, transport=stub, sleep=lambda _s: None)


def _stub(found: dict[str, str], missing: tuple[str, ...] = ()) -> StubTransport:
    routes: dict[tuple, object] = {
        ("GET", CONTENTS + path): text_response(text) for path, text in found.items()
    }
    for path in missing:
        routes[("GET", CONTENTS + path)] = json_response({"message": "Not Found"}, 404)
    return StubTransport(routes)


def _resolve(stub: StubTransport, *issues: LinkedIssue, warn=None) -> SpecContext:
    return resolve_specs(
        _client(stub), issues, HEAD, reviewed_paths=(), max_context_tokens=BIG, warn=warn
    )


def _content_paths(stub: StubTransport) -> list[str]:
    return [c.path.removeprefix(CONTENTS) for c in stub.calls]


# -- TC-207-11..13: each rule ------------------------------------------------


def test_rule_a_explicit_path_in_the_body_is_read_at_head_sha():
    stub = _stub({"workstream/specification-prd-x.md": "# X\n"})
    ctx = _resolve(stub, _issue(body="See workstream/specification-prd-x.md for detail."))
    assert ctx.spec == ResolvedSpec(
        path="workstream/specification-prd-x.md",
        text="# X\n",
        trimmed=False,
        truncated=False,
        tokens=2,
        issue=1,
    )
    assert stub.calls[0].params == {"ref": HEAD}


def test_rule_a_does_not_require_the_prd_prefix():
    assert spec_candidates(_issue(body="workstream/specification-legacy.md")) == (
        "workstream/specification-legacy.md",
    )


def test_rule_b_prd_title_maps_to_the_prd_spec():
    """AC-6: the #315 title shape resolves the webhook-triggers spec."""
    stub = _stub({"workstream/specification-prd-webhook-triggers.md": "# W\n"})
    title = "[PRD-webhook-triggers] Story S-170: pure routing engine + safe condition language"
    ctx = _resolve(stub, _issue(title=title))
    assert ctx.spec is not None
    assert ctx.spec.path == "workstream/specification-prd-webhook-triggers.md"


def test_rule_c_prd_label_maps_to_the_prd_spec():
    stub = _stub({"workstream/specification-prd-code-review-agent.md": "# C\n"})
    ctx = _resolve(stub, _issue(labels=("story", "prd:code-review-agent", "size:M")))
    assert ctx.spec is not None
    assert ctx.spec.path == "workstream/specification-prd-code-review-agent.md"


def test_candidates_are_in_rule_order_and_deduped():
    issue = _issue(
        title="[PRD-a] Story S-1: x",
        body="workstream/specification-z.md then workstream/specification-y.md",
        labels=("prd:b", "prd:a", "prd:c"),
    )
    assert spec_candidates(issue) == (
        "workstream/specification-z.md",
        "workstream/specification-prd-a.md",
        "workstream/specification-prd-b.md",
    )


def test_spec_path_for_prd():
    assert spec_path_for_prd("x") == "workstream/specification-prd-x.md"


# -- TC-207-14: fall-through and none ----------------------------------------


def test_rule_a_404_falls_through_to_rule_b():
    stub = _stub(
        {"workstream/specification-prd-b.md": "# B\n"},
        missing=("workstream/specification-gone.md",),
    )
    events: list[tuple[str, dict]] = []
    ctx = _resolve(
        stub,
        _issue(title="[PRD-b] x", body="workstream/specification-gone.md"),
        warn=lambda m, **d: events.append((m, d)),
    )
    assert ctx.spec is not None and ctx.spec.path == "workstream/specification-prd-b.md"
    assert ctx.misses == ("workstream/specification-gone.md",)
    assert events == [("spec not found", {"path": "workstream/specification-gone.md"})]


def test_rule_b_404_falls_through_to_a_label_hit():
    stub = _stub(
        {"workstream/specification-prd-lab.md": "# L\n"},
        missing=("workstream/specification-prd-tit.md",),
    )
    ctx = _resolve(stub, _issue(title="[PRD-tit] x", labels=("prd:lab",)))
    assert ctx.spec is not None and ctx.spec.path == "workstream/specification-prd-lab.md"
    assert _content_paths(stub) == [
        "workstream/specification-prd-tit.md",
        "workstream/specification-prd-lab.md",
    ]


def test_all_rules_404_is_no_spec():
    stub = _stub(
        {},
        missing=(
            "workstream/specification-a.md",
            "workstream/specification-prd-b.md",
            "workstream/specification-prd-c.md",
        ),
    )
    ctx = _resolve(
        stub, _issue(title="[PRD-b] x", body="workstream/specification-a.md", labels=("prd:c",))
    )
    assert ctx.spec is None and ctx.specs == ()
    assert len(ctx.misses) == 3


def test_no_linked_issue_is_no_spec_and_no_request():
    stub = StubTransport()
    ctx = _resolve(stub)
    assert ctx.spec is None
    assert stub.calls == []


def test_issue_without_any_rule_is_no_spec():
    stub = StubTransport()
    ctx = _resolve(stub, _issue(title="fix: a bug", labels=("bug",)))
    assert ctx.spec is None
    assert stub.calls == []


def test_spec_permission_error_propagates():
    """Only the issue GET degrades on 403 (spec §13); a spec 403 fails the run."""
    stub = StubTransport(
        {("GET", CONTENTS + "workstream/specification-prd-x.md"): json_response({}, 403)}
    )
    with pytest.raises(GitHubPermissionDenied):
        _resolve(stub, _issue(title="[PRD-x] y"))


# -- TC-207-15: several issues (DF-20 pinned) --------------------------------


def test_two_issues_with_the_same_spec_fetch_and_include_it_once():
    stub = _stub({"workstream/specification-prd-x.md": "# X\n"})
    ctx = _resolve(stub, _issue(1, title="[PRD-x] a"), _issue(2, labels=("prd:x",)))
    assert [s.path for s in ctx.specs] == ["workstream/specification-prd-x.md"]
    assert ctx.specs[0].issue == 1
    assert len(stub.calls) == 1


def test_a_404_is_not_fetched_twice_across_issues():
    stub = _stub(
        {"workstream/specification-prd-y.md": "# Y\n"},
        missing=("workstream/specification-prd-x.md",),
    )
    ctx = _resolve(
        stub, _issue(1, title="[PRD-x] a"), _issue(2, title="[PRD-x] b", labels=("prd:y",))
    )
    assert [s.path for s in ctx.specs] == ["workstream/specification-prd-y.md"]
    assert _content_paths(stub) == [
        "workstream/specification-prd-x.md",
        "workstream/specification-prd-y.md",
    ]
    assert ctx.misses == ("workstream/specification-prd-x.md",)


def test_two_different_specs_are_both_kept_in_issue_order():
    """DF-20 pinned: both specs, each within an equal share of the 30% cap."""
    stub = _stub(
        {
            "workstream/specification-prd-a.md": "# A\n",
            "workstream/specification-prd-b.md": "# B\n",
        }
    )
    ctx = _resolve(stub, _issue(1, title="[PRD-a] x"), _issue(2, title="[PRD-b] y"))
    assert [(s.path, s.issue) for s in ctx.specs] == [
        ("workstream/specification-prd-a.md", 1),
        ("workstream/specification-prd-b.md", 2),
    ]
    assert ctx.spec == ctx.specs[0]


# -- TC-207-16: path hardening (SN-04) ---------------------------------------


@pytest.mark.parametrize(
    "issue",
    [
        _issue(title="[PRD-../../etc] x"),
        _issue(title="[PRD-a/b] x"),
        _issue(title="[PRD-] x"),
        _issue(body="workstream/specification-../../x.md"),
        _issue(body="workstream/specification-/x.md"),
        _issue(labels=("prd:../../etc",)),
        _issue(labels=("prd:a/b",)),
        _issue(labels=("prd:x y",)),
    ],
)
def test_hostile_names_yield_no_candidate(issue):
    assert spec_candidates(issue) == ()


def test_query_in_a_body_path_is_not_part_of_the_request():
    stub = _stub({"workstream/specification-x.md": "# X\n"})
    _resolve(stub, _issue(body="workstream/specification-x.md?ref=evil#frag"))
    (call,) = stub.calls
    assert call.path == CONTENTS + "workstream/specification-x.md"
    assert call.params == {"ref": HEAD}


def test_every_request_stays_under_workstream_specification():
    hostile = _issue(
        title="[PRD-..] t",
        body="workstream/specification-...md workstream/specification-%2e%2e.md",
        labels=("prd:.",),
    )
    stub = StubTransport(default=json_response({"message": "Not Found"}, 404))
    _resolve(stub, hostile)
    assert stub.calls
    for call in stub.calls:
        rest = call.path.removeprefix(CONTENTS)
        assert rest.startswith("workstream/specification-") and rest.endswith(".md")
        assert rest.count("/") == 1
        assert call.params == {"ref": HEAD}


# -- CT-12: dev-tasks issue conventions --------------------------------------


@pytest.mark.parametrize(
    ("title", "labels", "expected"),
    [
        ("[PRD-x] Story S-1: t", (), ("workstream/specification-prd-x.md",)),
        ("Story S-1: t", ("prd:x",), ("workstream/specification-prd-x.md",)),
        ("[prd-x] Story S-1: t", (), ()),  # lowercase prefix: no match (case-sensitive)
        ("Re: [PRD-x] t", (), ()),  # prefix must start the title
        ("[PRD-x] t", ("type:feature", "story"), ("workstream/specification-prd-x.md",)),
        ("t", ("PRD:x", "prd-x", "xprd:y"), ()),
    ],
)
def test_ct12_title_and_label_conventions(title, labels, expected):
    assert spec_candidates(_issue(title=title, labels=labels)) == expected


def test_resolution_uses_the_fetched_issue():
    """End to end through ``fetch_issues``: the checklist-stripped issue resolves."""
    issue_json = {
        "number": 3,
        "title": "[PRD-x] Story S-3: t",
        "body": "Intent.\n## Task Checklist\n- workstream/specification-prd-no.md\n",
        "labels": [],
    }
    stub = _stub({"workstream/specification-prd-x.md": "# X\n"})
    stub.add(("GET", "/repos/acme/widgets/issues/3"), json_response(issue_json))
    client = _client(stub)
    ctx = resolve_specs(
        client, fetch_issues(client, (3,)).issues, HEAD, reviewed_paths=(), max_context_tokens=BIG
    )
    assert ctx.spec is not None and ctx.spec.path == "workstream/specification-prd-x.md"
