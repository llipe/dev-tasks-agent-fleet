"""
The review pipeline (S-213; spec §8.1, §5.2, §5.3, §8.9, §12, §13; D-13, D-32, D-36).

``Pipeline.run`` drives one review under the caller's ``RunReporter``, in the
spec §8.1 steps (``STEPS``), and always ends the run:

1. ``load_pr`` — mint the installation token (registered with the scrubber
   before anything is logged), build the allowlisted ``GitHubClient``, and
   ``GET pull`` once. Its ``head_sha`` is the SHA reviewed: every later read
   takes it from this ``PullRequest`` (PRD FR-3). A 404 (not a PR, or gone)
   and a closed or merged PR end ``succeeded``/``not_applicable`` with no
   comment (FR-4: drafts are reviewed; CI status is never read).
2. ``context`` — changed files, classification and ``check_size`` before any
   content fetch; the expanded diff (a client per worker thread from
   ``client_factory``); linked issues, specs, verifier candidates and
   conventions, each with the ``warn`` callback; then ``build_prompt``, which
   fits the budget. Over the line budget (``check_size``) or the token budget
   (``build_prompt``) the run posts the budget comment; with no reviewed file
   (a lockfile-only PR, DF-16) it posts the "nothing to review" note. Both
   happen in a ``post`` step, end ``succeeded``/``not_applicable``, make no
   Converse call and write no ``audit_report`` (EC-21).
3. ``review`` — ``bedrock_adapter.review`` with the production client factory,
   the run deadline and the clock.
4. ``validate`` — ``validate_result`` with the same ``DiffContext`` that built
   the prompt.
5. ``post`` — render with the accepted call's ``ContextData``, scrub, ``POST``
   one new comment (never an edit, FR-25), then the ``audit_report`` artifact
   (§5.2) and ``runs.metrics`` (§5.3). ``clear`` -> ``no_findings``,
   ``blocking`` -> ``needs_review`` (FR-29).

**Errors** (§13). Any exception ends the run ``failed`` with
``error_code_for(exc, step=...)``: mapped on ``exc.code`` (never the class) and
reduced to a ``render.ERROR_CODES`` constant with ``render.canonical_code``,
so the run and the failure comment always agree. Anything ``validate`` raises
is ``INTERNAL_ERROR``. Then, per ``FAILURE_COMMENT``, one failure comment is
attempted (D-13); after ``COMMENT_POST_FAILED`` it is skipped only when the
POST raised ``GitHubPermissionDenied`` (401, or a 403 that is not a rate
limit; a rate-limited 403 still gets one, S-205 D4). A failed failure comment
is an ``error`` event and never changes the code. ``INVALID_PARAMS`` never
reaches here (``main.invoke``), and posts nothing.

**Deadline and heartbeat** (D-32, §8.9). The deadline is
``start + run_timeout_seconds - 60`` on the injected monotonic clock. It is
checked before every step and when each blocking phase returns, and ``bounded``
stops waiting for a blocking phase at the deadline in real time; reaching it is
``RUN_TIMEOUT``. The 60 s reserve pays for the failure comment and the reporter
flush. ``load_pr``, ``context`` and ``review`` run in a worker thread under the
heartbeat, whose chunks are yielded to the entrypoint stream; ``validate`` and
``post`` run inline. SIGTERM is the sibling signal backstop's job (installed by
``main.invoke``); the failure comment is attempted only from this module's
failure path, at most once.

**What leaves the wrapper** (§12, §13). run_events carry fixed messages and
counts only: no prompt, model or repository text, and no reviewed path. Every
event, the comment body and the artifact metadata pass through ``scrubber``
with the token and the Supabase key. Model and repository text in the
``Validation`` is scrubbed before rendering, since the renderer escapes it
(``_`` becomes ``\\_``) and a scrub of the escaped body alone would miss it.

**Metrics** (§5.3, S-210 DR-11). ``estimated_input_tokens`` is the estimate
(``bedrock_adapter.request_tokens``) of every Converse request actually sent,
the same scope as ``input_tokens`` (the sum of every call's usage), so the two
compare directly for the D-27 recalibration; ``estimated_first_call_tokens``
is the first prompt's budget estimate. ``context_tokens`` is per block of the
accepted call's prompt.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from bedrock_adapter import (
    BedrockAdapterError,
    CallMetrics,
    ClientFactory,
    ConverseClient,
    ReviewResult,
    make_client,
    request_tokens,
)
from bedrock_adapter import review as converse_review
from budget import BLOCK_SPEC, ContextData, ContextInputs
from config import DEADLINE_RESERVE_SECONDS, HEARTBEAT_INTERVAL, Settings
from context.diff import (
    DiffContext,
    NameOnlyFile,
    OverBudget,
    changed_lines,
    check_size,
    classify,
    expanded_diff,
)
from context.issues import linked_issues
from context.repo_conventions import repo_conventions
from context.spec import resolve_specs
from context.verifier import REPORT_NONE, verifier_candidates
from github_client import (
    GitHubClient,
    GitHubError,
    GitHubNotFound,
    GitHubPermissionDenied,
    PostedComment,
    PullRequest,
)
from heartbeat import HeartbeatResult, run_with_heartbeat
from prompt import Prompt, PromptSink, build_prompt, new_nonce, null_sink
from render import (
    canonical_code,
    code_span,
    comment_size,
    neutralize,
    render_budget,
    render_failure,
    render_nothing_to_review,
    render_review,
)
from scrubber import scrub
from validate import VERDICT_BLOCKING, VERDICT_CLEAR, Validation, validate_result

__all__ = [
    "FAILURE_COMMENT",
    "OUTCOME_NEEDS_REVIEW",
    "OUTCOME_NOT_APPLICABLE",
    "OUTCOME_NO_FINDINGS",
    "STEPS",
    "CommentPostFailed",
    "Pipeline",
    "PipelineDeps",
    "PipelineResult",
    "ReviewRequest",
    "RunTimeout",
    "audit_metadata",
    "bounded",
    "context_tokens",
    "error_code_for",
    "outcome_for_verdict",
    "run_deadline",
    "scrub_value",
    "wants_failure_comment",
]

STEPS = ("load_pr", "context", "review", "validate", "post")

STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
OUTCOME_NO_FINDINGS = "no_findings"
OUTCOME_NEEDS_REVIEW = "needs_review"
OUTCOME_NOT_APPLICABLE = "not_applicable"

ARTIFACT_SCHEMA_VERSION = 1
MESSAGE_MAX = 300  # run error_message detail

# Spec §13, the "Failure comment" column.
FAILURE_COMMENT: dict[str, str] = {
    "INVALID_PARAMS": "no",
    "GITHUB_PERMISSION_DENIED": "attempted",
    "GITHUB_API_ERROR": "attempted",
    "BEDROCK_ACCESS_DENIED": "yes",
    "BEDROCK_ERROR": "yes",
    "MODEL_OUTPUT_INVALID": "yes",
    "RUN_TIMEOUT": "yes",
    "COMMENT_POST_FAILED": "once_unless_denied",
    "INTERNAL_ERROR": "yes",
}

# Codes mapped before ``canonical_code``. ``GITHUB_NOT_FOUND`` on
# ``load_pr`` is ``not_applicable`` before any mapping; later (compare, files)
# it is an API failure. ``GITHUB_UNREACHABLE`` is the token exchange's
# transport failure ("GitHub 5xx or network").
_CODE_ALIASES = {
    "GITHUB_NOT_FOUND": "GITHUB_API_ERROR",
    "GITHUB_UNREACHABLE": "GITHUB_API_ERROR",
    # Only main.invoke's params validation may end a run INVALID_PARAMS (§13: no
    # comment, the PR is unvalidated). Inside the pipeline the params are valid,
    # so a sub-call raising that code is a defect, and the PR gets a comment.
    "INVALID_PARAMS": "INTERNAL_ERROR",
}


# ---------------------------------------------------------------------------
# Errors, outcomes, the deadline
# ---------------------------------------------------------------------------


class RunTimeout(Exception):
    """The run deadline (``start + run_timeout_seconds - 60``) was reached."""

    code = "RUN_TIMEOUT"


class CommentPostFailed(Exception):
    """The review (or budget) comment ``POST`` failed; ``cause`` is the client error."""

    code = "COMMENT_POST_FAILED"

    def __init__(self, cause: BaseException | None) -> None:
        self.cause = cause
        status = getattr(cause, "status", None)
        detail = type(cause).__name__ if cause is not None else "unknown"
        if isinstance(status, int) and not isinstance(status, bool):
            detail += f" (HTTP {status})"
        super().__init__(f"comment POST failed: {detail}")


class _StepFailure(Exception):
    """What a failed step records: the code and the exception class, never its text."""


def outcome_for_verdict(verdict: object) -> str:
    """``clear`` -> ``no_findings``, ``blocking`` -> ``needs_review`` (PRD FR-29)."""
    if isinstance(verdict, str) and verdict == VERDICT_CLEAR:
        return OUTCOME_NO_FINDINGS
    if isinstance(verdict, str) and verdict == VERDICT_BLOCKING:
        return OUTCOME_NEEDS_REVIEW
    raise ValueError("unknown verdict")


def run_deadline(start: float, run_timeout_seconds: int) -> float:
    """``start + run_timeout_seconds - DEADLINE_RESERVE_SECONDS`` (spec §8.9)."""
    return start + run_timeout_seconds - DEADLINE_RESERVE_SECONDS


def error_code_for(exc: BaseException, *, step: str | None = None) -> str:
    """The run's ``error_code`` for ``exc``: a ``render.ERROR_CODES`` constant.

    Read from ``exc.code``; anything ``validate`` raises (other than the
    deadline) is ``INTERNAL_ERROR`` (S-211 carry-forward).
    """
    if step == "validate" and not isinstance(exc, RunTimeout):
        return "INTERNAL_ERROR"
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        code = _CODE_ALIASES.get(str.__str__(code), code)
    return canonical_code(code)


def wants_failure_comment(code: str, exc: BaseException | None) -> bool:
    """Spec §13: whether the failure path attempts the one-line comment for ``code``."""
    policy = FAILURE_COMMENT.get(canonical_code(code), "yes")
    if policy == "no":
        return False
    if policy == "once_unless_denied":
        cause = getattr(exc, "cause", exc)
        return not isinstance(cause, GitHubPermissionDenied)
    return True


# ---------------------------------------------------------------------------
# A blocking phase under the heartbeat and the deadline
# ---------------------------------------------------------------------------

Heartbeat = Callable[..., AsyncIterator[Any]]


async def bounded(
    fn: Callable[[], Any],
    *,
    deadline: float,
    clock: Callable[[], float],
    interval: float,
    heartbeat: Heartbeat = run_with_heartbeat,
) -> AsyncIterator[Any]:
    """Run ``fn`` under ``heartbeat``; yield its heartbeat chunks, then one ``HeartbeatResult``.

    Raises ``RunTimeout`` without starting ``fn`` when the deadline has
    passed, and stops waiting for ``fn`` once it is reached (the worker thread
    is abandoned; it only reads). ``fn``'s own exception is re-raised.
    """
    if clock() >= deadline:
        raise RunTimeout("run deadline reached")
    agen = heartbeat(fn, interval=interval)
    try:
        while True:
            remaining = deadline - clock()
            if remaining <= 0:
                raise RunTimeout("run deadline reached")
            try:
                item = await asyncio.wait_for(agen.__anext__(), timeout=remaining)
            except TimeoutError:
                raise RunTimeout("run deadline reached") from None
            if isinstance(item, HeartbeatResult):
                if item.error is not None:
                    raise item.error
                yield item
                return
            yield item
    finally:
        aclose = getattr(agen, "aclose", None)
        if aclose is not None:
            await aclose()


# ---------------------------------------------------------------------------
# Scrubbing
# ---------------------------------------------------------------------------


def scrub_value(value: Any, secrets: Sequence[str]) -> Any:
    """``scrubber.scrub`` over every string in nested dicts, lists and tuples."""
    if isinstance(value, str):
        return scrub(value, list(secrets))
    if isinstance(value, dict):
        return {scrub_value(k, secrets): scrub_value(v, secrets) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [scrub_value(v, secrets) for v in value]
    return value


def _scrub_validation(v: Validation, secrets: Sequence[str]) -> Validation:
    """The validation with every model and repository text field scrubbed."""

    def s(text: str) -> str:
        return scrub(text, list(secrets))

    def finding(f: Any) -> Any:
        return dataclasses.replace(
            f,
            file=s(f.file),
            title=s(f.title),
            failure_scenario=s(f.failure_scenario),
            consequence=s(f.consequence),
        )

    return dataclasses.replace(
        v,
        blocking=tuple(finding(f) for f in v.blocking),
        suggestions=tuple(finding(f) for f in v.suggestions),
        dropped=tuple(dataclasses.replace(d, file=s(d.file), title=s(d.title)) for d in v.dropped),
        candidates=tuple(
            dataclasses.replace(
                c,
                reason=s(c.reason),
                candidate=dataclasses.replace(
                    c.candidate,
                    text=s(c.candidate.text),
                    report_path=s(c.candidate.report_path),
                ),
            )
            for c in v.candidates
        ),
    )


def _rendered_forms(secrets: Sequence[str]) -> list[str]:
    """Each secret as written and as the renderer would escape it (text and code span)."""
    forms: list[str] = []
    for secret in secrets:
        if not secret:
            continue
        for form in (secret, neutralize(secret), code_span(secret, len(secret) * 8 + 16)):
            if len(form) >= 3 and form not in forms:
                forms.append(form)
    # Longest first, so an escaped form is not pre-empted by a shorter one.
    return sorted(forms, key=len, reverse=True)


# ---------------------------------------------------------------------------
# Metrics and the artifact (spec §5.2, §5.3)
# ---------------------------------------------------------------------------


def context_tokens(data: ContextData) -> dict[str, int]:
    """Spec §5.3 ``context_tokens``: tokens charged per block, plus ``pr``.

    ``verifier`` holds the drift sections and the candidate blocks together.
    """
    b = data.block_tokens
    return {
        "instructions": b["instructions"],
        "diff": b["diff"],
        "pr": b["pr"],
        "issues": b["issue"],
        "spec": b["spec"],
        "verifier": b["verifier"] + b["verifier-candidate"],
        "conventions": b["conventions"],
        "full_files": b["file"],
    }


def audit_metadata(
    *,
    pull: PullRequest,
    pr_number: int,
    validation: Validation,
    result: ReviewResult,
    inputs: ContextInputs,
    diff: DiffContext,
    model_id: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    """The ``audit_report`` metadata (spec §5.2), before scrubbing."""
    ctx = result.context
    spec_path = ctx.spec_paths[0] if ctx.spec_paths else None
    resolved = None
    if spec_path is not None and inputs.spec is not None:
        resolved = next((s for s in inputs.spec.specs if s.path == spec_path), None)
    spec_trimmed = bool(resolved is not None and (resolved.trimmed or resolved.truncated)) or any(
        n.block == BLOCK_SPEC and n.ref == spec_path for n in ctx.notes
    )
    reports = (
        [r.path for r in inputs.verifier.reports if r.state != REPORT_NONE]
        if inputs.verifier is not None
        else []
    )
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "pr_number": pr_number,
        "head_sha": pull.head_sha,
        "base_sha": pull.base_sha,
        "merge_base_sha": diff.merge_base_sha,
        "verdict": validation.verdict,
        "model_id": model_id,
        "output_mode": result.output_mode,
        "reasoning_effort": reasoning_effort,
        "reasoning_effort_applied": result.reasoning_effort_applied,
        "rubric_version": result.prompt.rubric_version,
        "context": {
            "issues": list(ctx.issue_numbers),
            "spec": spec_path,
            "specs": list(ctx.spec_paths),
            "spec_trimmed": spec_trimmed,
            "fidelity_reports": reports,
            "full_files_included": len(ctx.full_files_included),
            "full_files_dropped": len(ctx.full_files_dropped),
            "listed_by_name": [f.filename for f in diff.name_only],
        },
        "findings": [f.as_artifact() for f in validation.findings],
        "verifier": [
            {
                "candidate_id": c.id,
                "report": c.candidate.report_path,
                "row": c.candidate.text,
                "status": c.status,
                "reason": c.reason,
            }
            for c in validation.candidates
        ],
        "dropped": [d.as_artifact() for d in validation.dropped],
    }


def _empty_metrics() -> dict[str, Any]:
    """Every spec §5.3 key with its "nothing happened" value."""
    return {
        "input_tokens": None,
        "output_tokens": None,
        "estimated_input_tokens": None,
        "estimated_first_call_tokens": None,
        "cost_usd": None,
        "bedrock_ms": 0,
        "bedrock_calls": 0,
        "wall_clock_ms": 0,
        "output_mode": None,
        "repair_calls": 0,
        "reasoning_effort_applied": None,
        "context_tokens": {},
        "findings_by_severity": {},
        "findings_by_category": {},
        "downgraded": {},
        "dropped": {},
        "suggestions_capped": 0,
        "verifier_candidates": 0,
        "verifier_confirmed": 0,
        "comment_chars": 0,
        "comment_truncated": False,
    }


# ---------------------------------------------------------------------------
# Inputs, deps, result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewRequest:
    """A validated invocation with defaults applied."""

    run_id: str
    repository_org: str
    repository_name: str
    params: dict[str, Any]
    settings: Settings


@dataclass(frozen=True)
class PipelineDeps:
    """What ``main.invoke`` injects; the defaults are production's.

    ``resolve_token`` maps the org to an installation token. ``make_github``
    is called as ``make_github(token, org, repo, pr_number)``.
    ``bedrock_factory`` is ``bedrock_adapter.make_client``'s shape, called once
    per Converse call with that call's timeouts.
    """

    resolve_token: Callable[[str], str]
    make_github: Callable[..., GitHubClient] = GitHubClient
    bedrock_factory: ClientFactory = make_client
    clock: Callable[[], float] = time.monotonic
    sink: PromptSink = null_sink
    nonce_factory: Callable[[], str] = new_nonce
    heartbeat: Heartbeat = run_with_heartbeat
    heartbeat_interval: float = HEARTBEAT_INTERVAL


@dataclass(frozen=True)
class PipelineResult:
    """The terminal state; ``payload()`` is the entrypoint's return chunk (spec §6.1)."""

    status: str
    outcome: str
    error_code: str | None = None
    verdict: str | None = None
    comment_url: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "outcome": self.outcome,
            "verdict": self.verdict,
            "comment_url": self.comment_url,
            "error_code": self.error_code,
        }


