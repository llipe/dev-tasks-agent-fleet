"""
bug-fix agent — AgentCore entrypoint and step orchestration
(S-190; spec §4, §8.2–§8.9, §13; FR-5, FR-25–FR-27; D-20, D-58, D-61, D-67,
D-81, D-92, D-94, D-112).

Payload (spec §6, D-60): ``{run_id, repository_org, repository_name,
base_branch, params}``, optionally wrapped as ``{"prompt": "<json>"}``.

**Steps.** Each is one ``run_steps`` entry with ``run_events`` at its
decisions (FR-25):

1. ``preflight`` — the payload (``run_id`` a UUID, the repository fields);
   the installation token and ``issues: write`` (D-58); the params and their
   bounds (D-82, refusal ``invalid_params``).
2. ``refuse`` — refusal checks (a)–(d) (D-92): ``pull_request``, ``closed``,
   ``linked_pr``, ``active_run``.
3. ``checkout`` — the link-protection sysctls as a ``run_event`` first
   (S-189, QA-189-01; spec v2.6 §8.7), then clone, materialize, repo gate
   (refusal ``repo_gate``), install, base gates, base restore (S-189). No
   issue changes before the repo gate passes (FR-5): the refusal reply is the
   only write until here.
4. ``claim`` — the claim comment, 👀, the post-claim race check and the
   ownership gate (S-188, D-54, D-81). With ``FIX_LOOP_ENABLED=0`` (Wave A),
   a confirmed claim then disposes "fix loop not yet enabled" (😕 plus the
   diagnosis) and the run ends ``succeeded``/``needs_review``.
5. ``fix`` — only when ``FIX_LOOP_ENABLED=1``. It runs the injected fix
   runner (Wave B, S-191 onward). This build has none, so the step disposes
   "the fix step is not available in this build" instead.

Every terminal path maps to one :class:`outcomes.RunResult` (spec §8.9). Only
``failed`` counts toward the breaker (D-20). Every ``needs_review`` and
``not_applicable`` result carries ``result.summary`` and ``result.reason``.

**Ownership gate (D-81).** The ``finally`` path (:func:`execute`) and the
SIGTERM backstop dispose only after the claim's post-check has confirmed
ownership, and at most once per run. A fault before that keeps the claim
comment and disposes nothing.

**Token refresh (S-185 residual).** GitHub calls take their token from a
:class:`TokenSource`, which calls ``credentials.refresh_if_stale`` and maps
its errors by ``exc.error_code``: ``PermissionMissing`` →
``GITHUB_PERMISSION_MISSING``, a mint failure → ``CREDENTIALS_UNAVAILABLE``.
A refresh failure that a best-effort call swallowed still fails the run.

**Heartbeat, stream close and backstop.** The steps run on a
:class:`RunWorker` thread while the entrypoint streams heartbeat chunks
(``heartbeat.run_with_heartbeat`` waits on :meth:`RunWorker.join`), so a long
install or gate never idles the AgentCore stream (issue #98). The worker owns
the run's terminal write; the entrypoint only relays. A consumer that closes
or cancels the stream mid-run ends the relay, not the run: the worker
finishes, notes the close in a ``run_event`` and reports its real outcome
(QA-190-01). The SIGTERM backstop runs the disposition (10 s budget) when
ownership is confirmed, then ``fail()`` with ``SIGNAL_TERMINATION``.

**Metrics** (FR-27): ``runs.metrics`` holds ``issue_number``,
``step_timings_ms`` (non-negative integer milliseconds per step) and, after
checkout, ``gates_base``.

Probe mode (S-182, D-70): a top-level ``__probe: true`` runs the spike
checks in ``probe.py`` only when ``ALLOW_PROBE=1`` is set on the runtime;
otherwise ``PROBE_REFUSED``.

Secrets (spec §12): every resolved secret is held in a :class:`SecretSet` in
this process's memory, never exported to ``os.environ``, and every message
leaving the process is scrubbed. The reporter does not capture the standard
``logging`` stream, so nothing reaches ``run_events`` without passing through
a module's scrubbed ``run_event`` call.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp

import outcomes
import signal_backstop
from agent_reporter import RunReporter
from checkout import WorkPaths, run_checkout
from claim import Claimer
from config import (
    HEARTBEAT_INTERVAL,
    MAX_LIFETIME,
    RUN_GRACE_SECONDS,
    Config,
    ConfigError,
    load_config,
)
from credentials import (
    CredentialError,
    GitHubSession,
    TokenContext,
    fetch_supabase_key,
    refresh_if_stale,
    resolve_github_session,
)
from disposition import Diagnosis, Disposer
from gates import SandboxLike
from heartbeat import HeartbeatResult, run_with_heartbeat, terminal_chunk
from issues import IssuesClient
from markers import canonical_run_id
from outcomes import RunResult
from params import ParamsError, parse_params
from probe import execute as execute_probe
from probe import is_probe_request, probe_allowed
from refusal import CheckOutcome, RunStatusReader, run_preflight, run_refusals
from run_link import RunLink
from safe_git import GitTools
from sandbox import Sandbox
from scrubber import SecretSet, scrub_all, scrub_exception
from signal_backstop import DISPOSITION_BUDGET_SECONDS, RunTarget, install_termination_backstop

log = logging.getLogger("bug_fix")


@contextlib.asynccontextmanager
async def _lifespan(_app: Any) -> AsyncIterator[None]:
    """App start: put the SIGTERM backstop on top of uvicorn's handler.

    uvicorn installs its own SIGTERM handler on the main thread
    (``Server.capture_signals``) before the lifespan starts, and runs the
    lifespan on that thread, so this install lands above it and chains to it:
    the backstop runs first, then uvicorn's graceful shutdown.
    """
    signal_backstop.install_process_backstop("app start")
    yield


app = BedrockAgentCoreApp(lifespan=_lifespan)

# Import time: ``python main.py`` imports this module on the main thread, so
# the backstop is in place before uvicorn starts. uvicorn saves it and
# restores it after its shutdown, then re-raises a captured SIGTERM: this
# handler runs again, finds the run already handled, and chains to SIG_DFL,
# which ends the process even with the (non-daemon) run worker still alive.
signal_backstop.install_process_backstop("import")

PROBE_REFUSED = "probe mode refused: ALLOW_PROBE is not set to 1 on the runtime"
FIX_UNAVAILABLE_REASON = "fix_unavailable"
FIX_UNAVAILABLE = "the fix step is not available in this build"

STEP_PREFLIGHT = "preflight"
STEP_REFUSE = "refuse"
STEP_CHECKOUT = "checkout"
STEP_CLAIM = "claim"
STEP_FIX = "fix"

FIX_LOOP_DISABLED_TRIED = (
    "The run checked the issue, cloned the repository, installed its dependencies "
    "and ran its base gates. The fix step is switched off on this runtime "
    "(FIX_LOOP_ENABLED=0), so no change was attempted."
)
FIX_UNAVAILABLE_TRIED = (
    "The run claimed this issue and prepared the repository, but this build has no "
    "fix runner, so no change was attempted."
)
FAULT_TRIED = "The run had claimed this issue. It proposed no change."


class InvalidPayloadError(ValueError):
    """The invocation payload is not a usable run request."""


def _fault_chunk(error_code: str, summary: str) -> dict:
    """The terminal chunk of a fault outside the steps (pre-run, probe refused).

    Built through :class:`outcomes.RunResult`, so it follows the same rule as
    every other fault: ``failed`` with its code and no outcome (DF-190-05).
    """
    return terminal_chunk(json.dumps(outcomes.failed(error_code, summary).terminal()))


def unwrap_payload(payload: Any) -> dict:
    """Return the run request, unwrapping ``{"prompt": "<json>"}`` once."""
    if isinstance(payload, dict) and set(payload) == {"prompt"}:
        try:
            payload = json.loads(payload["prompt"])
        except (TypeError, ValueError):
            raise InvalidPayloadError("prompt is not JSON") from None
    if not isinstance(payload, dict):
        raise InvalidPayloadError("payload is not an object")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise InvalidPayloadError("run_id is missing")
    return payload


# ---------------------------------------------------------------------------
# External boundaries (tests replace them through default_runtime)
# ---------------------------------------------------------------------------


def _no_remote(owner: str, repo: str) -> str | None:
    """Production clones ``https://github.com/<owner>/<repo>.git``."""
    return None


