"""
S-213 end to end — ``main.invoke`` through the pipeline on recorded fixtures (Layer 2).

Test plan §4.10, TC-213-01..TC-213-31 (prompt capture, TC-213-21..24, is in
``test_pipeline_prompt_capture.py``; the deadline and heartbeat, TC-213-17/18,
in ``tests/unit/test_deadline.py``). Each test drives the real entrypoint with
the harness in ``tests/helpers/pipeline_run.py``: the sample PR
``acme/widgets#42`` (three reviewed files, a lockfile, a binary; issue #41 is
``Story S-001`` with a drift report holding one ``Critical``+``Unintended`` row
V1 and one ``Minor`` row; #40 is a PR) and a scripted fake Converse.

Pinned here (decisions the spec leaves open, recorded in the S-213 PR body):

- the budget, token-budget and nothing-to-review paths post in a ``post`` step,
  write no ``audit_report`` (EC-21) and still record ``runs.metrics``;
- a PR with no reviewed file (lockfile-only, DF-16) gets one short
  "nothing to review" comment, ``succeeded``/``not_applicable``, no fetch and
  no Converse call;
- ``COMMENT_POST_FAILED`` posts one failure comment unless the POST raised
  ``GitHubPermissionDenied``; a rate-limited 403 still gets one (S-205 D4);
- ``estimated_input_tokens`` is the estimate of every request actually sent,
  the same scope as ``input_tokens`` (S-210 DR-11).
"""

from __future__ import annotations

import json
import signal

import pytest

import pipeline
import signal_backstop
from tests.fixtures.bedrock import (
    access_denied,
    service_unavailable,
    text_response,
    throttled,
    tool_use_response,
)
from tests.helpers.github_stub import StubResponse, json_response
from tests.helpers.pipeline_run import (
    COMMENT_URL,
    COMMENTS_PATH,
    COMPARE_PATH,
    FILES_PATH,
    HEAD,
    MERGE_BASE,
    MOVED_HEAD,
    OTHER_RUN_ID,
    PREFIX,
    PULL_PATH,
    RUN_ID,
    RUN_URL,
    SUPABASE_KEY,
    TOKEN,
    V1_CONFIRMED,
    V1_NOT_REPRODUCED,
    Harness,
    blocking,
    file_entry,
    marker,
    pull_json,
    review,
    suggestion,
)

STEPS = ["load_pr", "context", "review", "validate", "post"]
CI_FRAGMENTS = ("/check-runs", "/check-suites", "/statuses", "/status", "/actions")


@pytest.fixture
def h(monkeypatch) -> Harness:
    return Harness(monkeypatch)


def _failure(code: str) -> str:
    return f"Code review failed (`{code}`). [run]({RUN_URL})\n"


# ---------------------------------------------------------------------------
# AC1 steps, AC5 outcomes (TC-213-01, TC-213-02)
# ---------------------------------------------------------------------------


def test_steps(h):
    """TC-213-01: a clear review runs the five steps in order, one comment."""
    h.fake.push(review())
    result = h.drive()

    assert result == {
        "status": "succeeded",
        "outcome": "no_findings",
        "verdict": "clear",
        "comment_url": COMMENT_URL,
        "error_code": None,
    }
    assert h.reporter.step_keys() == STEPS
    assert h.reporter.step_statuses() == ["succeeded"] * 5
    for key in STEPS:
        infos = [e for e in h.reporter.events_for(key) if e["level"] == "info"]
        assert any(e["data"] for e in infos), f"step {key} has no info event with counts"
    terminal = h.reporter.terminal
    assert (terminal["status"], terminal["outcome"]) == ("succeeded", "no_findings")
    assert len(h.posts()) == 1
    assert h.posts()[0].startswith(f"<!-- code-review-agent:v1 run={RUN_ID} sha={HEAD} -->")
    assert "## Code review: **clear** · `9f2c4e1`" in h.posts()[0]
    assert h.fake.calls == 1
    assert h.backstops == 1


