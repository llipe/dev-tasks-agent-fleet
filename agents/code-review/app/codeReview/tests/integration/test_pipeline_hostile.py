"""
S-213 hostile pipeline tests (qa-engineer completion gate, Layer 2).

Attacks the pipeline guarantees the story and spec §8.1, §8.9, §12 and §13
make, through the real ``main.invoke`` and the ``tests/helpers/pipeline_run.py``
harness:

1. A review request never goes silent: an exception injected at every step and
   sub-call ends the run ``failed`` with a §13 code, and the failure comment is
   posted exactly when the §13 table says so. This includes exceptions with no
   ``.code``, exceptions whose ``str`` carries the secrets, ``KeyboardInterrupt``
   and ``SystemExit``, and an exception raised inside the failure path itself.
2. Exactly one review comment per run: never zero on success, never two, never
   an edit, no retry of the review ``POST``.
3. The deadline at every step (including mid-``POST``), workers abandoned at
   the deadline, heartbeats during each long phase, SIGTERM at every step.
4. Secrets never reach run_events, ``error_message``, the artifact, metrics or
   the comment.
5. SHA pinning, 6. the artifact and metrics shape, 7. the state mapping, on
   every outcome path (the seeded property, seed 415002).

Real defects are pinned with ``pytest.mark.xfail(strict=True)`` and a
reproducer: the test asserts the contract, so it turns green (and then fails
the strict xfail) once the defect is fixed.
"""

from __future__ import annotations

import json
import os
import signal
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest
import requests

import agent_reporter
import pipeline
import signal_backstop
from github_client import (
    GitHubApiError,
    GitHubClient,
    GitHubNotFound,
    GitHubPermissionDenied,
)
from render import ERROR_CODES
from tests.helpers.github_stub import StubResponse, json_response
from tests.helpers.pipeline_run import (
    BASE,
    COMMENTS_PATH,
    COMPARE_PATH,
    FILES_PATH,
    HEAD,
    MERGE_BASE,
    PULL_PATH,
    RUN_ID,
    RUN_URL,
    START,
    SUPABASE_KEY,
    TOKEN,
    Harness,
    blocking,
    file_entry,
    review,
)
from tests.helpers.prng import Tactic, tactic_seed

DEADLINE = START + 900 - 60
MARKER = "<!-- code-review-agent:v1 "