@dataclass
class Runtime:
    """The run's external boundaries. Production uses the defaults."""

    github_session: Any = None  # a requests.Session-like transport
    supabase_session: Any = None  # the v_runs transport (``requests``)
    sandbox: SandboxLike | None = None  # ``sandbox.Sandbox()`` when None
    paths: WorkPaths = field(default_factory=WorkPaths)
    git_tools: GitTools | None = None
    remote_url: Callable[[str, str], str | None] = _no_remote
    resolve_github: Callable[[str, str, str], GitHubSession] = resolve_github_session
    refresh: Callable[[TokenContext, str, int], TokenContext] = refresh_if_stale
    sysctl_base: str | None = None
    heartbeat_interval: float = float(HEARTBEAT_INTERVAL)
    # The fix step (Wave B). None: the step disposes FIX_UNAVAILABLE.
    fix_runner: Callable[[RunContext], RunResult] | None = None
    clock: Callable[[], float] = time.monotonic
    # The run's time budget in seconds; None: run_budget_seconds(payload).
    run_budget: float | None = None


def default_runtime() -> Runtime:
    return Runtime()


# How long past its deadline the relay waits for a worker stuck in a step
# before it ends the run itself (the worker checks the deadline between steps).
OVERDUE_SLACK_SECONDS = DISPOSITION_BUDGET_SECONDS


def _positive_seconds(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def run_budget_seconds(request: Mapping[str, Any]) -> float:
    """The run's time budget: ``max_runtime_seconds - grace_seconds``.

    Both come from the payload when it carries them as positive integers (the
    run row's snapshot), else from the runtime's ``MAX_LIFETIME`` and the
    seed's ``grace_seconds``. Ending here leaves the grace for the terminal
    write and the disposition, before the reaper's own timeout.
    """
    max_runtime = _positive_seconds(request.get("max_runtime_seconds")) or MAX_LIFETIME
    grace = _positive_seconds(request.get("grace_seconds")) or RUN_GRACE_SECONDS
    return float(max(0, max_runtime - grace))


_REPORTER_WRITES = frozenset(
    {
        "start",
        "succeed",
        "fail",
        "step",
        "_finish_step",
        "log",
        "info",
        "warn",
        "error",
        "debug",
        "flush",
        "artifact",
    }
)
# New rows a run must not get once it is terminal (QA gap 5).
_REPORTER_EVENTS = frozenset({"step", "log", "info", "warn", "error", "debug", "artifact"})


class RunHandle:
    """The run's reporter, one writer at a time, plus its stop flag (QA gap 6).

    ``RunReporter`` is not thread-safe, and three threads can write to it: the
    run worker, the entrypoint, and the SIGTERM handler (with its disposition
    thread). Every write goes through :attr:`write_lock`, which the backstop
    also takes (``signal_backstop.handle_termination``), so a SIGTERM inside a
    terminal write waits for it: one terminal write in every interleaving.
    It is re-entrant: a signal handled on a thread that is already writing
    doesn't deadlock. Once the run is terminal, new events, steps and
    artifacts are dropped. The vendored reporter stays unchanged.

    :meth:`request_stop` tells the worker to stop between steps; whoever ends
    the run while the worker is alive (the backstop, the entrypoint, the
    deadline) calls it.
    """

    def __init__(self, reporter: Any) -> None:
        self._reporter = reporter
        self.write_lock = threading.RLock()
        self._stop = threading.Event()

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._reporter, name)
        if name not in _REPORTER_WRITES:
            return attr

        def locked(*args: Any, **kwargs: Any) -> Any:
            with self.write_lock:
                if name in _REPORTER_EVENTS and self._reporter._terminal:
                    return None
                return attr(*args, **kwargs)

        return locked

    @property
    def _terminal(self) -> bool:
        return bool(self._reporter._terminal)

    def request_stop(self) -> None:
        self._stop.set()

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()


