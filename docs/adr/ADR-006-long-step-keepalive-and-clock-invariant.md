# ADR-006: Long-Step Keep-Alive, Enforced Timeout-Clock Invariant, and Abrupt-Termination Backstop

## Status

Accepted

## Context

The `dependency-update` agent runs on AWS Bedrock AgentCore behind an
`@app.entrypoint` async generator. Historically that generator yielded only at
terminal points, so during a long blocking step — notably `pnpm test` inside the
`validate` step, and the multi-call `llm_fix` loop — the HTTP response stream sat
idle for the whole duration of the step. AgentCore reclaims a container whose
stream stays idle past `idleRuntimeSessionTimeout` (300 s at the time). With
`TEST_TIMEOUT` defaulting to 600 s — twice the idle bound — a legitimately
running validation could be reclaimed **mid-step, before the agent wrote any
terminal status**. The run then sat `running` in Supabase until the `pg_cron`
reaper marked it `timed_out` ~61 minutes later.

This is issue #98, first observed during the issue #94 reaper verification on
real run `f63ac9f3-…`: the container log ended cleanly on the last `update`-step
line with no exception, no OOM signature, and no terminal line — the fingerprint
of output-idle reclamation rather than a crash. The defect blocked issue #94's
AC5 (no long run could complete) and, left unaddressed, would make
`maxLifetime: 3600` moot because nothing survived the first five idle minutes.

Three properties of the system made this more than a one-line timeout bump:

1. **Four timeout "clocks" govern one run and were only implicitly related.**
   `TOOL_COMMAND_TIMEOUT` (per fix-agent command) ≤ `TEST_TIMEOUT` (validation)
   bound the work; `IDLE_SESSION_TIMEOUT` and `MAX_LIFETIME` are container bounds
   mirrored in `agentcore/agentcore.json`; `REAPER_THRESHOLD_SECONDS` mirrors the
   Supabase run snapshot (`max_runtime_seconds` + `grace_seconds`). Nothing
   stopped a future edit to any one value from re-opening exactly this class of
   defect — a silent mid-step death is the worst possible failure mode because
   the two-layer reaper design (technical-guidelines §3) keeps the UI looking
   correct while `runs.status` stays wrong.

2. **The keep-alive must not leak into the vendored SDK.** `agent_reporter.py` is
   copied byte-identical into the agent repo (D13); the fix must live in the
   agent, not in the shared copy.

3. **`RunReporter.__exit__` covers normal exits only.** It writes a terminal
   status on any normal Python exit but not on an abrupt kill, so an
   interceptable stop (SIGTERM) still fell through to the reaper.

This ADR exists both because the repository rule requires an ADR for every change
to `technical-guidelines.md`, and — unlike ADR-002/003/005, which recorded
bug-fix status corrections — because #98 **introduces a new enforceable rule**
(the fail-fast clock-consistency invariant) and two new architectural mechanisms
(the heartbeat keep-alive and the SIGTERM backstop). It is a decision record, not
only a current-state correction.

## Decision

1. **Live-yield heartbeats during long blocking steps.** `validate` and `llm_fix`
   run under `heartbeat.run_with_heartbeat`, which executes the blocking function
   in a worker thread (stdlib `asyncio.to_thread`, no new dependency) and
   live-yields a lightweight heartbeat chunk every `HEARTBEAT_INTERVAL` (120 s)
   until the step ends. The response stream is therefore never idle for
   `IDLE_SESSION_TIMEOUT`. Heartbeat chunks (`{"heartbeat": {...}}`) are
   structurally distinct from the terminal result payload (the existing
   `event.contentBlockDelta.delta.text` shape); the terminal chunk is always
   emitted last; and a consumer extracts the result with
   `heartbeat.read_terminal_payload`, ignoring heartbeats. The reusable logic
   lives in `heartbeat.py`, **not** in the vendored `agent_reporter.py` (D13).