SPEC_5_3_KEYS = frozenset(
    {
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
)
SPEC_5_2_KEYS = frozenset(
    {
        "schema_version",
        "pr_number",
        "head_sha",
        "base_sha",
        "verdict",
        "model_id",
        "output_mode",
        "reasoning_effort",
        "reasoning_effort_applied",
        "rubric_version",
        "context",
        "findings",
        "verifier",
        "dropped",
    }
)
SPEC_5_2_CONTEXT_KEYS = frozenset(
    {
        "issues",
        "spec",
        "spec_trimmed",
        "fidelity_reports",
        "full_files_included",
        "full_files_dropped",
        "listed_by_name",
    }
)


@pytest.fixture
def h(monkeypatch) -> Harness:
    return Harness(monkeypatch)


def _failure(code: str) -> str:
    return f"Code review failed (`{code}`). [run]({RUN_URL})\n"


# ---------------------------------------------------------------------------
# Hostile exceptions and injection helpers
# ---------------------------------------------------------------------------


class Hostile(Exception):
    """No ``.code``; ``str`` and ``repr`` both carry both secrets."""

    def __str__(self) -> str:
        return f"boom {TOKEN} {SUPABASE_KEY}"

    def __repr__(self) -> str:
        return f"Hostile({TOKEN!r}, {SUPABASE_KEY!r})"


class Unprintable(Exception):
    """``str`` and ``repr`` raise: nothing may depend on rendering the exception."""

    def __str__(self) -> str:
        raise RuntimeError("no str")

    def __repr__(self) -> str:
        raise RuntimeError("no repr")


def _raiser(exc: BaseException) -> Callable[..., Any]:
    def raise_it(*_a: Any, **_k: Any) -> Any:
        raise exc

    return raise_it


def _first_call_raises(orig: Callable[..., Any], exc: BaseException) -> Callable[..., Any]:
    calls = {"n": 0}

    def wrapped(*a: Any, **k: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise exc
        return orig(*a, **k)

    return wrapped


Inject = Callable[[Harness, pytest.MonkeyPatch, BaseException], None]


def _on_client(name: str, *, first_only: bool = False) -> Inject:
    def inject(h: Harness, mp: pytest.MonkeyPatch, exc: BaseException) -> None:
        orig = getattr(GitHubClient, name)
        mp.setattr(
            GitHubClient, name, _first_call_raises(orig, exc) if first_only else _raiser(exc)
        )

    return inject


def _on_pipeline(name: str) -> Inject:
    def inject(h: Harness, mp: pytest.MonkeyPatch, exc: BaseException) -> None:
        mp.setattr(pipeline, name, _raiser(exc))

    return inject


def _on_harness(name: str) -> Inject:
    def inject(h: Harness, mp: pytest.MonkeyPatch, exc: BaseException) -> None:
        mp.setattr(h, name, _raiser(exc))

    return inject


def _on_step_open(key: str) -> Inject:
    def inject(h: Harness, mp: pytest.MonkeyPatch, exc: BaseException) -> None:
        orig = agent_reporter.RunReporter.step

        def step(self: Any, k: str, title: str | None = None) -> Any:
            if k == key:
                raise exc
            return orig(self, k, title)

        mp.setattr(agent_reporter.RunReporter, "step", step)

    return inject


# (point, step that fails, failure comment expected for a plain exception)
# Every point before the review POST: the run must end failed/INTERNAL_ERROR,
# with zero review comments.
POINTS: dict[str, tuple[Inject, str, bool]] = {
    "token-mint": (_on_harness("resolve_token"), "load_pr", False),  # no token
    "load_pr": (_on_client("get_pull"), "load_pr", True),
    "step-open-context": (_on_step_open("context"), "context", True),
    "files": (_on_client("list_pull_files"), "context", True),
    "classify": (_on_pipeline("classify"), "context", True),
    "check_size": (_on_pipeline("check_size"), "context", True),
    "compare": (_on_client("compare"), "context", True),
    "blob-fetch": (_on_client("get_content_bytes"), "context", True),
    "expanded_diff": (_on_pipeline("expanded_diff"), "context", True),
    "issue-get": (_on_client("get_issue"), "context", True),
    "issues": (_on_pipeline("linked_issues"), "context", True),
    "spec": (_on_pipeline("resolve_specs"), "context", True),
    "dir-listing": (_on_client("list_dir"), "context", True),
    "verifier": (_on_pipeline("verifier_candidates"), "context", True),
    "conventions": (_on_pipeline("repo_conventions"), "context", True),
    "build_prompt": (_on_pipeline("build_prompt"), "context", True),
    "step-open-review": (_on_step_open("review"), "review", True),
    "bedrock-client": (_on_harness("bedrock_factory"), "review", True),
    "review": (_on_pipeline("converse_review"), "review", True),
    "validate": (_on_pipeline("validate_result"), "validate", True),
    "step-open-post": (_on_step_open("post"), "post", True),
    "scrub-validation": (_on_pipeline("_scrub_validation"), "post", True),
    "render": (_on_pipeline("render_review"), "post", True),
    "audit-metadata": (_on_pipeline("audit_metadata"), "post", True),
    "post-non-github-error": (_on_client("post_pr_comment", first_only=True), "post", True),
}


# ---------------------------------------------------------------------------
# Invariants every run must keep
# ---------------------------------------------------------------------------


def _terminals(h: Harness) -> list[dict[str, Any]]:
    return [p for p in h.reporter.run_patches() if "finished_at" in p]


def _review_posts(h: Harness) -> list[str]:
    return [b for b in h.posts() if b.startswith(MARKER)]


def _failure_posts(h: Harness) -> list[str]:
    return [b for b in h.posts() if b.startswith("Code review failed (")]


def _assert_no_secret(h: Harness) -> None:
    blob = h.reporter.dump() + json.dumps(h.posts())
    for secret in (TOKEN, SUPABASE_KEY):
        assert secret not in blob
        assert secret.replace("_", "\\_") not in blob
        assert secret.replace("-", "\\-") not in blob


def _assert_invariants(h: Harness, result: dict[str, Any]) -> dict[str, Any]:
    """What must hold on every run that reached the pipeline, whatever happened."""
    terminals = _terminals(h)
    assert len(terminals) == 1, "exactly one terminal write"
    t = terminals[0]
    assert t["status"] == result["status"]
    assert t.get("outcome") == result["outcome"]
    assert t.get("error_code") == result["error_code"]
    if t["status"] == "failed":
        assert t["error_code"] in ERROR_CODES, t["error_code"]
        assert t["outcome"] == "not_applicable"
    else:
        assert t.get("error_code") is None
    # §5.3: every key on every path, with its "nothing happened" value at worst.
    assert set(t["metrics"]) >= SPEC_5_3_KEYS, SPEC_5_3_KEYS - set(t["metrics"])
    assert t["metrics"]["wall_clock_ms"] >= 0
    # Exactly one review comment on a reviewed success; never two; never an edit.
    reviews, failures = _review_posts(h), _failure_posts(h)
    notes = [b for b in h.posts() if b not in reviews and b not in failures]
    assert len(reviews) <= 1
    assert len(failures) <= 1
    assert len(notes) <= 1, "one budget comment or nothing-to-review note at most"
    assert not (notes and reviews), "a note path never also posts a review"
    if result["status"] == "succeeded" and result["outcome"] == "not_applicable":
        assert len(notes) == (1 if result["comment_url"] else 0)
    if result["outcome"] in ("no_findings", "needs_review"):
        assert len(reviews) == 1 and failures == []
        assert result["comment_url"]
    if result["status"] == "succeeded":
        assert failures == []
    assert {c.method for c in h.stub.calls} <= {"GET", "POST"}
    # Every step that started was finished.
    assert len(h.reporter.step_statuses()) == len(h.reporter.step_keys())
    # SHA pinning: every ref read is the captured head or the merge base.
    refs = {c.params["ref"] for c in h.content_calls() if c.params and "ref" in c.params}
    assert refs <= {HEAD, MERGE_BASE}
    _assert_no_secret(h)
    return t


# ---------------------------------------------------------------------------
# 1. Never silent: an exception at every step and sub-call
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("exc_type", [Hostile, Unprintable], ids=["hostile", "unprintable"])
@pytest.mark.parametrize("point", list(POINTS))
def test_an_exception_at_every_point_ends_failed_with_one_failure_comment(h, point, exc_type):
    inject, step, comment = POINTS[point]
    inject(h, h.monkeypatch, exc_type())
    h.fake.push(review([blocking()]))
    result = h.drive()

    t = _assert_invariants(h, result)
    assert result["status"] == "failed"
    assert result["error_code"] == "INTERNAL_ERROR"
    if point.startswith("step-open-"):
        # The step row was never created; the run's message still names the step.
        assert step not in h.reporter.step_keys()
    else:
        assert h.reporter.step_keys()[-1] == step
        assert h.reporter.step_statuses()[-1] == "failed"
    assert _review_posts(h) == []
    assert h.posts() == ([_failure("INTERNAL_ERROR")] if comment else [])
    assert h.reporter.artifacts() == []
    # The run's message names the class, never the exception text.
    assert t["error_message"] == f"INTERNAL_ERROR in step {step}: {exc_type.__name__}"
    assert "boom" not in h.reporter.dump()
    if not comment:
        assert any("no GitHub token" in m for m in h.reporter.messages("error"))


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (GitHubApiError("x", status=502), "GITHUB_API_ERROR"),
        (GitHubPermissionDenied("x", status=403), "GITHUB_PERMISSION_DENIED"),
        (GitHubNotFound("x", status=404), "GITHUB_API_ERROR"),
        (requests.ConnectionError(TOKEN), "INTERNAL_ERROR"),
    ],
    ids=["5xx", "403", "404-after-load_pr", "raw-requests-error"],
)
@pytest.mark.parametrize("point", ["files", "compare", "blob-fetch", "issue-get", "dir-listing"])
def test_github_errors_in_context_map_to_their_code(h, point, exc, code):
    """A reader that lets a client error through maps it on ``.code`` (§13)."""
    POINTS[point][0](h, h.monkeypatch, exc)
    h.fake.push(review())
    result = h.drive()
    _assert_invariants(h, result)
    if result["status"] == "succeeded":
        # The issue, spec, verifier and conventions readers may absorb a read
        # error (TC-213-28); then the review must still have been posted.
        assert point in {"issue-get", "dir-listing", "blob-fetch"}
        assert len(_review_posts(h)) == 1
        return
    assert result["error_code"] == code
    assert h.posts() == [_failure(code)]