class TokenSource:
    """The installation token for every GitHub call, refreshed when stale.

    Calls ``refresh(ctx, pem, app_id)`` (``credentials.refresh_if_stale``) on
    each use. A refreshed token is registered with the scrubber. The first
    refresh error is kept in :attr:`failure` and raised again on every later
    use, so a call that swallowed it (a best-effort reply) can't hide it; the
    run maps it by ``exc.error_code``.
    """

    def __init__(
        self,
        session: GitHubSession,
        refresh: Callable[[TokenContext, str, int], TokenContext],
        secrets: SecretSet,
    ) -> None:
        self.ctx = session.token
        self._pem = session.pem
        self._refresh = refresh
        self._secrets = secrets
        self._lock = threading.Lock()
        self._mints = 0
        self.failure: CredentialError | None = None

    def __call__(self) -> str:
        with self._lock:
            if self.failure is not None:
                raise self.failure
            app_id = self.ctx.app_id
            if app_id is None:
                self.failure = CredentialError("INVALID_APP_ID", "the installation has no App id")
                raise self.failure
            try:
                new = self._refresh(self.ctx, self._pem, app_id)
            except CredentialError as exc:
                self.failure = exc
                raise
            if new.token != self.ctx.token:
                self._mints += 1
                self._secrets.add(f"GITHUB_INSTALLATION_TOKEN_{self._mints}", new.token)
            self.ctx = new
            return new.token


# ---------------------------------------------------------------------------
# The run's state
# ---------------------------------------------------------------------------


@dataclass
class RunContext:
    cfg: Config
    request: dict
    run: Any
    secrets: SecretSet
    runtime: Runtime
    supabase_key: str = field(repr=False)
    run_id: str = ""
    owner: str = ""
    repo: str = ""
    base_branch: str = ""
    run_link: RunLink | None = None
    token_source: TokenSource | None = field(default=None, repr=False)
    client: IssuesClient | None = field(default=None, repr=False)
    pre: CheckOutcome | None = field(default=None, repr=False)
    run_status: RunStatusReader | None = field(default=None, repr=False)
    issue_number: int | None = None
    trigger_comment_id: int | None = None
    app_id: int | None = None
    disposer: Disposer | None = field(default=None, repr=False)
    disposition_attempted: bool = False
    timings: dict[str, int] = field(default_factory=dict)
    gates_base: dict[str, dict[str, Any]] | None = None
    # Called on the worker thread just before the terminal report (RunWorker).
    on_report: Callable[[], None] | None = field(default=None, repr=False)
    # The run's deadline on runtime.clock; None: no deadline.
    deadline: float | None = None
    # The run as the SIGTERM backstop's registry holds it (cleared at the end).
    backstop_target: RunTarget | None = field(default=None, repr=False)

    def stopped(self) -> bool:
        """The run was ended by someone else, or asked to stop (QA gap 5)."""
        run = self.run
        stop = getattr(run, "stop_requested", False) is True
        return stop or getattr(run, "_terminal", False) is True

    def time_left(self) -> float | None:
        if self.deadline is None:
            return None
        return self.deadline - self.runtime.clock()

    def event(self, level: str, message: str, **data: Any) -> None:
        """A scrubbed ``run_event``; a reporting fault never changes the outcome."""
        message = scrub_all(message, self.secrets)
        getattr(log, "warning" if level == "warn" else level)("%s", message)
        try:
            getattr(self.run, level)(message, **data)
        except Exception:  # noqa: BLE001
            log.warning("run_event could not be recorded")

    def metrics(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "issue_number": self.issue_number,
            "step_timings_ms": dict(self.timings),
        }
        if self.gates_base is not None:
            out["gates_base"] = self.gates_base
        return out

    def backstop_disposition(self) -> Callable[[], object] | None:
        """The SIGTERM backstop's disposition: ``None`` before confirmed ownership."""
        disposer = self.disposer
        return disposer.backstop_action() if disposer is not None else None


def _issue_of(raw_params: object) -> int | None:
    """``issue_number`` when it alone is valid, for the metrics."""
    if not isinstance(raw_params, Mapping) or "issue_number" not in raw_params:
        return None
    try:
        return parse_params({"issue_number": raw_params["issue_number"]}).issue_number
    except ParamsError:
        return None


