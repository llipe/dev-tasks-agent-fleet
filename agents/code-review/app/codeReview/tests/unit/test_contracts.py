"""
CT-05 (S-205, S-206) — GitHub response consumer contract.

The client reads only the fields spec §6.2 names and normalizes them into typed
results. Each contract gets a valid case (the recorded ``sample-pr`` fixtures),
a missing-field case, a type-mismatch case, and an extra-field case.
S-206 extends this module for the files/diff consumer. S-210 adds CT-08, the
``submit_review`` output schema (spec §6.3), shared with S-211.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from findings_schema import CATEGORIES, SUBMIT_REVIEW_SCHEMA, SchemaViolation, validate_review
from github_client import GitHubApiError, GitHubClient
from tests.helpers.github_stub import StubTransport, fixture_json, json_response

ORG, REPO, PR = "acme", "widgets", 42
R = f"/repos/{ORG}/{REPO}"
HEAD = "9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b1d"
BASE = "3a5c7e9b1d3f5a7c9e1b3d5f7a9c1e3b5d7f9a1c"


def _client(route: tuple, body: object) -> GitHubClient:
    stub = StubTransport({route: json_response(body)})
    return GitHubClient(
        "ghs_contract", ORG, REPO, PR, transport=stub, sleep=lambda _s: None, clock=lambda: 0.0
    )


PULL = ("GET", f"{R}/pulls/42")
FILES = ("GET", f"{R}/pulls/42/files")
COMPARE = ("GET", f"{R}/compare/{BASE}...{HEAD}")
ISSUE = ("GET", f"{R}/issues/41")


def pull_body() -> dict:
    return copy.deepcopy(fixture_json("sample-pr", "pull.json"))


def issue_body() -> dict:
    return copy.deepcopy(fixture_json("sample-pr", "issue_41.json"))


# --- pull ---------------------------------------------------------------


def test_pull_valid_fixture():
    pull = _client(PULL, pull_body()).get_pull()
    assert (pull.state, pull.merged, pull.draft) == ("open", False, False)
    assert (pull.head_sha, pull.base_sha) == (HEAD, BASE)


def test_pull_null_body_is_empty_string():
    body = pull_body()
    body["body"] = None
    assert _client(PULL, body).get_pull().body == ""


def test_pull_missing_body_is_empty_string():
    body = pull_body()
    del body["body"]
    assert _client(PULL, body).get_pull().body == ""


def test_pull_missing_draft_defaults_false():
    body = pull_body()
    del body["draft"]
    assert _client(PULL, body).get_pull().draft is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["head"].pop("sha"),
        lambda b: b["base"].pop("sha"),
        lambda b: b.pop("head"),
        lambda b: b.pop("state"),
        lambda b: b.pop("merged"),
        lambda b: b["head"].pop("ref"),
    ],
)
def test_pull_missing_required_field_is_api_error(mutate):
    body = pull_body()
    mutate(body)
    with pytest.raises(GitHubApiError):
        _client(PULL, body).get_pull()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.__setitem__("merged", "false"),
        lambda b: b.__setitem__("draft", 0),
        lambda b: b.__setitem__("head", "abc"),
        lambda b: b["head"].__setitem__("sha", 123),
        lambda b: b.__setitem__("title", None),
        lambda b: b.__setitem__("body", 5),
    ],
)
def test_pull_type_mismatch_is_api_error(mutate):
    body = pull_body()
    mutate(body)
    with pytest.raises(GitHubApiError):
        _client(PULL, body).get_pull()


def test_pull_whole_body_not_an_object_is_api_error():
    with pytest.raises(GitHubApiError):
        _client(PULL, ["not", "an", "object"]).get_pull()


def test_pull_extra_fields_ignored():
    body = pull_body()
    body["future_field"] = {"x": 1}
    body["head"]["extra"] = True
    assert _client(PULL, body).get_pull().head_sha == HEAD


# --- files --------------------------------------------------------------


def test_files_valid_fixture():
    files = _client(FILES, fixture_json("sample-pr", "pull_files_page1.json")).list_pull_files()
    assert [f.status for f in files.files] == ["modified", "added", "renamed", "modified", "added"]


def test_files_missing_patch_is_none_and_extra_keys_ignored():
    body = [{"filename": "a", "status": "added", "additions": 0, "deletions": 0, "x": 1}]
    (f,) = _client(FILES, body).list_pull_files().files
    assert f.patch is None
    assert f.previous_filename is None


@pytest.mark.parametrize(
    "item",
    [
        {"status": "added", "additions": 0, "deletions": 0},
        {"filename": "a", "additions": 0, "deletions": 0},
        {"filename": "a", "status": "added", "deletions": 0},
        {"filename": "a", "status": "added", "additions": "1", "deletions": 0},
        {"filename": "a", "status": "added", "additions": True, "deletions": 0},
        {"filename": 7, "status": "added", "additions": 0, "deletions": 0},
        {"filename": "a", "status": "added", "additions": 0, "deletions": 0, "patch": 1},
        "not-an-object",
    ],
)
def test_files_bad_item_is_api_error(item):
    with pytest.raises(GitHubApiError):
        _client(FILES, [item]).list_pull_files()


# --- compare ------------------------------------------------------------


def test_compare_valid_fixture():
    cmp = _client(COMPARE, fixture_json("sample-pr", "compare.json")).compare(BASE, HEAD)
    assert cmp.merge_base_sha == "7e1d3c5b9a8f6e4d2c0b1a3f5e7d9c8b6a4f2e0d"


@pytest.mark.parametrize(
    "body",
    [
        {"status": "ahead"},
        {"merge_base_commit": None},
        {"merge_base_commit": {}},
        {"merge_base_commit": {"sha": 5}},
        {"merge_base_commit": "abc"},
    ],
)
def test_compare_missing_merge_base_is_api_error_not_key_error(body):
    with pytest.raises(GitHubApiError) as exc_info:
        _client(COMPARE, body).compare(BASE, HEAD)
    assert exc_info.value.code == "GITHUB_API_ERROR"


# --- issue --------------------------------------------------------------


def test_issue_valid_fixture():
    issue = _client(ISSUE, issue_body()).get_issue(41)
    assert issue.title.startswith("[PRD-widgets]")
    assert issue.labels == ("prd:widgets", "type:feature")
    assert not issue.is_pull_request


def test_issue_null_body_is_empty_string():
    body = issue_body()
    body["body"] = None
    assert _client(ISSUE, body).get_issue(41).body == ""


def test_issue_labels_as_strings_are_tolerated():
    body = issue_body()
    body["labels"] = ["prd:widgets", {"name": "bug"}, 7, {"no_name": 1}, None]
    assert _client(ISSUE, body).get_issue(41).labels == ("prd:widgets", "bug")


@pytest.mark.parametrize("labels", [None, "prd:x", 5, {"name": "x"}])
def test_issue_labels_wrong_container_is_empty(labels):
    body = issue_body()
    body["labels"] = labels
    assert _client(ISSUE, body).get_issue(41).labels == ()


def test_issue_missing_labels_is_empty():
    body = issue_body()
    del body["labels"]
    assert _client(ISSUE, body).get_issue(41).labels == ()


def test_issue_pull_request_key_marks_pr_even_when_null_valued():
    body = issue_body()
    body["pull_request"] = {"url": "x"}
    assert _client(ISSUE, body).get_issue(41).is_pull_request


@pytest.mark.parametrize("mutate", [lambda b: b.pop("title"), lambda b: b.__setitem__("title", 1)])
def test_issue_bad_title_is_api_error(mutate):
    body = issue_body()
    mutate(body)
    with pytest.raises(GitHubApiError):
        _client(ISSUE, body).get_issue(41)


def test_issue_extra_fields_ignored():
    body = issue_body()
    body["reactions"] = {"+1": 3}
    assert _client(ISSUE, body).get_issue(41).number == 41


# ---------------------------------------------------------------------------
# CT-08 (S-210, S-211) — the ``submit_review`` output schema
# ---------------------------------------------------------------------------

_SPEC = (
    Path(__file__).resolve().parents[6] / "workstream" / "specification-prd-code-review-agent.md"
)


def _finding(**overrides) -> dict:
    out = {
        "severity": "suggestion",
        "category": "maintainability",
        "file": "src/app.py",
        "line_start": 3,
        "line_end": 4,
        "title": "t",
        "failure_scenario": "",
        "consequence": "c",
        "rank": 1,
    }
    out.update(overrides)
    return out


def _review(findings=None, checks=None) -> dict:
    return {
        "findings": [_finding()] if findings is None else findings,
        "verifier_checks": [] if checks is None else checks,
    }


def test_ct08_constant_equals_spec_6_3_verbatim():
    text = _SPEC.read_text(encoding="utf-8")
    block = text.split("Output schema (`submit_review.inputSchema`):", 1)[1]
    block = block.split("```json\n", 1)[1].split("\n```", 1)[0]
    assert json.loads(block) == SUBMIT_REVIEW_SCHEMA


def test_ct08_minimal_and_full_objects_validate():
    assert validate_review({"findings": [], "verifier_checks": []}) == {
        "findings": [],
        "verifier_checks": [],
    }
    full = _review(
        findings=[
            _finding(
                rank=k + 1,
                severity=("blocking", "suggestion")[k % 2],
                category=CATEGORIES[k % 4],
                file="f" * 400,
                title="t" * 200,
                failure_scenario="s" * 1500,
                consequence="c" * 500,
            )
            for k in range(40)
        ],
        checks=[
            {"candidate_id": "V1", "status": "confirmed", "reason": "r" * 300},
            {"candidate_id": "V20", "status": "not_reproduced", "reason": ""},
        ],
    )
    assert validate_review(full) is full


@pytest.mark.parametrize(
    "value",
    [
        {"verifier_checks": []},
        {"findings": []},
        *[
            _review(findings=[{k: v for k, v in _finding().items() if k != missing}])
            for missing in _finding()
        ],
        _review(checks=[{"candidate_id": "V1", "status": "confirmed"}]),
    ],
)
def test_ct08_missing_required_is_invalid(value):
    with pytest.raises(SchemaViolation) as exc:
        validate_review(value)
    assert exc.value.rule == "required"


@pytest.mark.parametrize(
    ("value", "rule"),
    [
        (_review(findings=[_finding(line_start="3")]), "type"),
        (_review(findings=[_finding(severity="high")]), "enum"),
        (_review(checks=[{"candidate_id": "v1", "status": "confirmed", "reason": ""}]), "pattern"),
        (_review(findings=[_finding(rank=1.0)]), "type"),
        (_review(findings=[_finding(rank=True)]), "type"),
        (_review(findings=[_finding(title=None)]), "type"),
        (_review(findings={"0": _finding()}), "type"),
        (_review(findings=[_finding()] * 41), "maxItems"),
        (_review(findings=[_finding(category="style")]), "enum"),
        (_review(findings=[_finding(line_end=0)]), "minimum"),
    ],
)
def test_ct08_type_and_value_mismatches_are_invalid(value, rule):
    with pytest.raises(SchemaViolation) as exc:
        validate_review(value)
    assert exc.value.rule == rule


@pytest.mark.parametrize(
    "value",
    [
        _review(findings=[{**_finding(), "verdict": "blocking"}]),
        _review(findings=[{**_finding(), "confidence": 0.9}]),
        {**_review(), "verdict": "clear"},
        _review(checks=[{"candidate_id": "V1", "status": "confirmed", "reason": "", "x": 1}]),
    ],
)
def test_ct08_extra_keys_are_invalid(value):
    with pytest.raises(SchemaViolation) as exc:
        validate_review(value)
    assert exc.value.rule == "additional"


def test_ct08_line_end_before_line_start_passes_the_schema():
    """Handled by S-211's location check, not the schema."""
    validate_review(_review(findings=[_finding(line_start=9, line_end=2)]))