def test_blocking_review(h):
    """TC-213-02: a blocking finding inside the diff -> needs_review."""
    h.fake.push(review([blocking()]))
    result = h.drive()

    assert result["status"] == "succeeded"
    assert result["outcome"] == "needs_review"
    assert result["verdict"] == "blocking"
    assert result["comment_url"] == COMMENT_URL
    body = h.posts()[0]
    assert "## Code review: **blocking**" in body
    assert "**B1 · correctness ·" in body
    assert h.reporter.terminal["outcome"] == "needs_review"


# ---------------------------------------------------------------------------
# AC2 states, drafts, no CI (TC-213-03..05)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pull",
    [
        {"state": "closed", "merged": False},
        {"state": "closed", "merged": True},
    ],
    ids=["closed", "merged"],
)
def test_closed_pr(h, pull):
    """TC-213-03, EC-18: a PR closed (or merged) before load_pr is not applicable."""
    h.set_pull(**pull)
    result = h.drive()

    assert (result["status"], result["outcome"]) == ("succeeded", "not_applicable")
    assert result["error_code"] is None
    assert h.posts() == []
    assert h.fake.calls == 0
    assert h.reporter.step_keys() == ["load_pr"]
    assert h.reporter.terminal["outcome"] == "not_applicable"
    assert h.reporter.terminal.get("error_code") is None
    assert [c.path for c in h.stub.calls] == [PULL_PATH]


def test_not_a_pr_is_not_applicable(h):
    """TC-213-03, EC-23: a 404 on GET pull is not_applicable, never GITHUB_NOT_FOUND."""
    h.stub.add(("GET", PULL_PATH), json_response({"message": "Not Found"}, status=404))
    result = h.drive()

    assert (result["status"], result["outcome"]) == ("succeeded", "not_applicable")
    assert result["error_code"] is None
    assert "GITHUB_NOT_FOUND" not in h.reporter.dump()
    assert h.posts() == []
    assert h.fake.calls == 0


def test_draft_pr(h):
    """TC-213-04: a draft PR is reviewed normally."""
    h.set_pull(draft=True)
    h.fake.push(review())
    result = h.drive()
    assert result["outcome"] == "no_findings"
    assert len(h.posts()) == 1


def test_no_ci_read(h):
    """TC-213-05 (FR-4): no CI status path is ever requested."""
    h.fake.push(review([blocking()]))
    h.drive()
    for call in h.stub.calls:
        assert not any(f in call.path for f in CI_FRAGMENTS), call.path
    assert {c.method for c in h.stub.calls} == {"GET", "POST"}


# ---------------------------------------------------------------------------
# AC3 SHA pinned (TC-213-06, EC-17)
# ---------------------------------------------------------------------------


def test_sha_pinned(h):
    """A force-push after load_pr: every read and every output stays on the captured SHA."""
    h.stub.add(
        ("GET", PULL_PATH),
        [json_response(pull_json()), json_response(pull_json(head_sha=MOVED_HEAD))],
    )
    h.fake.push(review([blocking()]))
    h.drive()

    assert len(h.calls("GET", PULL_PATH)) == 1, "the PR is read once, at load_pr"
    refs = {c.params["ref"] for c in h.content_calls()}
    assert refs <= {HEAD, MERGE_BASE}
    assert HEAD in refs
    assert MOVED_HEAD not in json.dumps([c.url for c in h.stub.calls])
    body = h.posts()[0]
    assert marker(body) == (RUN_ID, HEAD)
    assert f"`{HEAD[:7]}`" in body
    meta = h.reporter.artifacts()[0]["metadata"]
    assert meta["head_sha"] == HEAD
    assert h.prompts[0].context.max_context_tokens == 150_000
    assert HEAD in h.prompts[0].user


# ---------------------------------------------------------------------------
# AC4 budget (TC-213-07, TC-213-08, TC-213-30)
# ---------------------------------------------------------------------------


def _assert_budget_path(h: Harness, result: dict) -> str:
    assert (result["status"], result["outcome"]) == ("succeeded", "not_applicable")
    assert result["verdict"] is None
    assert result["comment_url"] == COMMENT_URL
    assert h.fake.calls == 0
    assert h.reporter.step_keys() == ["load_pr", "context", "post"]
    assert h.reporter.artifacts() == [], "EC-21 pinned: no audit_report on the budget path"
    metrics = h.reporter.terminal["metrics"]
    assert metrics["comment_chars"] == len(h.posts()[0])
    assert metrics["wall_clock_ms"] >= 0
    posts = h.posts()
    assert len(posts) == 1
    assert not posts[0].startswith("/review")
    return posts[0]