def wire_claim(
    *,
    client: IssuesClient,
    issue_number: int,
    run_id: str,
    app_id: int,
    trigger_comment_id: int | None,
    run_status: Callable[..., Mapping[str, str]],
    run: Any,
    run_link: RunLink | None,
    secrets: SecretSet,
    panel_origin: str | None,
) -> tuple[Claimer, Disposer]:
    """The claim and its disposition, wired as a run uses them (S-188 QA gap 1).

    The :class:`claim.Claimer` gets the real :class:`disposition.Disposer` and
    the configured run link, so a won race confirms ownership on the very
    object the ``finally`` path and the SIGTERM backstop dispose through. Both
    get ``panel_origin``, the configured ``PANEL_BASE_URL``, so each comment
    checks the link's host against the configuration (DF-190-12).
    Wave A has no board client (``projects.py`` is S-199), so no board call is
    wired.
    """
    disposer = Disposer(
        client=client,
        issue_number=issue_number,
        run_id=run_id,
        app_id=app_id,
        trigger_comment_id=trigger_comment_id,
        secrets=secrets,
        run=run,
        run_link=run_link,
        panel_origin=panel_origin,
    )
    claimer = Claimer(
        client=client,
        issue_number=issue_number,
        run_id=run_id,
        app_id=app_id,
        trigger_comment_id=trigger_comment_id,
        run_status=run_status,
        run=run,
        run_link=run_link,
        panel_origin=panel_origin,
        secrets=secrets,
        disposer=disposer,
    )
    return claimer, disposer


# ---------------------------------------------------------------------------
# The disposition after confirmed ownership
# ---------------------------------------------------------------------------


def dispose_needs_review(
    ctx: RunContext, reason: str, why: str, tried: str, diffstat: str | None = None
) -> RunResult:
    """Apply this run's disposition and end ``succeeded``/``needs_review``.

    Only after confirmed ownership (D-81). A GitHub fault on the disposition
    ends ``failed`` with its D-67 code; the ``finally`` path never retries it.
    """
    disposer = ctx.disposer
    if disposer is None or not disposer.ownership_confirmed:
        return outcomes.failed(
            outcomes.UNHANDLED_ERROR, "UNHANDLED_ERROR: disposition without confirmed ownership"
        )
    if ctx.stopped():
        # The run was ended elsewhere (the backstop disposes for it).
        return _stopped_result()
    ctx.disposition_attempted = True
    try:
        done = disposer.dispose(Diagnosis(why=why, tried=tried, diffstat=diffstat))
    except Exception as exc:  # noqa: BLE001 — mapped, scrubbed
        result = outcomes.from_exception(exc, ctx.secrets)
        ctx.event("error", f"disposition failed: {result.summary}")
        return result
    ctx.event("info", f"disposition {done.status}: {why}")
    return outcomes.needs_review(reason, scrub_all(why, ctx.secrets))


def _finally_dispose(ctx: RunContext, result: RunResult) -> None:
    """The ``finally`` path: a fault after confirmed ownership still disposes."""
    disposer = ctx.disposer
    if disposer is None or not disposer.ownership_confirmed or ctx.disposition_attempted:
        return
    if ctx.stopped():
        return
    ctx.disposition_attempted = True
    why = f"the run stopped on an error ({result.error_code})"
    try:
        done = disposer.dispose(Diagnosis(why=why, tried=FAULT_TRIED))
    except Exception as exc:  # noqa: BLE001 — best effort; the fault stands
        ctx.event(
            "warn", f"disposition after the fault failed: {scrub_exception(exc, ctx.secrets)}"
        )
        return
    ctx.event("info", f"disposition {done.status} after {result.error_code}")


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


_REPOSITORY_FIELDS = ("repository_org", "repository_name", "base_branch")


def _payload_problems(request: Mapping[str, Any]) -> list[str]:
    """What makes the payload unusable, naming fields and never their values.

    ``run_id`` must be a UUID (QA-190-02): every marker and run link is built
    from it, so a run that can't build them stops here, before any GitHub
    call. A repository field that is absent, ``null`` or blank is "missing";
    one that is present but not a string "has the wrong type" (QA gap 5).
    """
    problems: list[str] = []
    try:
        canonical_run_id(request.get("run_id"))  # type: ignore[arg-type]
    except ValueError:
        problems.append("run_id is not a UUID")
    for name in _REPOSITORY_FIELDS:
        value = request.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.append(f"{name} missing from the payload")
        elif not isinstance(value, str):
            problems.append(f"{name} has the wrong type (expected a string)")
    return problems


def _preflight(ctx: RunContext) -> RunResult | None:
    rt = ctx.runtime
    raw_params = ctx.request.get("params")
    ctx.issue_number = _issue_of(raw_params)
    problems = _payload_problems(ctx.request)
    if problems:
        return outcomes.failed("INVALID_PAYLOAD", f"INVALID_PAYLOAD: {'; '.join(problems)}")

    def resolve() -> TokenContext:
        session = rt.resolve_github(ctx.owner, ctx.cfg.supabase_url, ctx.supabase_key)
        ctx.secrets.add("GITHUB_APP_PRIVATE_KEY", session.pem)
        ctx.secrets.add("GITHUB_INSTALLATION_TOKEN", session.token.token)
        ctx.token_source = TokenSource(session, rt.refresh, ctx.secrets)
        return session.token

    def client_token(_token: TokenContext) -> Callable[[], str]:
        assert ctx.token_source is not None  # set by resolve()
        return ctx.token_source

    pre = run_preflight(
        run_id=ctx.run_id,
        owner=ctx.owner,
        repo=ctx.repo,
        raw_params=raw_params,
        resolve_token=resolve,
        session=rt.github_session,
        run=ctx.run,
        run_link=ctx.run_link,
        panel_origin=ctx.cfg.panel_base_url,
        secrets=ctx.secrets,
        client_token=client_token,
    )
    ctx.pre = pre
    ctx.client = pre.client
    if pre.token is not None:
        ctx.app_id = pre.token.app_id
    if pre.params is not None:
        ctx.issue_number = pre.params.issue_number
        ctx.trigger_comment_id = pre.params.trigger_comment_id
    return outcomes.from_check(pre)