def test_a_failure_comment_that_raises_a_non_github_error_is_logged(h, monkeypatch):
    """D-13: the failure comment is best effort whatever it raises; the code stays."""
    h.stub.add(("GET", COMPARE_PATH), json_response({"message": "x"}, status=500))
    monkeypatch.setattr(GitHubClient, "post_pr_comment", _raiser(Hostile()))
    result = h.drive()
    t = _assert_invariants(h, result)
    assert t["error_code"] == "GITHUB_API_ERROR"
    errors = [e for e in h.reporter.events() if e["message"] == "failure comment not posted"]
    assert len(errors) == 1 and errors[0]["data"]["error"] == "Hostile"


def test_review_post_timeout_is_not_retried(h):
    """No retry re-POSTs the review comment (§9): one review POST, then one failure comment."""
    h.stub.add(
        ("POST", COMMENTS_PATH),
        [requests.Timeout("read timed out"), json_response({"id": 1, "html_url": "u"}, 201)],
    )
    h.fake.push(review([blocking()]))
    result = h.drive()
    _assert_invariants(h, result)
    assert result["error_code"] == "COMMENT_POST_FAILED"
    assert len(_review_posts(h)) == 1
    assert _failure_posts(h) == [_failure("COMMENT_POST_FAILED")]


def test_note_post_timeout_is_not_retried(h):
    h.set_files([file_entry("pnpm-lock.yaml", 10, 10)])
    h.stub.add(
        ("POST", COMMENTS_PATH),
        [requests.Timeout("read timed out"), json_response({"id": 1, "html_url": "u"}, 201)],
    )
    result = h.drive()
    _assert_invariants(h, result)
    assert result["error_code"] == "COMMENT_POST_FAILED"
    assert [b[:17] for b in h.posts()] == ["Nothing to review", "Code review faile"]


def test_an_empty_token_fails_internal_and_posts_nothing(h, monkeypatch):
    """The exchange returns "": the client refuses it, and so does the failure comment."""
    monkeypatch.setattr(h, "resolve_token", lambda org: "")
    result = h.drive()
    t = _assert_invariants(h, result)
    assert t["error_code"] == "INTERNAL_ERROR"
    assert h.stub.calls == []
    errors = [e for e in h.reporter.events() if e["message"] == "failure comment not posted"]
    assert len(errors) == 1 and errors[0]["data"]["error"] == "ValueError"


# ---------------------------------------------------------------------------
# Defect QA-213-01: an exception inside the failure path aborts it
# ---------------------------------------------------------------------------