@dataclass
class _Gathered:
    """What the ``context`` step produced."""

    over: OverBudget | None = None
    nothing: bool = False
    name_only: tuple[NameOnlyFile, ...] = ()
    diff: DiffContext | None = None
    inputs: ContextInputs | None = None
    prompt: Prompt | None = None
    counts: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Box:
    value: Any = None


@dataclass
class _Gate:
    """A worker's ``warn`` channel; closed when its phase is abandoned at the deadline."""

    open: bool = True


class _Events:
    """Scrubbed, thread-safe run_events on the reporter."""

    def __init__(self, run: Any, secrets: list[str]) -> None:
        self._run = run
        self._secrets = secrets
        self._lock = threading.Lock()

    def log(self, level: str, message: str, gate: _Gate | None = None, **data: Any) -> None:
        with self._lock:
            if gate is not None and not gate.open:
                return
            self._run.log(
                scrub(message, self._secrets), level=level, **scrub_value(data, self._secrets)
            )

    def info(self, message: str, **data: Any) -> None:
        self.log("info", message, **data)

    def warn(self, message: str, **data: Any) -> None:
        self.log("warn", message, **data)

    def error(self, message: str, **data: Any) -> None:
        self.log("error", message, **data)

    def warner(self, gate: _Gate) -> Callable[..., None]:
        """The ``warn`` callback for a worker phase."""

        def warn(message: str, **data: Any) -> None:
            self.log("warn", message, gate=gate, **data)

        return warn