2. **Enforce the four-clock consistency invariant at startup (new rule).**
   `config.assert_clock_invariant()` runs first thing in the entrypoint and
   fail-fasts with `ClockConsistencyError` if the ordering is violated:

   ```
   TOOL_COMMAND_TIMEOUT (180) <= TEST_TIMEOUT (600) <= IDLE_SESSION_TIMEOUT (900)
                              <= MAX_LIFETIME (3600) <= REAPER_THRESHOLD_SECONDS (3720)
       and   0 < HEARTBEAT_INTERVAL (120) <= IDLE_SESSION_TIMEOUT / 2
   ```

   Refusing to start on an inconsistent configuration is strictly better than a
   silent mid-step death, and a unit test asserts the shipped constants satisfy
   the invariant so a bad configuration cannot ship. The container-side values
   (`IDLE_SESSION_TIMEOUT`, `MAX_LIFETIME`) MUST match
   `agentcore/agentcore.json` `lifecycleConfiguration`, and
   `REAPER_THRESHOLD_SECONDS` MUST match the Supabase run snapshot — the
   invariant makes those cross-boundary mirrors an enforced contract rather than
   a convention.

3. **Raise `idleRuntimeSessionTimeout` 300 → 900.** So a bounded `TEST_TIMEOUT`
   (600 s) validation, kept alive by the 120 s heartbeat, cannot trip idle
   reclamation. This value lives in `agentcore/agentcore.json` and only takes
   effect after a runtime **redeploy** (`agentcore deploy -y`), tracked in the
   pending-manual-config runbook.

4. **Add a best-effort SIGTERM backstop.** `signal_backstop.py` installs a
   SIGTERM handler that marks the active run `failed / SIGNAL_TERMINATION`
   (message secret-scrubbed via `scrubber.scrub`, handler never raises, no-op
   when there is no active run or it is already terminal) before restoring the
   default disposition and re-raising so the process still terminates. A true
   **SIGKILL / OOM cannot be intercepted by any process** — that path stays
   reaper-only by design. The backstop narrows, but does not close, the window
   in which an abruptly stopped run waits for the reaper.

5. **Correct the foundation docs to current state.** technical-guidelines §8
   gains the "long-step keep-alive + timeout-clock invariant" and
   "abrupt-termination backstop" subsections; §11 gains the #98 test surface;
   §18 flips the #98 row to Resolved (code) / live-verify pending; changelog row
   1.8 links this ADR.

## Alternatives Considered

- **Only raise `idleRuntimeSessionTimeout` (no heartbeat).** Rejected: it moves
  the cliff without removing it. Any step longer than the new idle bound — a slow
  `llm_fix` loop, a large test suite — reintroduces the exact silent-reclamation
  failure. A heartbeat removes the dependence of survival on a single tuned
  number.
- **Emit the keep-alive from inside `agent_reporter.py`.** Rejected: the SDK copy
  must stay byte-identical to `docs/reference/agent_reporter.py` (D13). Putting
  streaming concerns in the reporter would diverge the copy and couple reporting
  to the AgentCore stream shape.
- **Document the clock ordering as a convention without enforcing it.** Rejected:
  a comment does not prevent a future `TEST_TIMEOUT` bump above the idle bound
  from re-opening #98 silently. The whole lesson of #98 is that silent mid-step
  death is the worst outcome; a startup fail-fast converts it into a loud,
  pre-run error.
- **Introduce a new terminal error code for the idle-reclamation case.**
  Rejected: the agent cannot observe its own reclamation (that is the entire
  problem), so there is nothing in-process to report it with. The reaper's
  existing `RUNTIME_TIMEOUT` already covers the materialized outcome;
  `SIGNAL_TERMINATION` covers only the interceptable SIGTERM path.
- **Handle SIGKILL/OOM as well.** Not possible — SIGKILL is uncatchable. Recorded
  explicitly so the reaper-only coverage of that path is a documented decision,
  not a gap.
- **A background heartbeat thread instead of an async worker-thread + generator.**
  Rejected: the entrypoint is already an async generator and AgentCore consumes
  the yielded stream; driving heartbeats through the generator keeps a single
  emission path and avoids a second concurrency model.