def test_budget_path(h):
    """TC-213-07 (AC-5): 2,001 reviewed lines -> budget comment, no fetch, no Converse."""
    h.set_files([file_entry("src/app.py", additions=2001), file_entry("pnpm-lock.yaml", 50, 50)])
    result = h.drive()

    body = _assert_budget_path(h, result)
    assert "changes 2001 lines in 1 file, over the review budget of 2000 lines" in body
    assert RUN_URL in body
    assert "`pnpm-lock.yaml` (lockfile)" in body
    assert h.content_calls() == []
    assert h.calls("GET", COMPARE_PATH) == []
    assert h.reporter.terminal["metrics"]["changed_lines"] == 2001


def test_budget_path_exactly_at_the_limit_is_reviewed(h):
    """EC-02: exactly max_diff_lines is reviewed."""
    h.set_files([file_entry("src/app.py", additions=2000)])
    h.fake.push(review(checks=[]))
    result = h.drive()
    assert result["status"] == "succeeded"
    assert result["outcome"] in {"no_findings", "needs_review"}
    assert h.fake.calls == 1


def test_token_budget_path(h):
    """TC-213-08: lines under the limit, but the expanded diff is over the token budget."""
    big = "".join(f"value_{i} = {i}  # {'x' * 40}\n" for i in range(2_500))
    h.set_content("src/app.py", HEAD, big)
    result = h.drive({"pr_number": 42, "max_context_tokens": 20_000})

    body = _assert_budget_path(h, result)
    assert "over the context budget of 20000 tokens" in body
    assert h.prompts == [], "the sink never sees an over-budget prompt"


def test_lockfile_only_pr(h):
    """TC-213-30 / DF-16 pinned: nothing to review -> one short note, not_applicable."""
    h.set_files([file_entry("pnpm-lock.yaml", 10, 10), file_entry("uv.lock", 3, 1)])
    result = h.drive()

    body = _assert_budget_path(h, result)
    assert "Nothing to review" in body
    assert "`pnpm-lock.yaml` (lockfile)" in body and "`uv.lock` (lockfile)" in body
    assert RUN_URL in body
    assert h.content_calls() == []
    assert h.calls("GET", COMPARE_PATH) == []
    assert [c.path for c in h.stub.calls if c.method == "GET"] == [PULL_PATH, FILES_PATH]


# ---------------------------------------------------------------------------
# AC6 artifact and metrics (TC-213-10..12, TC-213-31)
# ---------------------------------------------------------------------------

SPEC_5_3_KEYS = {
    "input_tokens",
    "output_tokens",
    "estimated_input_tokens",
    "cost_usd",
    "bedrock_ms",
    "wall_clock_ms",
    "output_mode",
    "repair_calls",
    "reasoning_effort_applied",
    "context_tokens",
    "findings_by_severity",
    "findings_by_category",
    "downgraded",
    "dropped",
    "suggestions_capped",
    "verifier_candidates",
    "verifier_confirmed",
    "comment_chars",
    "comment_truncated",
}
CONTEXT_TOKEN_BLOCKS = {
    "instructions",
    "diff",
    "full_files",
    "issues",
    "spec",
    "verifier",
    "conventions",
}