def _reporter_log_raises_on(monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    orig = agent_reporter.RunReporter.log

    def log(self: Any, msg: str, level: str = "info", **data: Any) -> None:
        if level == "error" and msg.startswith(message):
            raise RuntimeError("reporter write failed")
        orig(self, msg, level, **data)

    monkeypatch.setattr(agent_reporter.RunReporter, "log", log)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-213-01: _fail logs the 'run failed' event before the failure comment; "
        "if that log raises, the failure comment is never attempted and main.invoke "
        "records INTERNAL_ERROR with the raw exception text instead of the original code"
    ),
)
@pytest.mark.parametrize("where", ["run-failed-event", "render_failure", "scrub-forms"])
def test_an_exception_inside_the_failure_path_keeps_the_code_and_the_comment(h, monkeypatch, where):
    """Reproducer: compare returns 500 (GITHUB_API_ERROR), then the failure path breaks."""
    h.stub.add(("GET", COMPARE_PATH), json_response({"message": "x"}, status=500))
    if where == "run-failed-event":
        _reporter_log_raises_on(monkeypatch, "run failed")
    elif where == "render_failure":
        monkeypatch.setattr(pipeline, "render_failure", _raiser(RuntimeError("render")))
    else:
        monkeypatch.setattr(pipeline, "_rendered_forms", _raiser(RuntimeError("forms")))
    result = h.drive()

    assert result["error_code"] == "GITHUB_API_ERROR"
    assert _terminals(h)[0]["error_code"] == "GITHUB_API_ERROR"
    if where == "run-failed-event":
        assert h.posts() == [_failure("GITHUB_API_ERROR")]


def test_a_failing_terminal_write_still_ends_the_run(h, monkeypatch):
    """RunReporter.fail raising inside _fail: main.invoke's fallback still ends the run."""
    h.stub.add(("GET", COMPARE_PATH), json_response({"message": "x"}, status=500))
    orig = agent_reporter.RunReporter.fail
    calls = {"n": 0}

    def fail(self: Any, *a: Any, **k: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("supabase down")
        orig(self, *a, **k)

    monkeypatch.setattr(agent_reporter.RunReporter, "fail", fail)
    result = h.drive()
    assert result["status"] == "failed"
    terminals = _terminals(h)
    assert len(terminals) == 1 and terminals[0]["status"] == "failed"
    assert h.posts() == [_failure("GITHUB_API_ERROR")], "posted before the write failed"
    _assert_no_secret(h)


# ---------------------------------------------------------------------------
# Defect QA-213-02: BaseException escapes every handler
# ---------------------------------------------------------------------------

BASE_POINTS = ["load_pr", "compare", "review", "validate", "render"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-213-02: Pipeline.run and main.invoke catch Exception only; a KeyboardInterrupt "
        "or SystemExit ends the run through RunReporter.__exit__ with error_code "
        "'KeyboardInterrupt'/'SystemExit'/'CancelledError' (not a §13 code) and no failure comment"
    ),
)
@pytest.mark.parametrize("exc_type", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("point", BASE_POINTS)
def test_a_base_exception_ends_the_run_with_a_spec_13_code(h, point, exc_type):
    POINTS[point][0](h, h.monkeypatch, exc_type())
    h.fake.push(review())
    with _SuppressBase():
        h.drive()
    terminals = _terminals(h)
    assert len(terminals) == 1
    assert terminals[0]["error_code"] in ERROR_CODES, terminals[0]["error_code"]
    assert _failure_posts(h) == [_failure("INTERNAL_ERROR")]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-213-03: on a BaseException, RunReporter.__exit__ writes str(exc) to "
        "runs.error_message and the traceback to run_events without scrubbing"
    ),
)
@pytest.mark.parametrize("point", ["compare", "validate"])
def test_a_base_exception_carrying_the_token_is_scrubbed(h, point):
    POINTS[point][0](h, h.monkeypatch, SystemExit(f"exit {TOKEN} {SUPABASE_KEY}"))
    h.fake.push(review())
    with _SuppressBase():
        h.drive()
    assert TOKEN not in h.reporter.dump()
    assert SUPABASE_KEY not in h.reporter.dump()