## Consequences

**Positive.**

- A long `validate`/`llm_fix` step no longer risks silent container reclamation;
  the stream stays alive and the agent reaches its own terminal write.
- The four cross-boundary timeout mirrors are now an enforced contract: a
  configuration that could recreate #98 refuses to start rather than dying
  mid-run.
- The interceptable-kill window is narrowed by the SIGTERM backstop; the
  uncatchable path is explicitly reaper-only.
- The heartbeat/terminal chunk contract is unit-tested (terminal-last property,
  bounded heartbeat count, fuzz-safe consumer parser) so the consumer contract
  (`event.contentBlockDelta.delta.text`) is preserved.

**Negative / accepted.**

- **Live behaviour (AC2 > 5 min `validate`, AC3 > 20 min `llm_fix`) is not yet
  verified against a real runtime** — it requires the `idleRuntimeSessionTimeout`
  redeploy. The code path is unit- and component-tested (heartbeat wiring emits
  ≥1 heartbeat and a single terminal chunk last), but end-to-end confirmation is
  pending and tracked on PR #103 / the pending-manual-config runbook Step 7.
- **`signal_backstop.py`'s signal-registration path is not unit-covered** (its
  reportable core is), and the SIGTERM handler cannot itself guarantee delivery
  before the process dies — it is best-effort by construction.
- **The 900 s idle bound is still a tuned number.** The heartbeat makes survival
  independent of it in the normal case, but a step that blocks longer than
  `HEARTBEAT_INTERVAL` without the worker thread yielding control would still go
  quiet; `HEARTBEAT_INTERVAL <= IDLE_SESSION_TIMEOUT / 2` is the guard against
  that, enforced by the invariant.
- **The ~61-minute stale window from the D8 threshold choice is unchanged** — the
  reaper backstop timing is out of scope for #98 (see ADR-004).

**Follow-up actions.**

- Live-verify AC2/AC3 after the AgentCore redeploy (PR #103 /
  pending-manual-config runbook Step 7).
- Sibling defects from the same #94 exercise remain independently tracked: #99
  (reaper leaves orphan `run_steps`), #100 (hand-invoke leaves no `runs` row).

## Related

- Requirements:
  - `docs/requirements/prd-dependency-update-agent.md` (validate step, timeouts)
  - `docs/requirements/prd-agent-fleet-panel-v2.md` (D8, FR8 reaper thresholds)
- Workstream:
  - Issue [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98) / PR
    [#103](https://github.com/llipe/dev-tasks-agent-fleet/pull/103)
  - Origin: `docs/runbooks/issue-94-reaper-verification.md` §3 (real run
    `f63ac9f3-…`, where the silent death was first observed)
  - `workstream/pending-manual-config-dependency-update-agent.md` (§1 env vars,
    Step 7 redeploy)
- Docs updated:
  - `docs/technical-guidelines.md` (§8 keep-alive + backstop subsections, §11
    test surface, §18 #98 row, changelog 1.8)
  - `docs/runbooks/issue-94-reaper-verification.md` (#98 defect rows annotated
    resolved-in-code)
- Implementation:
  - `agents/dependency-update/app/dependencyUpdate/heartbeat.py`
    (`run_with_heartbeat`, chunk contract, `HeartbeatResult`)
  - `agents/dependency-update/app/dependencyUpdate/signal_backstop.py`
    (`install_termination_backstop`, `report_abrupt_termination`)
  - `agents/dependency-update/app/dependencyUpdate/config.py`
    (`assert_clock_invariant`, `ClockConsistencyError`, clock constants)
  - `agents/dependency-update/app/dependencyUpdate/main.py` (entrypoint wiring:
    startup invariant check, `validate`/`llm_fix` under `run_with_heartbeat`,
    `terminal_chunk`, SIGTERM backstop install)
  - `agents/dependency-update/agentcore/agentcore.json`
    (`idleRuntimeSessionTimeout` 300 → 900)
