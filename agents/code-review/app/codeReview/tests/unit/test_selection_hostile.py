"""
PRD v1.4 — hostile inputs to the selection, the tree lookups and the tiers.

Every input here is attacker-sized: GitHub's tree holds up to 100,000 entries,
a PR body or issue body is megabytes, a path is thousands of characters, and
the model's output is whatever it sends. Each operation stays linear (bounded
by ``perf_bound``) and bounded in what it emits.
"""

from __future__ import annotations

import contextlib
import time

import pytest

from context.diff import file_tier, is_docs_only
from context.issues import LinkedIssue
from context.selection import (
    MAX_CANDIDATES,
    ChangedFile,
    DocCandidate,
    InvalidFolders,
    SelectionInputs,
    build_candidates,
    build_request,
    parse_context_folders,
    parse_selection,
)
from context.verifier import report_paths, title_story_ids, verifier_candidates
from github_client import GitHubClient, TreeEntry
from tests.helpers.github_stub import StubTransport, text_response
from tests.helpers.perf import perf_bound

HEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d"
TREE_SIZE = 100_000


def _elapsed(fn) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def test_candidates_from_a_full_size_tree_are_linear_and_capped():
    entries = [TreeEntry(f"docs/d{k // 100}/f{k}.md", "blob", k) for k in range(TREE_SIZE)]
    out = []
    assert _elapsed(lambda: out.append(build_candidates(entries, ("docs", "workstream")))) < (
        perf_bound(1.0)
    )
    assert len(out[0].candidates) == MAX_CANDIDATES and out[0].capped


def test_report_lookup_over_a_full_size_tree_is_one_pass():
    tree = [f"workstream/fidelity-report-issue-{k}-s.md" for k in range(TREE_SIZE)]
    issues = [LinkedIssue(n, "AB-1 CD-2 EF-3", (), "", "", False, False) for n in range(1, 6)]
    stub = StubTransport(default=text_response("", status=404))
    client = GitHubClient("ghs_x", "acme", "widgets", 42, transport=stub, sleep=lambda s: None)
    assert _elapsed(
        lambda: verifier_candidates(client, issues, HEAD, tree_paths=iter(tree))
    ) < perf_bound(2.0)
    # 5 issues x (3 story names + 1 issue name), plus at most 3 suffixes each.
    assert len(stub.calls) <= 5 * 4 * (1 + 3)


def test_title_ids_on_a_huge_title():
    title = "AB-1 " * 200_000
    assert _elapsed(lambda: title_story_ids(title)) < perf_bound(1.0)
    assert report_paths(LinkedIssue(1, title, (), "", "", False, False)) == (
        "workstream/fidelity-report-AB-1.md",
        "workstream/fidelity-report-issue-1.md",
    )


@pytest.mark.parametrize(
    "value",
    [
        "a/" * 499 + "a",
        "." * 1000,
        "a," * 499 + "a",
        ("a" * 99 + ",") * 9 + "a" * 99 + "/..",
        " ," * 500,
        "a" * 999 + "/",
    ],
)
def test_context_folders_validation_is_fast_on_adversarial_strings(value):
    def check() -> None:
        with contextlib.suppress(InvalidFolders):
            parse_context_folders(value)

    assert _elapsed(check) < perf_bound(0.1)


def test_parse_selection_with_a_huge_answer_is_linear():
    docs = [{"index": k, "role": "spec", "reason": "r" * 10_000} for k in range(200_000)]
    out = []
    assert _elapsed(
        lambda: out.append(
            parse_selection({"documents": docs, "file_priority": list(range(200_000))}, 400, 300)
        )
    ) < perf_bound(1.0)
    assert len(out[0].documents) == 6
    assert len(out[0].file_priority) == 300


def test_a_deeply_nested_json_answer_is_invalid_not_a_crash():
    from context.selection import SelectionInvalid

    with pytest.raises(SelectionInvalid):
        parse_selection("[" * 100_000 + "]" * 100_000, 1, 1)


def test_request_stays_bounded_whatever_the_inputs():
    huge = "x" * 5_000_000
    long_path = "src/" + "a" * 4096 + ".ts"
    inputs = SelectionInputs(
        pr_title=huge,
        pr_body=huge,
        head_ref=huge,
        issues=tuple(LinkedIssue(n, huge, (), huge, huge, False, False) for n in range(1, 6)),
        changed=tuple(ChangedFile(long_path, 1, 1) for _ in range(3000)),
        candidates=tuple(DocCandidate(k, "docs/" + "b" * 390 + ".md", 1) for k in range(1, 401)),
    )
    out = []
    assert _elapsed(
        lambda: out.append(build_request(inputs, model_id="m", nonce_factory=lambda: "0" * 16))
    ) < perf_bound(2.0)
    text = out[0]["messages"][0]["content"][0]["text"]
    # PR 2,000 + 5 issues x 1,500 tokens, 300 changed files and 400 candidates of
    # at most 300 characters each, plus the wrapper text.
    assert len(text) < 400_000


def test_tiers_and_docs_only_on_hostile_names():
    name = "a" + ".test" * 20_000 + ".py"
    assert _elapsed(lambda: file_tier(name)) < perf_bound(1.0)
    paths = (f"docs/{k}.md" for k in range(1_000_000))
    assert _elapsed(lambda: is_docs_only(paths)) < perf_bound(2.0)