def test_artifact_metrics(h):
    """TC-213-10, TC-213-12: one audit_report per spec §5.2 and every §5.3 metric."""
    h.fake.push(review([blocking(), suggestion(rank=2, line_start=3, line_end=3)]))
    h.drive()

    artifacts = h.reporter.artifacts()
    assert len(artifacts) == 1
    art = artifacts[0]
    assert art["type"] == "audit_report"
    assert art["url"] == COMMENT_URL
    assert art["title"] == "Code review #42 @ 9f2c4e1: blocking"
    meta = art["metadata"]
    assert meta["schema_version"] == 1
    assert meta["pr_number"] == 42
    assert meta["head_sha"] == HEAD
    assert meta["base_sha"] == "3a5c7e9b1d3f5a7c9e1b3d5f7a9c1e3b5d7f9a1c"
    assert meta["verdict"] == "blocking"
    assert meta["model_id"] == "us.openai.gpt-5-6-sol-v1:0"
    assert meta["output_mode"] == "forced_schema"
    assert meta["reasoning_effort"] == "high"
    assert meta["reasoning_effort_applied"] is True
    assert meta["rubric_version"] == "1"
    ctx = meta["context"]
    assert ctx["issues"] == [41]
    assert ctx["spec"] is None
    assert ctx["spec_trimmed"] is False
    assert ctx["fidelity_reports"] == ["workstream/fidelity-report-S-001.md"]
    assert ctx["full_files_included"] == 3
    assert ctx["full_files_dropped"] == 0
    assert ctx["listed_by_name"] == ["pnpm-lock.yaml", "assets/logo.png"]
    assert [f["id"] for f in meta["findings"]] == ["B1", "S1"]
    assert meta["findings"][0]["downgraded"] is False
    assert set(meta["findings"][0]) >= {
        "severity",
        "category",
        "file",
        "line_start",
        "line_end",
        "title",
        "failure_scenario",
        "consequence",
        "rank",
        "id",
        "downgraded",
    }
    assert meta["verifier"] == [
        {
            "candidate_id": "V1",
            "report": "workstream/fidelity-report-S-001.md",
            "row": meta["verifier"][0]["row"],
            "status": "not_reproduced",
            "reason": "The report predates the change.",
        }
    ]
    assert "Critical" in meta["verifier"][0]["row"]
    assert meta["dropped"] == []

    metrics = h.reporter.terminal["metrics"]
    assert SPEC_5_3_KEYS <= set(metrics)
    assert metrics["input_tokens"] == 1000 and metrics["output_tokens"] == 200
    assert metrics["cost_usd"] is None  # price env vars unset
    assert metrics["output_mode"] == "forced_schema"
    assert metrics["repair_calls"] == 0
    assert metrics["reasoning_effort_applied"] is True
    assert set(metrics["context_tokens"]) >= CONTEXT_TOKEN_BLOCKS
    assert all(isinstance(v, int) and v >= 0 for v in metrics["context_tokens"].values())
    assert metrics["context_tokens"]["full_files"] > 0
    assert metrics["findings_by_severity"]["blocking"] == 1
    assert metrics["findings_by_severity"]["suggestion"] == 1
    assert metrics["verifier_candidates"] == 1
    assert metrics["verifier_confirmed"] == 0
    assert metrics["comment_chars"] == len(h.posts()[0])
    assert metrics["comment_truncated"] is False
    # DR-11 pinned: the estimate of every request actually sent (one call here).
    first = h.prompts[0]
    assert metrics["estimated_input_tokens"] >= first.tokens - 2_212
    assert metrics["estimated_input_tokens"] > 0
    assert metrics["estimated_first_call_tokens"] == first.tokens
    assert metrics["bedrock_calls"] == 1


def test_estimated_input_tokens_sums_every_call(h):
    """DR-11: a repair run counts both requests, like input_tokens."""
    h.fake.push(
        tool_use_response({"findings": "not a list", "verifier_checks": []}, usage=(900, 50)),
        review(),
    )
    h.drive()
    metrics = h.reporter.terminal["metrics"]
    assert metrics["bedrock_calls"] == 2
    assert metrics["repair_calls"] == 1
    assert metrics["input_tokens"] == 1900
    assert metrics["estimated_input_tokens"] >= metrics["estimated_first_call_tokens"]