def _refuse(ctx: RunContext) -> RunResult | None:
    assert ctx.pre is not None
    ctx.run_status = RunStatusReader(
        ctx.cfg.supabase_url, ctx.supabase_key, session=ctx.runtime.supabase_session
    )
    out = run_refusals(
        ctx.pre,
        run_id=ctx.run_id,
        run_status=ctx.run_status,
        run=ctx.run,
        run_link=ctx.run_link,
        panel_origin=ctx.cfg.panel_base_url,
        secrets=ctx.secrets,
    )
    return outcomes.from_check(out)


def _checkout(ctx: RunContext) -> RunResult | None:
    rt = ctx.runtime
    assert ctx.client is not None and ctx.token_source is not None
    assert ctx.issue_number is not None
    out = run_checkout(
        run_id=ctx.run_id,
        owner=ctx.owner,
        repo=ctx.repo,
        base_branch=ctx.base_branch,
        issue_number=ctx.issue_number,
        sandbox=rt.sandbox if rt.sandbox is not None else Sandbox(),
        issues=ctx.client,
        secrets=ctx.secrets,
        token=ctx.token_source(),
        run=ctx.run,
        run_link=ctx.run_link,
        panel_origin=ctx.cfg.panel_base_url,
        paths=rt.paths,
        tools=rt.git_tools,
        remote_url=rt.remote_url(ctx.owner, ctx.repo),
        sysctl_base=rt.sysctl_base,
    )
    if out.base_gates is not None:
        ctx.gates_base = {
            name: {"pass": gate["pass"], "exit_code": gate["exit_code"]}
            for name, gate in out.base_gates.to_dict().items()
        }
    return outcomes.from_checkout(out)


def _claim(ctx: RunContext) -> RunResult | None:
    assert ctx.client is not None and ctx.run_status is not None
    assert ctx.issue_number is not None and ctx.app_id is not None
    claimer, disposer = wire_claim(
        client=ctx.client,
        issue_number=ctx.issue_number,
        run_id=ctx.run_id,
        app_id=ctx.app_id,
        trigger_comment_id=ctx.trigger_comment_id,
        run_status=ctx.run_status,
        run=ctx.run,
        run_link=ctx.run_link,
        secrets=ctx.secrets,
        panel_origin=ctx.cfg.panel_base_url,
    )
    ctx.disposer = disposer
    result = outcomes.from_claim(claimer.claim())
    if result is not None:
        return result
    if not ctx.cfg.fix_loop_enabled:
        ctx.event("info", "FIX_LOOP_ENABLED is 0: disposing without a fix step")
        return dispose_needs_review(
            ctx,
            outcomes.FIX_LOOP_DISABLED_REASON,
            outcomes.FIX_LOOP_DISABLED,
            FIX_LOOP_DISABLED_TRIED,
        )
    return None


def _fix(ctx: RunContext) -> RunResult | None:
    runner = ctx.runtime.fix_runner
    if runner is None:
        ctx.event("warn", f"FIX_LOOP_ENABLED is 1, but {FIX_UNAVAILABLE}")
        return dispose_needs_review(
            ctx, FIX_UNAVAILABLE_REASON, FIX_UNAVAILABLE, FIX_UNAVAILABLE_TRIED
        )
    return runner(ctx)


def _finish_step(run: Any, step: Any, status: str, error: str | None) -> None:
    """Close a ``run_steps`` row as ``succeeded`` or ``failed`` with a scrubbed
    message, never a traceback (``RunReporter``'s own ``_Step`` would record
    one; the vendored SDK stays unchanged)."""
    if step is None:
        return
    try:
        run._finish_step(step.id, status, error=error)
    except Exception:  # noqa: BLE001 — reporting never changes the outcome
        log.warning("run_steps row could not be closed")


def _run_step(
    ctx: RunContext, name: str, body: Callable[[RunContext], RunResult | None]
) -> RunResult | None:
    """Run one step: a ``run_steps`` row, its timing, its result (or ``None``)."""
    clock = ctx.runtime.clock
    started = clock()
    try:
        step = ctx.run.step(name)
    except Exception:  # noqa: BLE001 — reporting never changes the outcome
        step = None
    result: RunResult | None
    try:
        result = body(ctx)
    except Exception as exc:  # noqa: BLE001 — mapped by its code, scrubbed
        result = outcomes.from_exception(exc, ctx.secrets)
        ctx.event("error", f"step {name} failed: {result.summary}")
    failure = ctx.token_source.failure if ctx.token_source is not None else None
    if failure is not None and (result is None or result.status != outcomes.FAILED):
        # A best-effort call swallowed a refresh error: it still fails the run.
        result = outcomes.from_exception(failure, ctx.secrets)
        ctx.event("error", f"step {name}: {result.summary}")
    ctx.timings[name] = max(0, int(round((clock() - started) * 1000)))
    failed = result is not None and result.status == outcomes.FAILED
    _finish_step(
        ctx.run,
        step,
        "failed" if failed else "succeeded",
        result.summary if failed and result is not None else None,
    )
    return result


