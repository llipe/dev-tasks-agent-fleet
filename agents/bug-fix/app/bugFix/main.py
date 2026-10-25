"""
bug-fix agent — AgentCore entrypoint and step orchestration
(S-190; spec §4, §8.2–§8.9, §13; FR-5, FR-25–FR-27; D-20, D-58, D-61, D-67,
D-81, D-92, D-94, D-112).

Payload (spec §6, D-60): ``{run_id, repository_org, repository_name,
base_branch, params}``, optionally wrapped as ``{"prompt": "<json>"}``.

**Steps.** Each is one ``run_steps`` entry with ``run_events`` at its
decisions (FR-25):

1. ``preflight`` — the link-protection sysctls as a ``run_event`` (S-189,
   QA-189-01); the installation token and ``issues: write`` (D-58); the
   params and their bounds (D-82, refusal ``invalid_params``).
2. ``refuse`` — refusal checks (a)–(d) (D-92): ``pull_request``, ``closed``,
   ``linked_pr``, ``active_run``.
3. ``checkout`` — clone, materialize, repo gate (refusal ``repo_gate``),
   install, base gates, base restore (S-189). No issue changes before the repo
   gate passes (FR-5): the refusal reply is the only write until here.
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

**Heartbeat and backstop.** The steps run in a worker thread under
``heartbeat.run_with_heartbeat`` while the entrypoint streams heartbeat
chunks, so a long install or gate never idles the AgentCore stream (issue
#98). The SIGTERM backstop runs the disposition (10 s budget) when ownership
is confirmed, then ``fail()``.

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

import json
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp

import outcomes
from agent_reporter import RunReporter
from checkout import WorkPaths, record_link_protection, run_checkout
from claim import Claimer
from config import HEARTBEAT_INTERVAL, Config, ConfigError, load_config
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
from signal_backstop import install_termination_backstop

log = logging.getLogger("bug_fix")

app = BedrockAgentCoreApp()

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


def default_runtime() -> Runtime:
    return Runtime()


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
    record_link_protection(ctx.run, ctx.secrets, rt.sysctl_base)
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
        result = _run_step(ctx, name, body)
        if result is not None:
            return result
    # Only a fix runner that returns None ends here: there is no PR path yet.
    return dispose_needs_review(
        ctx, FIX_UNAVAILABLE_REASON, "the fix step ended without a result", FAULT_TRIED
    )


def _report(ctx: RunContext, result: RunResult) -> None:
    try:
        result.report(ctx.run, metrics=ctx.metrics())
    except Exception as exc:  # noqa: BLE001 — the terminal chunk still carries it
        log.error("terminal report failed: %s", scrub_exception(exc, ctx.secrets))


def execute(ctx: RunContext) -> RunResult:
    """Run every step, then the ``finally`` path, then report. Never raises."""
    try:
        result = _steps(ctx)
    except Exception as exc:  # noqa: BLE001 — mapped, scrubbed
        result = outcomes.from_exception(exc, ctx.secrets)
    if result.status == outcomes.FAILED:
        _finally_dispose(ctx, result)
    _report(ctx, result)
    return result


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

    run = RunReporter(
        supabase_url=cfg.supabase_url,
        supabase_key=supabase_key,
        run_id=request["run_id"],
        params=request,
        capture_logging=False,
    )
    ctx = RunContext(
        cfg=cfg,
        request=request,
        run=run,
        secrets=secrets,
        runtime=default_runtime(),
        supabase_key=supabase_key,
        run_id=request["run_id"],
        owner=str(request.get("repository_org") or ""),
        repo=str(request.get("repository_name") or ""),
        base_branch=str(request.get("base_branch") or ""),
        run_link=cfg.run_link(request["run_id"]),
    )
    probe_summary: dict | None = None
    result: RunResult | None = None
    with run:  # start(): status running (the "started" report)
        install_termination_backstop(lambda: run, secrets.values, ctx.backstop_disposition)
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
                async for item in run_with_heartbeat(
                    lambda: execute(ctx), interval=ctx.runtime.heartbeat_interval
                ):
                    if isinstance(item, HeartbeatResult):
                        if item.error is not None:
                            raise item.error
                        result = item.value
                    else:
                        yield item
        except Exception as exc:  # noqa: BLE001 — reported, scrubbed, never re-raised
            message = scrub_exception(exc, secrets)
            log.error("Unhandled error: %s", message)
            # Report here, scrubbed, so RunReporter.__exit__ never writes the
            # raw exception text to Supabase.
            run.fail("UNHANDLED_ERROR", message, metrics=ctx.metrics())
            yield terminal_chunk(json.dumps(outcomes.failed("UNHANDLED_ERROR", message).terminal()))
            return

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


if __name__ == "__main__":
    app.run()