def test_secrets_scrubbed(h):
    """TC-213-11: the token and the Supabase key never leave in a comment, artifact or event."""
    h.set_content(
        "src/app.py",
        HEAD,
        f'import sys\nSIZES = ("s", "m", "l")  # {TOKEN}\n\n\ndef main():\n    return 0\n',
    )
    h.set_issue(41, body=f"Add widget sizes. key={SUPABASE_KEY}\n", title="Story S-001: sizes")
    report = (
        "# Fidelity\n\n## 3. Drift catalog\n\n| ID | Drift | Impact | Intent |\n| --- | --- | --- | --- |\n"
        f"| DR-1 | leaks {SUPABASE_KEY} here | Critical | Unintended |\n"
    )
    h.set_content("workstream/fidelity-report-S-001.md", HEAD, report)
    h.fake.push(
        review(
            [
                blocking(
                    title=f"Token {TOKEN} in code", failure_scenario=f"Key {SUPABASE_KEY} leaks"
                )
            ],
            checks=[V1_CONFIRMED],
        )
    )
    h.drive()

    body = h.posts()[0]
    blob = body + h.reporter.dump()
    for secret in (TOKEN, SUPABASE_KEY):
        core = secret.replace("_", "").replace("-", "")[4:24]
        assert secret not in blob
        assert core not in blob.replace("\\", "").replace("_", "").replace("-", ""), secret
    assert "\\*\\*\\*" in body, "the redaction shows, escaped as text"
    meta = h.reporter.artifacts()[0]["metadata"]
    assert "***" in meta["findings"][0]["title"]
    assert "***" in meta["verifier"][0]["row"]
    # The secrets did reach Bedrock (accepted residual risk, PRD §17), not the outputs.
    assert TOKEN in h.prompts[0].user


def test_run_events_carry_no_prompt_or_model_text(h):
    """TC-213-29: no PR body, diff, model or secret text in run_events; each <= 8 KB."""
    h.set_pull(body="Closes #41\n\nPRBODY-SENTINEL-77")
    h.set_content("src/app.py", HEAD, 'import sys\nSIZES = ("DIFF-SENTINEL-88",)\n')
    h.fake.push(review([blocking(title="MODEL-SENTINEL-99", consequence="MODEL-SENTINEL-99")]))
    h.drive()

    events = h.reporter.events()
    assert events
    text = json.dumps(events)
    for sentinel in ("PRBODY-SENTINEL-77", "DIFF-SENTINEL-88", "MODEL-SENTINEL-99", TOKEN):
        assert sentinel not in text
    for e in events:
        assert len(e["message"].encode()) <= 8192 + 32
        assert "src/app.py" not in json.dumps(e), "no reviewed path in run_events"


def test_context_step_logs_block_token_counts(h):
    """S-209 carry-forward: per-block token counts in the context step's run_event."""
    h.fake.push(review())
    h.drive()
    data = [e["data"] for e in h.reporter.events_for("context") if "block_tokens" in e["data"]]
    assert len(data) == 1
    blocks = data[0]["block_tokens"]
    assert blocks == h.prompts[0].context.block_tokens


def test_failed_run_records_partial_metrics(h):
    """TC-213-31: a failed run after Converse keeps tokens and bedrock_ms, writes no artifact."""
    bad = tool_use_response({"findings": "nope", "verifier_checks": []}, usage=(700, 30))
    h.fake.push(bad, bad)
    result = h.drive()

    assert result["error_code"] == "MODEL_OUTPUT_INVALID"
    metrics = h.reporter.terminal["metrics"]
    assert metrics["input_tokens"] == 1400
    assert metrics["output_tokens"] == 60
    assert metrics["bedrock_calls"] == 2
    assert "bedrock_ms" in metrics and "wall_clock_ms" in metrics
    assert h.reporter.artifacts() == []


# ---------------------------------------------------------------------------
# AC5 verifier end to end (TC-213-25..27)
# ---------------------------------------------------------------------------


def test_ac7_confirmed_candidate_blocks_with_no_findings(h):
    """TC-213-25: V1 confirmed -> blocking; only V1 listed, the Minor row counted as other drift."""
    h.fake.push(review([], checks=[V1_CONFIRMED]))
    result = h.drive()

    assert result["verdict"] == "blocking"
    assert result["outcome"] == "needs_review"
    body = h.posts()[0]
    assert "### Blocking" not in body
    assert "**V1 (confirmed)**" in body
    assert "omits" in body and "which the spec lists" in body
    assert "informally" not in body, "the Minor row is not restated"
    assert "Other drift: 1 item" in body
    assert h.reporter.terminal["metrics"]["verifier_confirmed"] == 1