def _steps(ctx: RunContext) -> RunResult:
    plan: list[tuple[str, Callable[[RunContext], RunResult | None]]] = [
        (STEP_PREFLIGHT, _preflight),
        (STEP_REFUSE, _refuse),
        (STEP_CHECKOUT, _checkout),
        (STEP_CLAIM, _claim),
    ]
    if ctx.cfg.fix_loop_enabled:
        plan.append((STEP_FIX, _fix))
    for name, body in plan:
        if ctx.stopped():
            return _stopped_result()
        left = ctx.time_left()
        if left is not None and left <= 0:
            return _overdue(ctx, name)
        result = _run_step(ctx, name, body)
        if result is not None:
            return result
    # Only a fix runner that returns None ends here: there is no PR path yet.
    return dispose_needs_review(
        ctx, FIX_UNAVAILABLE_REASON, "the fix step ended without a result", FAULT_TRIED
    )


def _report(ctx: RunContext, result: RunResult) -> None:
    if ctx.on_report is not None:
        try:
            ctx.on_report()
        except Exception:  # noqa: BLE001 — a note never changes the outcome
            log.warning("pre-report note failed")
    try:
        result.report(ctx.run, metrics=ctx.metrics())
    except Exception as exc:  # noqa: BLE001 — the terminal chunk still carries it
        log.error("terminal report failed: %s", scrub_exception(exc, ctx.secrets))


# How long a stopped worker waits for the run's terminal row before it writes
# one itself: the backstop's whole budget, plus its fail() floor.
STOP_WAIT_SECONDS = DISPOSITION_BUDGET_SECONDS + 2.0


def _wait_until_terminal(run: Any, timeout: float) -> bool:
    end = time.monotonic() + timeout
    while getattr(run, "_terminal", False) is not True:
        if time.monotonic() >= end:
            return False
        time.sleep(0.02)
    return True


def _stopped_result() -> RunResult:
    return outcomes.failed(
        "SIGNAL_TERMINATION", "SIGNAL_TERMINATION: the run was ended before it finished"
    )


def _overdue(ctx: RunContext, step: str) -> RunResult:
    """Past the deadline between steps: ``failed``/``RUNTIME_TIMEOUT``.

    The ``finally`` path still disposes when ownership is confirmed (D-81).
    """
    result = outcomes.failed(
        outcomes.RUNTIME_TIMEOUT,
        f"RUNTIME_TIMEOUT: the run reached its deadline before the {step} step",
    )
    ctx.event("error", result.summary)
    return result


def execute(ctx: RunContext) -> RunResult:
    """Run every step, then the ``finally`` path, then report. Never raises.

    A run ended elsewhere (the backstop, the entrypoint, the relay's deadline)
    stops at the next step boundary and writes nothing more (QA gap 5).
    """
    try:
        result = _steps(ctx)
    except Exception as exc:  # noqa: BLE001 — mapped, scrubbed
        result = outcomes.from_exception(exc, ctx.secrets)
    if ctx.stopped():
        # Whoever stopped the run writes its terminal row; if nobody does
        # (a backstop that gave up on the write lock), the worker reports, so
        # the run never stays ``running``.
        if _wait_until_terminal(ctx.run, STOP_WAIT_SECONDS):
            log.warning("the run was ended elsewhere; the worker stops without a report")
        else:
            log.error("the run was stopped but not ended; the worker reports it")
            _report(ctx, result)
        return result
    if result.status == outcomes.FAILED:
        _finally_dispose(ctx, result)
    _report(ctx, result)
    return result