class _SuppressBase:
    """Swallow whatever BaseException the drive lets out (the harness re-raises it)."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return exc_type is not None and issubclass(exc_type, BaseException)


# ---------------------------------------------------------------------------
# Defect QA-213-04: a failure after the review POST adds a failure comment
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-213-04: once the review comment is posted, an exception from the artifact "
        "write, the 'posted' event or RunReporter.succeed sends the run to _fail, which "
        "posts a second, contradictory 'Code review failed' comment"
    ),
)
@pytest.mark.parametrize("where", ["artifact", "posted-event", "succeed"])
def test_nothing_after_the_review_post_adds_a_failure_comment(h, monkeypatch, where):
    if where == "artifact":
        monkeypatch.setattr(agent_reporter.RunReporter, "artifact", _raiser(RuntimeError("x")))
    elif where == "succeed":
        monkeypatch.setattr(agent_reporter.RunReporter, "succeed", _raiser(RuntimeError("x")))
    else:
        orig = pipeline._Events.info

        def info(self: Any, message: str, **data: Any) -> None:
            if message == "review comment posted":
                raise RuntimeError("x")
            orig(self, message, **data)

        monkeypatch.setattr(pipeline._Events, "info", info)
    h.fake.push(review([blocking()]))
    h.drive()
    assert len(_review_posts(h)) == 1
    assert _failure_posts(h) == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-213-05: a 2xx review POST whose body does not parse raises GitHubApiError, "
        "so the run fails COMMENT_POST_FAILED and posts a failure comment under a review "
        "comment that GitHub did create"
    ),
)
def test_a_created_comment_with_an_unreadable_body_is_not_followed_by_a_failure_comment(h):
    h.stub.add(("POST", COMMENTS_PATH), StubResponse(201, b"<html>not json</html>", {}))
    h.fake.push(review([blocking()]))
    h.drive()
    assert len(_review_posts(h)) == 1
    assert _failure_posts(h) == []


# ---------------------------------------------------------------------------
# 3. Deadline at every step
# ---------------------------------------------------------------------------


def _past_deadline(h: Harness, orig: Callable[..., Any]) -> Callable[..., Any]:
    def wrapped(*a: Any, **k: Any) -> Any:
        h.clock.now = DEADLINE + 1
        return orig(*a, **k)

    return wrapped


def _deadline_on_client(name: str) -> Callable[[Harness, pytest.MonkeyPatch], None]:
    def inject(h: Harness, mp: pytest.MonkeyPatch) -> None:
        mp.setattr(GitHubClient, name, _past_deadline(h, getattr(GitHubClient, name)))

    return inject


def _deadline_on_pipeline(name: str) -> Callable[[Harness, pytest.MonkeyPatch], None]:
    def inject(h: Harness, mp: pytest.MonkeyPatch) -> None:
        mp.setattr(pipeline, name, _past_deadline(h, getattr(pipeline, name)))

    return inject


def _deadline_on_token(h: Harness, mp: pytest.MonkeyPatch) -> None:
    mp.setattr(h, "resolve_token", _past_deadline(h, h.resolve_token))


# (point, last step, failed with RUN_TIMEOUT?)
DEADLINE_POINTS: dict[str, tuple[Callable[[Harness, pytest.MonkeyPatch], None], str, bool]] = {
    "token-mint": (_deadline_on_token, "load_pr", True),
    "load_pr": (_deadline_on_client("get_pull"), "load_pr", True),
    "files": (_deadline_on_client("list_pull_files"), "context", True),
    "compare": (_deadline_on_client("compare"), "context", True),
    "blob-fetch": (_deadline_on_client("get_content_bytes"), "context", True),
    "issues": (_deadline_on_pipeline("linked_issues"), "context", True),
    "conventions": (_deadline_on_pipeline("repo_conventions"), "context", True),
    "build_prompt": (_deadline_on_pipeline("build_prompt"), "context", True),
    "review": (_deadline_on_pipeline("converse_review"), "review", True),
    "validate": (_deadline_on_pipeline("validate_result"), "post", True),
    # Inside post, past the pre-POST check: §13 RUN_TIMEOUT is "before post".
    "render": (_deadline_on_pipeline("render_review"), "post", False),
    "mid-post": (_deadline_on_client("post_pr_comment"), "post", False),
}


@pytest.mark.parametrize("point", list(DEADLINE_POINTS))
def test_the_deadline_at_every_step(h, point):
    inject, step, timed_out = DEADLINE_POINTS[point]
    inject(h, h.monkeypatch)
    h.fake.push(review([blocking()]))
    result = h.drive()

    _assert_invariants(h, result)
    assert h.reporter.step_keys()[-1] == step
    if timed_out:
        assert result["error_code"] == "RUN_TIMEOUT"
        assert _review_posts(h) == []
        assert h.reporter.artifacts() == []
        # token-mint included: the token exists by the post-phase check, so it posts.
        assert h.posts() == [_failure("RUN_TIMEOUT")]
    else:
        assert result["status"] == "succeeded"
        assert len(_review_posts(h)) == 1
        assert len(h.reporter.artifacts()) == 1


def test_the_deadline_before_the_note_post(h, monkeypatch):
    h.set_files([file_entry("pnpm-lock.yaml", 10, 10)])
    _deadline_on_client("list_pull_files")(h, monkeypatch)
    result = h.drive()
    _assert_invariants(h, result)
    assert result["error_code"] == "RUN_TIMEOUT"
    assert h.posts() == [_failure("RUN_TIMEOUT")]


# ---------------------------------------------------------------------------
# 3. Workers abandoned at the deadline
# ---------------------------------------------------------------------------


def _writes_after_terminal(h: Harness) -> list[tuple[str, str]]:
    writes = h.reporter.writes
    idx = max(i for i, (m, t, p) in enumerate(writes) if t == "runs" and "finished_at" in p)
    return [(m, t) for m, t, _p in writes[idx + 1 :]]


def _wait_for(flag: threading.Event, seconds: float = 5.0) -> None:
    assert flag.wait(seconds), "the abandoned worker never finished"
    time.sleep(0.05)  # let it return through the pipeline code after the flag


def test_an_abandoned_review_worker_neither_posts_nor_writes(h):
    """Converse outlives the deadline in real time; after it returns, nothing happens."""
    h.heartbeat_interval = 0.01  # bounded re-reads the clock on every heartbeat
    done = threading.Event()

    seen: dict[str, Any] = {}

    def slow(_request: Any) -> Any:
        h.clock.now = DEADLINE + 1
        time.sleep(0.4)
        seen.update(terminal=bool(_terminals(h)), posts=list(h.posts()))
        done.set()
        return review([blocking()])

    h.fake.push(slow)
    result = h.drive()  # asyncio.run joins the executor, so the worker has finished
    _wait_for(done)
    # Abandoned in real time: the run had ended, failure comment out, before it unblocked.
    assert seen == {"terminal": True, "posts": [_failure("RUN_TIMEOUT")]}

    assert result["error_code"] == "RUN_TIMEOUT"
    assert h.reporter.step_keys() == ["load_pr", "context", "review"]
    assert h.posts() == [_failure("RUN_TIMEOUT")]
    assert _writes_after_terminal(h) == []
    assert h.reporter.artifacts() == []
    assert h.fake.calls == 1, "the abandoned worker made no further Converse call"
    _assert_invariants(h, result)


def test_an_abandoned_context_worker_neither_posts_nor_writes(h, monkeypatch):
    """Stuck in GET issue past the deadline; it then runs spec, verifier and conventions."""
    h.heartbeat_interval = 0.01
    done = threading.Event()
    orig_issue = GitHubClient.get_issue
    orig_build = pipeline.build_prompt

    seen: dict[str, Any] = {}

    def stuck_issue(self: Any, number: int) -> Any:
        h.clock.now = DEADLINE + 1
        time.sleep(0.4)
        seen.update(terminal=bool(_terminals(h)), posts=list(h.posts()))
        return orig_issue(self, number)

    def build(*a: Any, **k: Any) -> Any:
        try:
            return orig_build(*a, **k)
        finally:
            done.set()

    monkeypatch.setattr(GitHubClient, "get_issue", stuck_issue)
    monkeypatch.setattr(pipeline, "build_prompt", build)
    result = h.drive()
    _wait_for(done)
    assert seen == {"terminal": True, "posts": [_failure("RUN_TIMEOUT")]}

    assert result["error_code"] == "RUN_TIMEOUT"
    assert h.reporter.step_keys() == ["load_pr", "context"]
    assert h.posts() == [_failure("RUN_TIMEOUT")]
    assert _writes_after_terminal(h) == []
    assert h.fake.calls == 0
    _assert_invariants(h, result)


def test_an_abandoned_token_mint_posts_nothing_later(h, monkeypatch):
    """A slow token exchange past the deadline: no token, so no failure comment (documented).

    The worker then registers the late token and reads the PR; it must post
    nothing and write nothing after the run ended.
    """
    h.heartbeat_interval = 0.01
    done = threading.Event()

    seen: dict[str, Any] = {}

    def slow_token(org: str) -> str:
        h.clock.now = DEADLINE + 1
        time.sleep(0.4)
        seen.update(terminal=bool(_terminals(h)))
        return TOKEN

    orig_pull = GitHubClient.get_pull

    def pull(self: Any) -> Any:
        try:
            return orig_pull(self)
        finally:
            done.set()

    monkeypatch.setattr(h, "resolve_token", slow_token)
    monkeypatch.setattr(GitHubClient, "get_pull", pull)
    result = h.drive()
    _wait_for(done)
    assert seen == {"terminal": True}, "the run ended while the exchange was blocked"

    assert result["error_code"] == "RUN_TIMEOUT"
    assert h.calls("POST") == []
    assert len(h.calls("GET", PULL_PATH)) == 1, "the abandoned worker's late read"
    assert _writes_after_terminal(h) == []
    assert any("no GitHub token" in m for m in h.reporter.messages("error"))
    _assert_invariants(h, result)


# ---------------------------------------------------------------------------
# 3. Heartbeats during every long phase
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phase", ["load_pr", "context", "review"])
def test_heartbeats_flow_during_each_long_phase(h, monkeypatch, phase):
    h.heartbeat_interval = 0.01
    if phase == "load_pr":
        orig_token = h.resolve_token

        def slow_token(org: str) -> str:
            time.sleep(0.1)
            return orig_token(org)

        monkeypatch.setattr(h, "resolve_token", slow_token)
        h.fake.push(review())
    elif phase == "context":
        orig = GitHubClient.compare

        def slow_compare(self: Any, *a: Any) -> Any:
            time.sleep(0.1)
            return orig(self, *a)

        monkeypatch.setattr(GitHubClient, "compare", slow_compare)
        h.fake.push(review())
    else:

        def slow(_request: Any) -> Any:
            time.sleep(0.1)
            return review()

        h.fake.push(slow)
    result = h.drive()
    assert result["status"] == "succeeded"
    seqs = [c["heartbeat"]["seq"] for c in h.heartbeat_chunks]
    assert len(seqs) >= 3, f"heartbeats during {phase}: {seqs}"
    assert h.chunks[-1] not in h.heartbeat_chunks


# ---------------------------------------------------------------------------
# 3. SIGTERM at every step
# ---------------------------------------------------------------------------


class _Killed(BaseException):
    pass


def _sigterm(*_a: Any, **_k: Any) -> None:
    os.kill(os.getpid(), signal.SIGTERM)
    time.sleep(0.05)  # a worker thread: give the main thread time to run the handler


def _then(orig: Callable[..., Any]) -> Callable[..., Any]:
    """``orig`` with a real SIGTERM delivered first."""

    def wrapped(*a: Any, **k: Any) -> Any:
        _sigterm()
        return orig(*a, **k)

    return wrapped


def _sigterm_on_token(h: Harness, mp: pytest.MonkeyPatch) -> None:
    mp.setattr(h, "resolve_token", _then(h.resolve_token))


def _sigterm_on_compare(h: Harness, mp: pytest.MonkeyPatch) -> None:
    mp.setattr(GitHubClient, "compare", _then(GitHubClient.compare))


def _sigterm_on_converse(h: Harness, mp: pytest.MonkeyPatch) -> None:
    h.fake.push(_then(lambda _request: review([blocking()])))


def _sigterm_on_pipeline(name: str) -> Callable[[Harness, pytest.MonkeyPatch], None]:
    def inject(h: Harness, mp: pytest.MonkeyPatch) -> None:
        mp.setattr(pipeline, name, _then(getattr(pipeline, name)))

    return inject


SIGTERM_POINTS: dict[str, Callable[[Harness, pytest.MonkeyPatch], None]] = {
    "token-mint": _sigterm_on_token,
    "compare": _sigterm_on_compare,
    "review": _sigterm_on_converse,
    "validate": _sigterm_on_pipeline("validate_result"),
    "render": _sigterm_on_pipeline("render_review"),
}


@pytest.mark.parametrize("point", list(SIGTERM_POINTS))
def test_sigterm_at_every_step_is_recorded_once_by_the_backstop(h, monkeypatch, point):
    previous = signal.getsignal(signal.SIGTERM)

    def fake_raise(signum: int) -> None:
        raise _Killed()

    monkeypatch.setattr(signal_backstop.signal, "raise_signal", fake_raise)
    import main

    monkeypatch.setattr(
        main, "install_termination_backstop", signal_backstop.install_termination_backstop
    )
    SIGTERM_POINTS[point](h, monkeypatch)
    if point != "review":
        h.fake.push(review([blocking()]))
    try:
        with pytest.raises(_Killed):
            h.drive()
    finally:
        signal.signal(signal.SIGTERM, previous)

    terminals = _terminals(h)
    assert [t["status"] for t in terminals] == ["failed"]
    assert terminals[0]["error_code"] == "SIGNAL_TERMINATION"
    assert h.calls("POST") == [], "the dying process posts nothing"
    _assert_no_secret(h)


# ---------------------------------------------------------------------------
# 4. Secrets
# ---------------------------------------------------------------------------


def test_secrets_in_pr_text_model_output_and_paths_never_leave(h):
    h.set_pull(
        title=f"Fix {TOKEN}",
        body=f"Closes #41\n\n{SUPABASE_KEY}\n_{TOKEN}_ **{SUPABASE_KEY}**",
    )
    h.set_files(
        [
            file_entry("src/app.py", additions=1, deletions=1),
            file_entry(f"vendor/{SUPABASE_KEY}/uv.lock", 1, 1),
            file_entry(f"assets/{TOKEN}.lock", 1, 1),
        ]
    )
    h.fake.push(
        review(
            [
                blocking(
                    title=f"_{TOKEN}_ and `{SUPABASE_KEY}`",
                    failure_scenario=f"<b>{TOKEN}</b> www.{SUPABASE_KEY}",
                    consequence=f"https://x/{TOKEN}?k={SUPABASE_KEY}",
                    file=f"src/{TOKEN}.py",
                )
            ]
        )
    )
    result = h.drive()
    _assert_invariants(h, result)
    body = h.posts()[0]
    for secret in (TOKEN, SUPABASE_KEY):
        assert secret not in body
        assert secret[4:20] not in body.replace("\\", "").replace("​", "")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-213-06: repository paths are rendered (and cut at 200 chars) without being "
        "scrubbed first, so a secret straddling the cut leaves a fragment the final "
        "whole-string scrub cannot match"
    ),
)
def test_a_secret_straddling_a_path_cut_leaves_no_fragment(h):
    from render import CONTEXT_PATH_MAX

    prefix = "vendor/" + "d" * (CONTEXT_PATH_MAX - len("vendor/") - 10)
    h.set_files([file_entry(f"{prefix}{SUPABASE_KEY}/uv.lock", 1, 1)])
    h.drive()
    body = h.posts()[0]
    assert SUPABASE_KEY[:9] not in body


def test_exception_text_never_reaches_events_message_or_comment(h, monkeypatch):
    monkeypatch.setattr(pipeline, "resolve_specs", _raiser(Hostile()))
    result = h.drive()
    t = _assert_invariants(h, result)
    assert "boom" not in h.reporter.dump()
    assert t["error_message"] == "INTERNAL_ERROR in step context: Hostile"


# ---------------------------------------------------------------------------
# 5-7. The seeded property: random faults, every invariant (seed 415002)
# ---------------------------------------------------------------------------

_CODED_NAMES = [
    *(c for c in ERROR_CODES if c != "INVALID_PARAMS"),
    "GITHUB_NOT_FOUND",
    "GITHUB_UNREACHABLE",
    "NOPE",
    "",
    None,
    500,
]


class _Coded(Exception):
    def __init__(self, code: object) -> None:
        super().__init__(f"coded {TOKEN}")
        self.code = code


def _exception(rng: Any) -> BaseException:
    kind = rng.randrange(6)
    if kind == 0:
        return Hostile()
    if kind == 1:
        return _Coded(rng.choice(_CODED_NAMES))
    if kind == 2:
        return GitHubApiError(f"x {TOKEN}", status=rng.choice([500, 502, 422, None]))
    if kind == 3:
        return GitHubPermissionDenied("denied", status=rng.choice([401, 403]))
    if kind == 4:
        return GitHubNotFound("nf", status=404)
    return requests.ConnectionError(SUPABASE_KEY)


_SCENARIOS = ["clean", "blocking", "closed", "merged", "draft", "404", "budget", "lockfile"]


def _scenario(h: Harness, name: str) -> None:
    if name == "closed":
        h.set_pull(state="closed", merged=False)
    elif name == "merged":
        h.set_pull(state="closed", merged=True)
    elif name == "draft":
        h.set_pull(draft=True)
    elif name == "404":
        h.stub.add(("GET", PULL_PATH), json_response({"message": "Not Found"}, status=404))
    elif name == "budget":
        h.set_files([file_entry("src/app.py", additions=2001)])
    elif name == "lockfile":
        h.set_files([file_entry("pnpm-lock.yaml", 3, 3)])
    h.fake.push(review([blocking()] if name in ("blocking", "draft") else []))


@pytest.mark.xfail(
    strict=True,
    reason=(
        "QA-213-07: error_code_for maps any exception whose .code is 'INVALID_PARAMS' "
        "to INVALID_PARAMS, whose §13 row posts no failure comment, so a sub-call that "
        "raises it after validation leaves the PR silent"
    ),
)
@pytest.mark.parametrize("point", ["compare", "review"])
def test_invalid_params_from_inside_the_pipeline_is_not_silent(h, point):
    POINTS[point][0](h, h.monkeypatch, _Coded("INVALID_PARAMS"))
    h.fake.push(review())
    result = h.drive()
    assert result["error_code"] == "INTERNAL_ERROR"
    assert h.posts() == [_failure("INTERNAL_ERROR")]


def test_random_faults_keep_every_invariant(monkeypatch):
    """Seeded: a scenario, at most one fault at a random point, all invariants."""
    tactic = Tactic.from_env(tactic_seed(415, 2), iterations=160)
    rng = tactic.rng()
    for i in range(tactic.iterations):
        scenario = rng.choice(_SCENARIOS)
        point = rng.choice([None, None, *POINTS])
        exc = _exception(rng)
        if not tactic.selected(i):
            continue
        ctx = tactic.context(i, (scenario, point, type(exc).__name__, getattr(exc, "code", None)))
        with monkeypatch.context() as mp:
            h = Harness(mp)
            _scenario(h, scenario)
            if point is not None:
                POINTS[point][0](h, mp, exc)
            result = h.drive()
            try:
                t = _assert_invariants(h, result)
                _check_paths(h, result, scenario, point, exc, t)
            except AssertionError as err:
                raise AssertionError(f"{ctx}: {err}") from err


def _check_paths(
    h: Harness,
    result: dict[str, Any],
    scenario: str,
    point: str | None,
    exc: BaseException,
    t: dict[str, Any],
) -> None:
    reached = h.reporter.step_keys()
    # 7. State mapping: silent not_applicable for closed, merged and 404.
    if scenario in ("closed", "merged", "404") and result["status"] == "succeeded":
        assert result["outcome"] == "not_applicable"
        assert h.posts() == []
        assert h.fake.calls == 0
        assert reached == ["load_pr"]
    if result["status"] == "succeeded" and result["outcome"] in ("no_findings", "needs_review"):
        # 6. One artifact with every §5.2 key on a reviewed run.
        arts = h.reporter.artifacts()
        assert len(arts) == 1
        meta = arts[0]["metadata"]
        assert set(meta) >= SPEC_5_2_KEYS
        assert set(meta["context"]) >= SPEC_5_2_CONTEXT_KEYS
        assert meta["head_sha"] == HEAD and meta["base_sha"] == BASE
        assert arts[0]["url"] == result["comment_url"]
    else:
        assert h.reporter.artifacts() == []
    if result["status"] == "failed":
        # Never silent: the failure comment exactly where §13 says, else documented.
        no_token = point == "token-mint"
        denied_post = result["error_code"] == "COMMENT_POST_FAILED" and isinstance(
            exc, GitHubPermissionDenied
        )
        if no_token or denied_post:
            assert _failure_posts(h) == []
        else:
            assert _failure_posts(h) == [_failure(result["error_code"])]
        if reached and reached[-1] == "validate" and not (point or "").startswith("step-open"):
            assert result["error_code"] == "INTERNAL_ERROR"
    # The run ID in every marker is this run's.
    for body in _review_posts(h):
        assert body.startswith(f"{MARKER}run={RUN_ID} sha={HEAD} -->")
    assert len(h.calls("GET", PULL_PATH)) <= 1
    if scenario in ("budget", "lockfile"):
        assert h.calls("GET", COMPARE_PATH) == [] or point is not None
    assert all(c.path != FILES_PATH or c.method == "GET" for c in h.stub.calls)