def test_ac7_not_reproduced_candidate_is_listed_and_clear(h):
    """TC-213-26: not_reproduced -> clear, listed with its reason."""
    h.fake.push(review([], checks=[V1_NOT_REPRODUCED]))
    result = h.drive()
    assert result["verdict"] == "clear"
    body = h.posts()[0]
    assert "**V1 (not reproduced)**" in body
    assert "The report predates the change." in body


def test_ac7_omitted_candidate_blocks_as_not_checked(h):
    """TC-213-26: a candidate the model omits counts, "not checked by the model"."""
    h.fake.push(review([], checks=[]))
    result = h.drive()
    assert result["verdict"] == "blocking"
    body = h.posts()[0]
    assert "**V1 (unchecked)**" in body
    assert "not checked by the model" in body


def test_ac9_downgrade_and_drop(h):
    """TC-213-27 (PRD AC-9): blank scenario and outside-diff downgrade; blank consequence drops."""
    h.fake.push(
        review(
            [
                blocking(failure_scenario="", rank=1, title="Blank scenario"),
                blocking(line_start=50, line_end=50, rank=2, title="Outside the hunks"),
                suggestion(consequence="", rank=3, title="No consequence"),
            ]
        )
    )
    result = h.drive()

    assert result["verdict"] == "clear"
    body = h.posts()[0]
    assert "**S1 ·" in body and "**S2 ·" in body
    assert "**B1" not in body
    assert "No consequence" not in body
    metrics = h.reporter.terminal["metrics"]
    assert sum(metrics["downgraded"].values()) == 2
    assert metrics["downgraded"] == {"outside_diff": 1, "no_scenario": 1}
    assert metrics["dropped"]["no_consequence"] == 1
    meta = h.reporter.artifacts()[0]["metadata"]
    assert meta["dropped"] == [{"reason": "no_consequence", "title": "No consequence"}]
    assert {f["downgraded"] for f in meta["findings"]} == {"no_scenario", "outside_diff"}


# ---------------------------------------------------------------------------
# AC7 errors and the failure comment (TC-213-13..16, TC-213-28)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("script", "code"),
    [
        (throttled(), "BEDROCK_ERROR"),
        (service_unavailable(), "BEDROCK_ERROR"),
        (access_denied(), "BEDROCK_ACCESS_DENIED"),
    ],
    ids=["throttled", "5xx", "access-denied"],
)
def test_errors_bedrock(h, script, code):
    """TC-213-13 (AC-11): a Bedrock error ends failed with one failure comment."""
    h.fake.push(script)
    result = h.drive()

    assert result["status"] == "failed"
    assert result["error_code"] == code
    assert result["comment_url"] is None
    assert h.posts() == [_failure(code)]
    terminal = h.reporter.terminal
    assert (terminal["status"], terminal["error_code"]) == ("failed", code)
    assert h.reporter.step_statuses()[-1] == "failed"
    assert any(code in e["message"] for e in h.reporter.events() if e["level"] == "error")
    assert h.reporter.artifacts() == []


def _github_403() -> StubResponse:
    return json_response({"message": "Resource not accessible by integration"}, status=403)


def _github_500() -> StubResponse:
    return json_response({"message": "boom"}, status=500)


@pytest.mark.parametrize(
    ("setup", "code", "failure_comment"),
    [
        (
            lambda h: h.stub.add(
                ("GET", FILES_PATH, (("page", "1"), ("per_page", "100"))), _github_403()
            ),
            "GITHUB_PERMISSION_DENIED",
            True,
        ),
        (lambda h: h.stub.add(("GET", COMPARE_PATH), _github_500()), "GITHUB_API_ERROR", True),
        (lambda h: h.stub.add(("GET", PULL_PATH), _github_500()), "GITHUB_API_ERROR", True),
        (
            lambda h: h.fake.push(text_response("no tool"), text_response("still none")),
            "MODEL_OUTPUT_INVALID",
            True,
        ),
        (lambda h: h.fake.push(throttled()), "BEDROCK_ERROR", True),
    ],
    ids=["403-files", "500-compare", "500-pull", "model-invalid", "bedrock"],
)
def test_errors_table(h, setup, code, failure_comment):
    """TC-213-14: each §13 code ends failed with that code; the comment follows the table."""
    setup(h)
    result = h.drive()

    assert result["status"] == "failed"
    assert result["error_code"] == code
    assert h.reporter.terminal["error_code"] == code
    assert h.posts() == ([_failure(code)] if failure_comment else [])