class RunWorker:
    """:func:`execute` on its own thread, started at once (QA-190-01).

    **Why.** AgentCore streams the entrypoint's chunks to the caller, and the
    caller can go away mid-run: the panel resolves ``invokeAgentRuntime`` once
    the call is accepted, and the webhook path aborts it on a timeout. The
    async generator then gets ``GeneratorExit`` (``aclose()``) or
    ``CancelledError`` at its current ``await``/``yield``. The run's outcome
    must not depend on that, so ownership is split:

    - **The worker owns the run.** It runs every step, the ``finally``
      disposition, and the one terminal write (``execute()`` → ``_report``).
      It starts here, on a plain thread, before the first chunk, so no
      cancellation can stop it from starting or finishing; a cancelled
      ``asyncio`` future can only stop *waiting* for a thread, never the
      thread itself.
    - **The entrypoint only relays.** :meth:`join` is what
      ``run_with_heartbeat`` waits on, so the heartbeat keeps the stream
      alive while the consumer listens. A close or cancel ends the relay
      only: the entrypoint calls :meth:`stream_closed` and re-raises,
      without a terminal write.
    - **Stopping for real** is the SIGTERM backstop's job
      (``signal_backstop``): ``failed``/``SIGNAL_TERMINATION``, scrubbed,
      after the disposition when ownership is confirmed (D-81).

    The worker is not a daemon thread: the process doesn't exit under a run
    that is still reporting. The run's deadline (:meth:`join_until_deadline`)
    and SIGTERM bound it.

    **Busy while it runs.** The SDK's ``/ping`` says ``HealthyBusy`` only
    while a task registered with ``app.add_async_task`` is open. The worker
    registers its whole lifetime, so a session whose stream the panel closed
    is not reclaimed as idle (``IDLE_SESSION_TIMEOUT``) mid-run (QA gap 2).

    :meth:`stream_closed` only sets a field; the worker writes the
    ``run_event`` itself before its terminal report. Every reporter write
    goes through :class:`RunHandle`'s lock either way.
    """

    def __init__(self, ctx: RunContext) -> None:
        self._ctx = ctx
        self._done = threading.Event()
        self._result: RunResult | None = None
        self._error: BaseException | None = None
        ctx.on_report = self._note_close
        self._closed: str | None = None
        self._busy: int | None = None
        try:
            self._busy = app.add_async_task("bug-fix-run", {"run_id": ctx.run_id})
        except Exception as exc:  # noqa: BLE001 — a missing busy mark never stops a run
            ctx.event("error", f"the session could not be marked busy ({type(exc).__name__})")
        self._thread = threading.Thread(target=self._run, name="bug-fix-run", daemon=False)
        self._thread.start()

    @property
    def running(self) -> bool:
        return not self._done.is_set()

    @property
    def result(self) -> RunResult | None:
        """The run's result once the worker finished it (it reported), else None."""
        return self._result if self._done.is_set() else None

    def stop(self) -> None:
        """Stop at the next step boundary: the run was ended elsewhere (QA gap 5)."""
        stop = getattr(self._ctx.run, "request_stop", None)
        if callable(stop):
            stop()

    def stream_closed(self, how: str) -> None:
        """The consumer went away (``GeneratorExit``, ``CancelledError``, a relay fault)."""
        self._closed = how

    def _note_close(self) -> None:
        if self._closed is not None:
            self._ctx.event(
                "warn",
                f"the invoke stream closed mid-run ({self._closed}); the run finished "
                "the steps and reports its own outcome",
            )

    def _run(self) -> None:
        try:
            self._result = execute(self._ctx)
        except BaseException as exc:  # noqa: BLE001 — handed to join()
            self._error = exc
        finally:
            if self._busy is not None:
                with contextlib.suppress(Exception):
                    app.complete_async_task(self._busy)
            signal_backstop.clear_active_run(self._ctx.backstop_target)
            self._done.set()

    def join(self, timeout: float | None = None) -> RunResult:
        """Wait for the run; its result, or what it raised (execute() never
        raises an ``Exception``; a ``BaseException`` means the process is
        dying, and is passed on as-is). :class:`RunOverdue` when it is still
        running after ``timeout`` seconds."""
        if not self._done.wait(timeout):
            raise RunOverdue()
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result

    def join_until_deadline(self) -> RunResult:
        """:meth:`join`, bounded by the run's deadline plus a slack for a worker
        that is finishing its step (it checks the deadline between steps)."""
        left = self._ctx.time_left()
        return self.join(None if left is None else max(0.0, left) + OVERDUE_SLACK_SECONDS)


class RunOverdue(Exception):
    """The run worker is still running past the run's deadline."""


def _end_overdue_run(ctx: RunContext, worker: RunWorker) -> RunResult:
    """The relay's deadline (QA gap 7): the worker is stuck in a step.

    Ends the run ``failed``/``RUNTIME_TIMEOUT`` the way the backstop ends it
    on SIGTERM: the worker stops at its next boundary, the disposition runs
    (10 s budget) when ownership is confirmed (D-81), then ``fail()``. A run
    that turned terminal meanwhile keeps its own result.
    """
    finished = worker.result
    if finished is not None:  # it reported just in time: its result stands
        return finished
    worker.stop()
    summary = "RUNTIME_TIMEOUT: the run passed its deadline while a step was still running"
    signal_backstop.handle_termination(
        lambda: ctx.run,
        ctx.secrets.values,
        ctx.backstop_disposition,
        "deadline",
        DISPOSITION_BUDGET_SECONDS,
        error_code=outcomes.RUNTIME_TIMEOUT,
        headline=summary,
    )
    return outcomes.failed(outcomes.RUNTIME_TIMEOUT, summary)


# ---------------------------------------------------------------------------
# The entrypoint
# ---------------------------------------------------------------------------