class _CountingClient:
    """A Converse client that adds each request's estimate to the run total (DR-11)."""

    def __init__(self, inner: ConverseClient, pipeline: Pipeline) -> None:
        self._inner = inner
        self._pipeline = pipeline

    def converse(self, **request: Any) -> Any:
        self._pipeline._sent_tokens += request_tokens(request)
        return self._inner.converse(**request)


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


@dataclass
class Pipeline:
    """One review run. ``run()`` yields heartbeat chunks, then one ``PipelineResult``."""

    run_reporter: Any
    request: ReviewRequest
    secrets: list[str]
    deps: PipelineDeps
    _events: _Events = field(init=False)
    _client: GitHubClient | None = field(default=None, init=False)
    _token: str | None = field(default=None, init=False)
    _pull: PullRequest | None = field(default=None, init=False)
    _step_key: str | None = field(default=None, init=False)
    _start: float = field(default=0.0, init=False)
    _deadline: float = field(default=0.0, init=False)
    _metrics: dict[str, Any] = field(default_factory=_empty_metrics, init=False)
    _counts: dict[str, Any] = field(default_factory=dict, init=False)
    _sent_tokens: int = field(default=0, init=False)
    _failure_comment_tried: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self._events = _Events(self.run_reporter, self.secrets)

    # -- params ------------------------------------------------------------

    @property
    def params(self) -> dict[str, Any]:
        return self.request.params

    @property
    def settings(self) -> Settings:
        return self.request.settings

    # -- entry -------------------------------------------------------------

    async def run(self) -> AsyncIterator[Any]:
        self._start = self.deps.clock()
        self._deadline = run_deadline(self._start, self.params["run_timeout_seconds"])
        result: PipelineResult | None = None
        try:
            async for item in self._stages():
                if isinstance(item, PipelineResult):
                    result = item
                else:
                    yield item
        except Exception as exc:  # noqa: BLE001 - every failure ends the run (spec §13)
            result = self._fail(exc)
        assert result is not None
        yield result

    # -- steps ---------------------------------------------------------------

    @contextlib.contextmanager
    def _step(self, key: str) -> Iterator[None]:
        self._step_key = key
        step = self.run_reporter.step(key)
        try:
            yield
        except BaseException as exc:
            code = error_code_for(exc, step=key) if isinstance(exc, Exception) else "INTERRUPTED"
            failure = _StepFailure(f"{code} ({type(exc).__name__})")
            step.__exit__(_StepFailure, failure, None)
            raise
        else:
            step.__exit__(None, None, None)

    def _check_deadline(self) -> None:
        if self.deps.clock() >= self._deadline:
            raise RunTimeout(f"run deadline reached before step {self._step_key}")

    async def _phase(
        self, fn: Callable[[_Gate], Any], box: _Box, *, check: bool = True
    ) -> AsyncIterator[Any]:
        """Run ``fn(gate)`` in a worker under the heartbeat and the deadline.

        With ``check`` the deadline is checked again when ``fn`` returns; the
        review step checks it itself, after recording the calls' metrics.
        """
        gate = _Gate()
        try:
            async for item in bounded(
                lambda: fn(gate),
                deadline=self._deadline,
                clock=self.deps.clock,
                interval=self.deps.heartbeat_interval,
                heartbeat=self.deps.heartbeat,
            ):
                if isinstance(item, HeartbeatResult):
                    box.value = item.value
                else:
                    yield item
        except RunTimeout:
            gate.open = False  # the abandoned worker's late warnings are dropped
            raise
        if check:
            self._check_deadline()

    async def _stages(self) -> AsyncIterator[Any]:
        box = _Box()

        # 1. load_pr
        with self._step("load_pr"):
            self._check_deadline()
            async for chunk in self._phase(self._load_pr, box):
                yield chunk
            pull: PullRequest | None = box.value
            if pull is None:
                self._events.info("pull request not found (404): not applicable", status=404)
            else:
                self._events.info(
                    "pull request loaded",
                    state=pull.state,
                    merged=pull.merged,
                    draft=pull.draft,
                    head_sha=pull.head_sha,
                )
        if pull is None or pull.state != "open" or pull.merged:
            yield self._succeed(OUTCOME_NOT_APPLICABLE)
            return
        self._pull = pull

        # 2. context
        with self._step("context"):
            self._check_deadline()
            async for chunk in self._phase(self._gather, box):
                yield chunk
            gathered: _Gathered = box.value
            self._counts.update(gathered.counts)
            self._log_context(gathered)

        if gathered.over is not None or gathered.nothing:
            yield self._post_note(gathered)
            return
        assert gathered.prompt is not None and gathered.inputs is not None
        assert gathered.diff is not None

        # 3. review
        with self._step("review"):
            self._check_deadline()
            async for chunk in self._phase(
                lambda gate: self._converse(gathered, gate), box, check=False
            ):
                yield chunk
            result: ReviewResult = box.value
            self._record_calls(result.metrics)
            self._metrics["context_tokens"] = context_tokens(result.context)
            self._check_deadline()
            self._events.info(
                "review received",
                calls=result.calls,
                repair_calls=result.repair_calls,
                output_mode=result.output_mode,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                bedrock_ms=result.bedrock_ms,
            )

        # 4. validate
        with self._step("validate"):
            self._check_deadline()
            validation = validate_result(
                result, gathered.diff, max_suggestions=self.params["max_suggestions"]
            )
            self._metrics.update(validation.metrics())
            self._events.info(
                "findings validated",
                verdict=validation.verdict,
                blocking=len(validation.blocking),
                suggestions=len(validation.suggestions),
                dropped=len(validation.dropped),
                downgraded=sum(validation.counts.downgraded.values()),
                verifier_confirmed=validation.counts.verifier_confirmed,
            )

        # 5. post
        with self._step("post"):
            self._check_deadline()
            comment = self._post_review(validation, result, gathered)
        outcome = outcome_for_verdict(validation.verdict)
        yield self._succeed(outcome, verdict=validation.verdict, comment_url=comment.html_url)

    # -- worker phases (run in a thread) ---------------------------------------

    def _github(self) -> GitHubClient:
        assert self._token is not None
        return self.deps.make_github(
            self._token,
            self.request.repository_org,
            self.request.repository_name,
            self.params["pr_number"],
        )

    def _load_pr(self, gate: _Gate) -> PullRequest | None:
        token = self.deps.resolve_token(self.request.repository_org)
        if token and token not in self.secrets:
            self.secrets.append(token)  # before any line that could carry it
        self._token = token
        self._client = self._github()
        try:
            return self._client.get_pull()
        except GitHubNotFound:
            return None

    def _gather(self, gate: _Gate) -> _Gathered:
        client, pull = self._client, self._pull
        assert client is not None and pull is not None
        warn = self._events.warner(gate)
        budget = self.params["max_context_tokens"]
        max_lines = self.params["max_diff_lines"]
        # Local, returned with the result: an abandoned worker never touches run state.
        counts: dict[str, Any] = {}

        files = client.list_pull_files()
        classification = classify(files.files)
        counts.update(
            changed_lines=changed_lines(classification),
            files_changed=len(files.files),
            files_reviewed=len(classification.reviewed),
            files_name_only=len(classification.name_only),
            files_listing_truncated=files.truncated,
        )
        over = check_size(classification, max_lines, truncated=files.truncated)
        if over is not None:
            return _Gathered(counts=counts, over=over, name_only=classification.name_only)
        if not classification.reviewed:
            return _Gathered(counts=counts, nothing=True, name_only=classification.name_only)

        diff = expanded_diff(client, pull, classification, client_factory=self._github)
        counts.update(files_reviewed=len(diff.files), files_name_only=len(diff.name_only))
        if not diff.files:
            return _Gathered(counts=counts, nothing=True, name_only=diff.name_only, diff=diff)

        issues = linked_issues(client, pull, warn=warn)
        specs = resolve_specs(
            client,
            issues.issues,
            pull.head_sha,
            reviewed_paths=[f.filename for f in diff.files],
            max_context_tokens=budget,
            warn=warn,
        )
        verifier = verifier_candidates(client, issues.issues, pull.head_sha, warn=warn)
        conventions = repo_conventions(client, pull.head_sha, max_context_tokens=budget, warn=warn)
        inputs = ContextInputs(
            pr_number=self.params["pr_number"],
            head_sha=pull.head_sha,
            pr_title=pull.title,
            pr_body=pull.body,
            diff=diff,
            issues=issues,
            spec=specs,
            verifier=verifier,
            conventions=conventions,
        )
        counts.update(
            issues_linked=len(issues.issues),
            issues_skipped=len(issues.skipped),
            specs=len(specs.specs),
            verifier_reports=len([r for r in verifier.reports if r.state != REPORT_NONE]),
        )
        built = build_prompt(
            inputs,
            max_context_tokens=budget,
            max_diff_lines=max_lines,
            nonce_factory=self.deps.nonce_factory,
            sink=self.deps.sink,
        )
        if isinstance(built, OverBudget):
            return _Gathered(
                counts=counts, over=built, name_only=diff.name_only, diff=diff, inputs=inputs
            )
        return _Gathered(
            counts=counts, diff=diff, inputs=inputs, prompt=built, name_only=diff.name_only
        )

    def _converse(self, gathered: _Gathered, gate: _Gate) -> ReviewResult:
        assert gathered.prompt is not None and gathered.inputs is not None
        return converse_review(
            gathered.prompt,
            gathered.inputs,
            client_factory=self._bedrock_client,
            settings=self.settings,
            reasoning_effort=self.params["reasoning_effort"],
            max_diff_lines=self.params["max_diff_lines"],
            warn=self._events.warner(gate),
            sink=self.deps.sink,
            nonce_factory=self.deps.nonce_factory,
            clock=self.deps.clock,
            deadline=self._deadline,
        )

    def _bedrock_client(
        self, *, read_timeout_seconds: float, connect_timeout_seconds: float
    ) -> ConverseClient:
        inner = self.deps.bedrock_factory(
            read_timeout_seconds=read_timeout_seconds,
            connect_timeout_seconds=connect_timeout_seconds,
        )
        return _CountingClient(inner, self)

    # -- logging and metrics -------------------------------------------------------

    def _log_context(self, g: _Gathered) -> None:
        data: dict[str, Any] = {
            k: self._counts[k]
            for k in ("changed_lines", "files_changed", "files_reviewed", "files_name_only")
            if k in self._counts
        }
        if g.over is not None:
            data["over_budget"] = g.over.reason
        if g.nothing:
            data["nothing_to_review"] = True
        if g.inputs is not None:
            for k in ("issues_linked", "issues_skipped", "specs", "verifier_reports"):
                data[k] = self._counts.get(k, 0)
            verifier = g.inputs.verifier
            data["verifier_candidates"] = len(verifier.candidates) if verifier is not None else 0
        if g.prompt is not None:
            data["block_tokens"] = g.prompt.context.block_tokens
            data["prompt_tokens"] = g.prompt.tokens
            data["full_files_included"] = len(g.prompt.context.full_files_included)
            data["full_files_dropped"] = len(g.prompt.context.full_files_dropped)
            self._metrics["estimated_first_call_tokens"] = g.prompt.tokens
            self._metrics["context_tokens"] = context_tokens(g.prompt.context)
        self._events.info("context assembled", **data)

    def _record_calls(self, calls: CallMetrics | None) -> None:
        if calls is None:
            return
        self._metrics.update(calls.as_metrics())
        self._metrics["estimated_input_tokens"] = self._sent_tokens

    def _final_metrics(self) -> dict[str, Any]:
        out = dict(self._metrics)
        out.update(self._counts)
        out["wall_clock_ms"] = max(0, round((self.deps.clock() - self._start) * 1000))
        return scrub_value(out, self.secrets)

    # -- outputs -------------------------------------------------------------

    def _scrub_body(self, body: str) -> str:
        for form in _rendered_forms(self.secrets):
            if form in body:
                body = body.replace(form, "***")
        return body

    def _post(self, body: str) -> PostedComment:
        assert self._client is not None
        try:
            return self._client.post_pr_comment(body)
        except GitHubError as exc:
            raise CommentPostFailed(exc) from None

    def _post_note(self, g: _Gathered) -> PipelineResult:
        """The budget comment or the nothing-to-review note, in a ``post`` step."""
        run_id, panel = self.request.run_id, self.settings.panel_base_url
        with self._step("post"):
            self._check_deadline()
            if g.over is not None:
                body = render_budget(
                    g.over, run_id=run_id, panel_base_url=panel, name_only=g.name_only
                )
                kind = "budget comment"
            else:
                body = render_nothing_to_review(g.name_only, run_id=run_id, panel_base_url=panel)
                kind = "nothing-to-review note"
            body = self._scrub_body(body)
            self._metrics["comment_chars"] = comment_size(body)
            comment = self._post(body)
            self._events.info(f"{kind} posted", comment_chars=self._metrics["comment_chars"])
        return self._succeed(OUTCOME_NOT_APPLICABLE, comment_url=comment.html_url)

    def _post_review(
        self, validation: Validation, result: ReviewResult, g: _Gathered
    ) -> PostedComment:
        assert g.inputs is not None and g.diff is not None and self._pull is not None
        clean = _scrub_validation(validation, self.secrets)
        rendered = render_review(
            clean,
            context=result.context,
            diff=g.diff,
            verifier=g.inputs.verifier,
            run_id=self.request.run_id,
            head_sha=self._pull.head_sha,
            model_id=self.settings.model_id,
            rubric_version=result.prompt.rubric_version,
            panel_base_url=self.settings.panel_base_url,
        )
        body = self._scrub_body(rendered.body)
        self._metrics["comment_chars"] = rendered.chars
        self._metrics["comment_truncated"] = rendered.truncated
        if rendered.truncated:
            self._events.warn(
                "review comment truncated",
                stages=list(rendered.stages),
                comment_chars=rendered.chars,
            )
        # Built before the POST, so nothing after a posted comment can fail the run.
        metadata = scrub_value(
            audit_metadata(
                pull=self._pull,
                pr_number=self.params["pr_number"],
                validation=clean,
                result=result,
                inputs=g.inputs,
                diff=g.diff,
                model_id=self.settings.model_id,
                reasoning_effort=self.params["reasoning_effort"],
            ),
            self.secrets,
        )
        number, short = self.params["pr_number"], self._pull.head_sha[:7]
        title = f"Code review #{number} @ {short}: {validation.verdict}"
        comment = self._post(body)
        self.run_reporter.artifact("audit_report", url=comment.html_url, title=title, **metadata)
        self._events.info(
            "review comment posted",
            comment_chars=rendered.chars,
            comment_truncated=rendered.truncated,
            stages=list(rendered.stages),
        )
        return comment

    # -- terminal states ---------------------------------------------------------

    def _succeed(
        self, outcome: str, *, verdict: str | None = None, comment_url: str | None = None
    ) -> PipelineResult:
        self.run_reporter.succeed(
            outcome,
            result={"verdict": verdict, "comment_url": comment_url},
            metrics=self._final_metrics(),
        )
        return PipelineResult(STATUS_SUCCEEDED, outcome, verdict=verdict, comment_url=comment_url)

    def _fail(self, exc: Exception) -> PipelineResult:
        code = error_code_for(exc, step=self._step_key)
        step = self._step_key or "start"
        self._record_calls(getattr(exc, "metrics", None))
        status = getattr(exc, "status", None)
        if status is None:
            status = getattr(getattr(exc, "cause", None), "status", None)
        self._events.error(
            f"run failed: {code}",
            code=code,
            step=step,
            error=type(exc).__name__,
            status=status if isinstance(status, int) and not isinstance(status, bool) else None,
        )
        if wants_failure_comment(code, exc):
            self._failure_comment(code)
        self.run_reporter.fail(
            error_code=code,
            error_message=self._message(exc, code, step),
            outcome=OUTCOME_NOT_APPLICABLE,
            metrics=self._final_metrics(),
        )
        return PipelineResult(STATUS_FAILED, OUTCOME_NOT_APPLICABLE, error_code=code)

    def _message(self, exc: Exception, code: str, step: str) -> str:
        """``<code> in step <step>: <class>``; only the wrapper's own safe texts are added."""
        message = f"{code} in step {step}: {type(exc).__name__}"
        status = getattr(exc, "status", None)
        if isinstance(status, int) and not isinstance(status, bool):
            message += f" (HTTP {status})"
        if isinstance(exc, BedrockAdapterError | RunTimeout | CommentPostFailed):
            message += f": {exc}"
        return scrub(message, self.secrets)[:MESSAGE_MAX]

    def _failure_comment(self, code: str) -> None:
        """D-13: one best-effort failure comment; a failure here is logged, nothing more."""
        if self._failure_comment_tried:
            return
        self._failure_comment_tried = True
        if self._token is None:
            self._events.error("failure comment not posted: no GitHub token", code=code)
            return
        body = self._scrub_body(
            render_failure(
                code, run_id=self.request.run_id, panel_base_url=self.settings.panel_base_url
            )
        )
        try:
            # A fresh client: a worker abandoned at the deadline may still hold the
            # run's client, and a requests.Session is not shared across threads.
            self._github().post_pr_comment(body)
        except Exception as exc:  # noqa: BLE001 - best effort (D-13)
            status = getattr(exc, "status", None)
            self._events.error(
                "failure comment not posted",
                code=code,
                error=type(exc).__name__,
                status=status if isinstance(status, int) and not isinstance(status, bool) else None,
            )
            return
        self._events.info("failure comment posted", code=code)