def test_errors_internal_error_from_validate(h, monkeypatch):
    """S-211 (2): an exception from validate_result is INTERNAL_ERROR, with a comment."""

    def boom(*a, **k):
        raise ValueError("validator defect")

    monkeypatch.setattr(pipeline, "validate_result", boom)
    h.fake.push(review())
    result = h.drive()
    assert result["error_code"] == "INTERNAL_ERROR"
    assert h.posts() == [_failure("INTERNAL_ERROR")]
    assert h.reporter.step_keys()[-1] == "validate"


def test_errors_invalid_params_no_comment_no_github(h):
    """TC-213-14: INVALID_PARAMS posts nothing and calls nothing."""
    result = h.drive({"pr_number": 0})
    assert result["error_code"] == "INVALID_PARAMS"
    assert h.stub.calls == []
    assert h.token_resolutions == []


def test_errors_credentials_unavailable(h, monkeypatch):
    """No token: the failure comment cannot be posted; the run still ends with its code."""
    from credentials import CredentialError

    def no_token(org):
        raise CredentialError("GITHUB_PERMISSION_DENIED", "exchange refused (HTTP 403)")

    monkeypatch.setattr(h, "resolve_token", no_token)
    result = h.drive()
    assert result["error_code"] == "GITHUB_PERMISSION_DENIED"
    assert h.stub.calls == []
    assert any("failure comment" in m for m in h.reporter.messages("error"))


def test_errors_comment_post_failed(h):
    """D-36: the review POST fails with 500 -> COMMENT_POST_FAILED and one failure comment."""
    h.stub.add(("POST", COMMENTS_PATH), [_github_500(), _created()])
    h.fake.push(review([blocking()]))
    result = h.drive()

    assert result["status"] == "failed"
    assert result["error_code"] == "COMMENT_POST_FAILED"
    posts = h.posts()
    assert len(posts) == 2, "the review POST (not retried) and one failure comment"
    assert posts[0].startswith("<!-- code-review-agent:v1")
    assert posts[1] == _failure("COMMENT_POST_FAILED")
    assert h.reporter.artifacts() == []


@pytest.mark.parametrize("status", [401, 403])
def test_errors_comment_post_denied_posts_nothing_more(h, status):
    """D-36: after a 401/403 on the review POST, no failure comment."""
    h.stub.add(("POST", COMMENTS_PATH), json_response({"message": "denied"}, status=status))
    h.fake.push(review())
    result = h.drive()
    assert result["error_code"] == "COMMENT_POST_FAILED"
    assert len(h.posts()) == 1


def test_errors_comment_post_rate_limited_403_posts_failure_comment(h):
    """S-205 D4 pinned: a rate-limited 403 is a GitHubApiError, so one failure comment."""
    limited = json_response(
        {"message": "You have exceeded a secondary rate limit"},
        status=403,
        headers={"x-ratelimit-remaining": "0"},
    )
    h.stub.add(("POST", COMMENTS_PATH), [limited, _created()])
    h.fake.push(review())
    result = h.drive()
    assert result["error_code"] == "COMMENT_POST_FAILED"
    assert h.posts()[1] == _failure("COMMENT_POST_FAILED")


def test_errors_failure_comment_failure_is_logged(h):
    """TC-213-16: the failure comment POST fails -> error event, original code kept."""
    h.stub.add(("POST", COMMENTS_PATH), _github_500())
    h.fake.push(throttled())
    result = h.drive()

    assert result["error_code"] == "BEDROCK_ERROR"
    assert h.reporter.terminal["error_code"] == "BEDROCK_ERROR"
    assert len(h.posts()) == 1
    assert any("failure comment not posted" in m for m in h.reporter.messages("error"))


def test_errors_failure_comment_failure_after_comment_post_failed(h):
    h.stub.add(("POST", COMMENTS_PATH), _github_500())
    h.fake.push(review())
    result = h.drive()
    assert result["error_code"] == "COMMENT_POST_FAILED"
    assert len(h.posts()) == 2
    assert any("failure comment not posted" in m for m in h.reporter.messages("error"))