@app.entrypoint
async def invoke(payload: Any, context: Any) -> AsyncIterator[dict]:
    secrets = SecretSet()

    try:
        cfg = load_config()
    except ConfigError as exc:
        # The message names the variable, never its value.
        log.error("Configuration error: %s", exc)
        yield _fault_chunk("CONFIG_INVALID", str(exc))
        return

    try:
        request = unwrap_payload(payload)
    except InvalidPayloadError as exc:
        log.error("Invalid payload: %s", exc)
        yield _fault_chunk("INVALID_PAYLOAD", str(exc))
        return

    try:
        supabase_key = fetch_supabase_key(cfg.supabase_key_secret_id)
    except CredentialError as exc:
        # Spec §8.9: secrets / token mint -> failed / CREDENTIALS_UNAVAILABLE.
        summary = scrub_all(f"credentials unavailable ({exc.code})", secrets)
        log.error("%s", summary)
        yield _fault_chunk("CREDENTIALS_UNAVAILABLE", summary)
        return
    secrets.add("SUPABASE_SERVICE_ROLE_KEY", supabase_key)

    run = RunHandle(
        RunReporter(
            supabase_url=cfg.supabase_url,
            supabase_key=supabase_key,
            run_id=request["run_id"],
            params=request,
            capture_logging=False,
        )
    )
    runtime = default_runtime()
    budget = runtime.run_budget if runtime.run_budget is not None else run_budget_seconds(request)
    ctx = RunContext(
        cfg=cfg,
        request=request,
        run=run,
        secrets=secrets,
        runtime=runtime,
        supabase_key=supabase_key,
        run_id=request["run_id"],
        owner=str(request.get("repository_org") or ""),
        repo=str(request.get("repository_name") or ""),
        base_branch=str(request.get("base_branch") or ""),
        run_link=cfg.run_link(request["run_id"]),
        deadline=runtime.clock() + budget,
    )
    probe_summary: dict | None = None
    result: RunResult | None = None
    worker: RunWorker | None = None
    relay_failed = False
    # Not ``with run:``. RunReporter.__exit__ marks the run ``failed`` with the
    # exception's class name and its traceback for *any* exception, including
    # the GeneratorExit/CancelledError of a consumer that went away while the
    # worker still runs (QA-190-01). The lifecycle is explicit instead: start()
    # here, the terminal write by whoever owns the outcome (see RunWorker).
    run.start()  # status running (the "started" report)
    target = install_termination_backstop(lambda: run, secrets.values, ctx.backstop_disposition)
    if isinstance(target, RunTarget):
        ctx.backstop_target = target
        if not target.installed:
            # Loud, never swallowed: without it a SIGTERM ends the run by the reaper.
            ctx.event("error", f"the SIGTERM backstop is not installed: {target.reason}")
    try:
        if is_probe_request(request):
            if not probe_allowed():
                # D-70: no check runs; the run ends with the reason.
                log.warning("%s", PROBE_REFUSED)
                run.fail("PROBE_REFUSED", PROBE_REFUSED)
                yield _fault_chunk("PROBE_REFUSED", PROBE_REFUSED)
                return
            probe_summary = execute_probe(run, cfg, secrets, supabase_key)
            run.succeed("not_applicable", result=probe_summary)
        else:
            ctx.event("info", f"bug-fix run started for {ctx.owner}/{ctx.repo}")
            worker = RunWorker(ctx)
            async for item in run_with_heartbeat(
                worker.join_until_deadline, interval=ctx.runtime.heartbeat_interval
            ):
                if isinstance(item, HeartbeatResult):
                    if isinstance(item.error, RunOverdue):
                        result = await asyncio.to_thread(_end_overdue_run, ctx, worker)
                    elif item.error is not None:
                        raise item.error
                    else:
                        result = item.value
                else:
                    yield item
    except (GeneratorExit, asyncio.CancelledError) as exc:
        # The consumer closed or cancelled the stream. That ends this relay,
        # not the run: the worker finishes the steps and writes the terminal
        # result itself, and notes the close in a run_event (QA-190-01).
        if worker is not None:
            worker.stream_closed(type(exc).__name__)
        log.warning(
            "invoke stream %s; the run %s",
            type(exc).__name__,
            "continues and reports its own outcome"
            if worker is not None and worker.running
            else "had already reported",
        )
        raise
    except Exception as exc:  # noqa: BLE001 — reported, scrubbed, never re-raised
        message = scrub_exception(exc, secrets)
        if worker is not None and (worker.running or worker.result is not None):
            # The relay broke, not the run: the worker owns the terminal
            # write, as on a stream close. Only log (and note it in the run).
            log.error("invoke relay failed (%s); the run reports its own outcome", message)
            worker.stream_closed(f"the relay failed: {type(exc).__name__}")
            relay_failed = True
        else:
            # No worker, or one that died without reporting.
            log.error("Unhandled error: %s", message)
            # Reported here, scrubbed: no traceback ever reaches run_events.
            run.fail("UNHANDLED_ERROR", message, metrics=ctx.metrics())
            yield terminal_chunk(json.dumps(outcomes.failed("UNHANDLED_ERROR", message).terminal()))
            return
    except BaseException as exc:
        # The process is stopping (SystemExit, KeyboardInterrupt, a signal
        # re-raised): end the run with the closed-set SIGNAL_TERMINATION and a
        # scrubbed message, unless it is already terminal (the SIGTERM
        # backstop got there first). fail() is a no-op on a terminal run. A
        # worker still alive stops at its next step boundary first, so it
        # makes no GitHub write and no event on the ended run (QA gap 5).
        if worker is not None and worker.running:
            worker.stop()
        run.fail(
            "SIGNAL_TERMINATION",
            scrub_all(f"the run stopped on {type(exc).__name__}", secrets),
            metrics=ctx.metrics(),
        )
        raise
    finally:
        if worker is None:  # else the worker clears it when it ends
            signal_backstop.clear_active_run(ctx.backstop_target)

    if relay_failed:
        assert worker is not None
        result = await _await_worker(ctx, worker)
    if probe_summary is not None:
        out: dict[str, Any] = {
            "status": "succeeded",
            "outcome": "not_applicable",
            "summary": str(probe_summary.get("summary", "probe")),
            "probe": probe_summary,
        }
        yield terminal_chunk(json.dumps(out))
        return
    assert result is not None  # execute() always returns a result
    yield terminal_chunk(json.dumps(result.terminal()))


async def _await_worker(ctx: RunContext, worker: RunWorker) -> RunResult:
    """After a relay fault: wait (bounded) for the worker's own result.

    The worker reports its own terminal row; this only fetches the result for
    the stream's terminal chunk. Past the deadline, the run ends as overdue.
    """
    try:
        return await asyncio.to_thread(worker.join_until_deadline)
    except RunOverdue:
        return await asyncio.to_thread(_end_overdue_run, ctx, worker)


# uvicorn's shutdown waits for open connections, and a run's stream is one.
# After a SIGTERM the backstop has already written the terminal row, so the
# wait is bounded: past it, uvicorn cancels the stream and the process ends.
SHUTDOWN_WAIT_SECONDS = 5


def serve(port: int = 8080) -> None:
    """Run the server (``python main.py``); the backstop is on top once it starts."""
    app.run(port=port, timeout_graceful_shutdown=SHUTDOWN_WAIT_SECONDS)


if __name__ == "__main__":
    serve()
