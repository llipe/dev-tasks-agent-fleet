# Refinement — Issue #98: run dies during `validate` step without reporting terminal status

- **Repository:** `llipe/dev-tasks-agent-fleet`
- **Issue:** [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98)
- **Type:** bug · `priority:high` · `size:M`
- **Discovery source:** [#94](https://github.com/llipe/dev-tasks-agent-fleet/issues/94) (pg_cron reaper verification), see `docs/runbooks/issue-94-reaper-verification.md` (Known limitations §1)

## Changelog

| Version | Date       | Summary                                                                                                                                           | Author           |
| ------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| 1.0     | 2026-08-31 | Initial refinement. Confirmed root cause from CloudWatch evidence and code review; committed to heartbeat + three-clock reconciliation direction. | product-engineer |

## 1. Root cause (evidence-backed)

The run went silent, was never reported terminal by the agent, and was later reaped as `timed_out`. Two independent lines of evidence identify the cause as an **AgentCore output-idle session timeout killing the container mid-`validate`**, not a missing code branch.

### 1.1 CloudWatch evidence (run `f63ac9f3-14b0-4157-9484-f2f6b062f846`)

Container log group `/aws/bedrock-agentcore/runtimes/dependencyupdate_dependency_update-UsQc5U5Yz0-DEFAULT`, stream `2026/08/31/[runtime-logs]d7aeb0be-…`. The stream **ends cleanly** on the last `update`-step line and contains **no** exception, traceback, OOM, SIGKILL, or terminal-report line afterward:

```
2026-08-31T19:34:47.533Z  Returning streaming response (generator) (0.000s)
2026-08-31T19:34:50.138Z  GitHub credentials resolved for org=llipe
2026-08-31T19:34:52.260Z  Repository cloned to /tmp/dep-update-tf-ecommerce-mgmt-…
2026-08-31T19:34:55.689Z  Toolchain: pm=pnpm, scripts=test
2026-08-31T19:35:25.172Z  Dependencies installed (frozen)
2026-08-31T19:35:32.203Z  Audit complete: 101 total vulns, 0 in_range, 2 major_required, 94 unknown
2026-08-31T19:36:07.346Z  Update applied: 0 packages changed       ← last line, then silence
```

The control-plane Lambda log groups over the same window show **no** kill/OOM/timeout message either. AgentCore idle-session reclamation leaves no application-visible log line, which is consistent with the clean silence.

### 1.2 Code review — the terminal-report contract already holds

`RunReporter.__exit__` (`agent_reporter.py`) **guarantees** a terminal DB write on *any* normal Python exit from the `with RunReporter.from_env() as run:` block:

- on exception → `fail(...)` (and open steps closed `failed`);
- on clean exit where nobody terminated → `succeed("not_applicable")`.

Therefore a run left `status='running'` with `validate` still open and **no** terminal write can only happen if the **process was killed abruptly** (SIGKILL) so `__exit__` never ran. This rules out the "agent forgot to report success" hypothesis for *this* run — the gap is process survival, not a missing call.

### 1.3 Why the container was killed — the three-clock inconsistency

The entrypoint `invoke()` in `main.py` is an `@app.entrypoint` **async generator that yields only at terminal points** (final result payloads). Between `19:34:47` ("Returning streaming response") and death it emitted **zero** yields. When `validate` began a long `pnpm test` on a 101-advisory monorepo, the HTTP response stream stayed idle past the AgentCore limit and the container was reclaimed.

There are **three independent clocks** that should be consistent and are not:

| Clock | Value | Owner / location | Enforced by |
| --- | --- | --- | --- |
| `idleRuntimeSessionTimeout` | **300 s** | `agents/dependency-update/agentcore/agentcore.json` | AWS AgentCore (container) |
| `maxLifetime` | 3600 s | same file | AWS AgentCore (container) |
| `TEST_TIMEOUT` | **600 s** | `app/dependencyUpdate/config.py` (env-overridable) | agent subprocess bound |
| `max_runtime_seconds` + `grace_seconds` | 3600 + 120 = **3720 s** | Supabase run snapshot / reaper | `reap_stale_runs()` |

`TEST_TIMEOUT` (600 s) is **twice** the idle timeout (300 s): a validation test run lasting 5–10 minutes with no stream output is structurally unsurvivable, regardless of `maxLifetime`. This is the leading cause.

**OOM remains a secondary hypothesis** (a `pnpm test` OOM on a 101-advisory monorepo would produce an identical DB signature) but is **not supported** by any observed evidence and cannot be confirmed without container memory metrics.

## 2. Goal

- **Goal:** A `dependency-update` run performs long-running steps (notably `validate`) without the AgentCore container being reclaimed for output inactivity, and reaches a normal terminal status. The three timeout clocks are made mutually consistent and documented.
- **Primary user impact:** `llm_fix`-mode runs and any run with a slow test suite can complete instead of dying silently and surfacing only as a late `timed_out`. Unblocks dependency-update PRD AC-36 and #94 AC5.
- **Non-goals:**
  - The reaper itself — verified correct in #94.
  - Heartbeat-based *stale detection* (`last_heartbeat_at`, parent PRD §9 backlog). This issue keeps the container **alive**; it does not add a DB heartbeat detection signal.
  - Closing orphan `run_steps` on reap — that is [#99](https://github.com/llipe/dev-tasks-agent-fleet/issues/99).

## 3. Chosen direction (Option A)

Commit to **keep-alive + clock reconciliation** as the primary fix, with OOM sizing retained only as a documented contingency:

1. **Periodic heartbeat yields from the entrypoint during long-running steps** so the HTTP response stream never goes idle. The agent must emit a lightweight stream chunk on an interval comfortably below `idleRuntimeSessionTimeout` while a blocking step (install / audit / update / validate / llm_fix) is in progress.
2. **Reconcile the three clocks** so no inner timeout can exceed an outer one:
   - `idleRuntimeSessionTimeout` (and effective `maxLifetime`) must be ≥ the longest inner operation bound, i.e. ≥ `TEST_TIMEOUT`, **or** the heartbeat interval must guarantee the stream is never idle for `idleRuntimeSessionTimeout` — whichever the confirmed AgentCore semantics require.
   - The AgentCore container lifetime and the Supabase `max_runtime_seconds`/`grace_seconds` reaper threshold must be coherent (container should not outlive the reaper window, nor die far before it without reporting).
   - Document the single source of truth and the ordering invariant: `TOOL_COMMAND_TIMEOUT` ≤ `TEST_TIMEOUT` ≤ container idle/lifetime ≤ reaper threshold.

## 4. Acceptance Criteria

- [ ] **AC1 — Root cause recorded with evidence.** The CloudWatch finding (§1.1), the `__exit__` contract analysis (§1.2), and the three-clock inconsistency (§1.3) are captured in the code/docs and referenced from `docs/runbooks/issue-94-reaper-verification.md`. *(Given the silent death signature, When the death window is inspected, Then the record identifies output-idle timeout as the cause and OOM as the excluded-pending-metrics contingency.)*
- [ ] **AC2 — Long `validate` survives.** A `validate` step whose test run exceeds 5 minutes completes without the container being reclaimed. *(When a run's `pnpm test` runs >300 s, Then the stream stays non-idle via heartbeat and the run reaches a terminal status.)*
- [ ] **AC3 — Long `llm_fix` run completes.** An `llm_fix` run exceeding 20 minutes reaches a normal terminal status (`succeeded`/`failed` written by the agent), not a reaper `timed_out`.
- [ ] **AC4 — Clocks reconciled and documented.** `TEST_TIMEOUT`, `TOOL_COMMAND_TIMEOUT`, `idleRuntimeSessionTimeout`, `maxLifetime`, and the Supabase `max_runtime_seconds`/`grace_seconds` are mutually consistent per the §3 ordering invariant, with the relationship documented in `technical-guidelines.md` (or the agent README) as a single source of truth.
- [ ] **AC5 — Heartbeat does not corrupt the result contract.** Heartbeat stream chunks are distinguishable from the terminal result payload and do not break `unwrap_payload`/result parsing on the consumer side; the terminal payload remains the last chunk.
- [ ] **AC6 — Container-kill backstop documented.** Where an abrupt SIGKILL still cannot be intercepted, the agent makes a best-effort terminal flush where technically possible; where impossible, it is explicitly documented that the pg_cron reaper is the sole backstop.

## 5. Constraints

- The reporting SDK (`agent_reporter.py`) is a byte-identical copied file (D13) with a mypy override; heartbeat logic **SHOULD** live in the entrypoint / pipeline orchestration, not in `agent_reporter.py`, to avoid diverging the copied SDK.
- No new external runtime dependency is expected; heartbeat should use the existing async generator mechanism.
- `error_code` / `runs` columns are free-form text (no enum/check) per `001_schema.sql` — **no DB migration** is anticipated. If any DB change is proposed, the migration lifecycle + user-confirmation gate applies.
- Changing `agentcore.json` lifecycle values is a redeploy of the AgentCore runtime (see `technical-guidelines.md` §13) — an operator/manual step, to be recorded in the manual-config runbook.

## 6. Risks and Edge Cases

- **OOM masquerade.** If the true cause on some runs is OOM rather than idle timeout, the heartbeat alone will not save them. AC1 must state OOM is unconfirmed; container memory sizing is the contingency lever if AC2/AC3 still fail after heartbeat.
- **`"0 packages changed"` yet proceeded to `validate`.** The final log line was `Update applied: 0 packages changed`, but DB evidence shows `validate` opened 600 ms later — so `has_changes(workspace)` returned truthy despite a zero package-change count. This inconsistency **SHOULD** be verified during implementation (it is a candidate confusing-log defect, not necessarily in scope to fix here).
- **Heartbeat interval vs. real idle semantics.** If `idleRuntimeSessionTimeout` is invocation-idle rather than stream-output-idle, heartbeat yields may not reset it; the implementer must confirm the semantic empirically (a short live run) before relying on it.
- **Heartbeat too chatty.** Interval must be well below 300 s but not so frequent it floods the stream / logs (interacts with R5, verbose-execution write volume).

## 7. Dependencies

- Related: [#94](https://github.com/llipe/dev-tasks-agent-fleet/issues/94) (discovery), [#99](https://github.com/llipe/dev-tasks-agent-fleet/issues/99) (orphan step on reap — adjacent, separate), [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101) (#94 residual verification incl. AC5 healthy-long-run).
- Blocks: dependency-update PRD AC-36; #94 AC5 verification.
- Requires live AgentCore deploy + a real long run to verify AC2/AC3 (deploy/E2E — see #77).

## 8. Testing Notes

- **Unit (Layer 1, `pytest`):** heartbeat scheduler/generator helper emits at the configured interval and stops at step boundaries; result payload is always the final chunk; clock-consistency assertion (a test that fails if `TEST_TIMEOUT` > configured container idle bound).
- **Component (Layer 2, `pytest`):** entrypoint driven with a mocked long-running `validate` — assert heartbeat chunks are interleaved and a terminal report is still produced; assert consumer-side parsing ignores heartbeat chunks (AC5).
- **Manual / live:** one real run with a >5 min test suite (AC2) and one `llm_fix` run >20 min (AC3) against deployed AgentCore; capture CloudWatch to confirm no idle reclamation and a terminal DB status. Empirically confirm `idleRuntimeSessionTimeout` semantics before trusting the heartbeat (Risk in §6).
- **Edge-case checks:** `"0 packages changed"` → `validate` inconsistency (§6); SIGKILL best-effort flush path (AC6).
- **AC-to-test mapping:** AC1→doc/runbook review; AC2/AC3→manual live + component; AC4→unit clock-consistency + doc review; AC5→unit + component parsing; AC6→doc review + best-effort-flush unit if implemented.

## 9. Open Questions

- Exact semantics of AgentCore `idleRuntimeSessionTimeout` (invocation-idle vs. stream-output-idle) — decides whether heartbeat yields actually reset it or whether the timeout value itself must be raised. **Must be confirmed empirically during implementation.**
- Target heartbeat interval (e.g., 60–120 s) and final reconciled values for `idleRuntimeSessionTimeout` / `maxLifetime` / `TEST_TIMEOUT`.
- Whether to also raise `idleRuntimeSessionTimeout` as defense-in-depth even after heartbeat is in place.