def test_issue_403_note(h):
    """TC-213-28: a 403 on GET issue skips it with a warn; the review proceeds."""
    h.stub.add(("GET", f"{PREFIX}/issues/41"), _github_403())
    h.fake.push(review([], checks=[]))
    result = h.drive()

    assert result["status"] == "succeeded"
    assert "issues unavailable (permission)" in h.posts()[0]
    permission = [
        e
        for e in h.reporter.events()
        if e["level"] == "warn" and e["data"].get("reason") == "permission"
    ]
    assert len(permission) == 1
    assert permission[0]["data"]["issue"] == 41


def test_budget_comment_post_failure_is_comment_post_failed(h):
    h.set_files([file_entry("src/app.py", additions=5000)])
    h.stub.add(("POST", COMMENTS_PATH), [_github_500(), _created()])
    result = h.drive()
    assert result["error_code"] == "COMMENT_POST_FAILED"
    assert h.posts()[1] == _failure("COMMENT_POST_FAILED")


# ---------------------------------------------------------------------------
# SIGTERM during post (TC-213-19, EC-20)
# ---------------------------------------------------------------------------


class _SigtermOnPost:
    """Delivers a real SIGTERM to this process when the review comment is posted."""

    def __init__(self, inner):
        self.inner = inner

    def request(self, method, url, **kw):
        if method == "POST":
            import os

            os.kill(os.getpid(), signal.SIGTERM)
        return self.inner.request(method, url, **kw)


def test_sigterm_during_post_is_recorded_by_the_backstop(h, monkeypatch):
    """The real backstop marks the run failed; no failure comment from the dying process."""
    import dataclasses
    import functools

    import main
    from github_client import GitHubClient

    previous = signal.getsignal(signal.SIGTERM)

    class Killed(BaseException):
        pass

    def fake_raise(signum):
        raise Killed()

    monkeypatch.setattr(signal_backstop.signal, "raise_signal", fake_raise)
    monkeypatch.setattr(
        main, "install_termination_backstop", signal_backstop.install_termination_backstop
    )
    transport = _SigtermOnPost(h.stub)
    deps = h.deps
    monkeypatch.setattr(
        h,
        "deps",
        lambda: dataclasses.replace(
            deps(),
            make_github=functools.partial(GitHubClient, transport=transport, sleep=lambda s: None),
        ),
    )
    h.fake.push(review([blocking()]))
    try:
        with pytest.raises(Killed):
            h.drive()
    finally:
        signal.signal(signal.SIGTERM, previous)

    terminal = h.reporter.terminal
    assert terminal["status"] == "failed"
    assert terminal["error_code"] == "SIGNAL_TERMINATION"
    assert len(h.posts()) == 0, "the signal lands before the POST is sent"
    assert TOKEN not in h.reporter.dump()
    statuses = [p["status"] for p in h.reporter.run_patches()]
    assert statuses.count("failed") == 1


# ---------------------------------------------------------------------------
# AC9 a new comment per /review (TC-213-20, EC-19)
# ---------------------------------------------------------------------------


def test_new_comment_each_run(h):
    """Two invocations -> two POSTs, never a PATCH or DELETE, distinct run IDs in the markers."""
    h.fake.push(review(), review([blocking()]))
    h.drive(run_id=RUN_ID)
    h.drive(run_id=OTHER_RUN_ID)

    posts = h.posts()
    assert len(posts) == 2
    assert {c.method for c in h.stub.calls} == {"GET", "POST"}
    assert [marker(p) for p in posts] == [(RUN_ID, HEAD), (OTHER_RUN_ID, HEAD)]
    assert not any(c.path.startswith(f"{PREFIX}/issues/comments") for c in h.stub.calls)
    assert h.calls("GET", COMMENTS_PATH) == [], "earlier comments are never read"


def _created() -> StubResponse:
    return json_response(
        {
            "id": 2000002,
            "html_url": "https://github.com/acme/widgets/pull/42#issuecomment-2000002",
            "body": "x",
        },
        status=201,
    )
