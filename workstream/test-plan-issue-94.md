# Compliance Test Plan — Issue #94: Schedule pg_cron Reaper & Verify Stale-Run Detection

> **Mode:** verifier Design Mode (test-first)
> **Repository:** `llipe/dev-tasks-agent-fleet`
> **Source issue:** [#94](https://github.com/llipe/dev-tasks-agent-fleet/issues/94) — `fix(infra): schedule pg_cron reaper and verify stale-run detection (Phase 1 gap)`
> **Task list:** `workstream/tasks-issue-94-schedule-pg-cron-reaper.md`
> **Reference artifacts:** `docs/reference/001_schema.sql` (`reap_stale_runs()`, `v_runs`), `docs/reference/002_seed.sql` (seeded agent/repos), `docs/runbooks/issue-77-deployment-e2e.md`

## Nature of this plan

This issue is **infrastructure + verification**, not application code. There is no unit-testable module to add; the "system under test" is a scheduled Postgres function (`reap_stale_runs()`) running against the live Supabase database, a read-time SQL view (`v_runs.effective_status`), and the agent SDK's CloudWatch fallback path on a live AgentCore runtime.

Consequently the test cases here are **black-box behavioral checks executed as SQL/CLI assertions against a live environment**, not a code test suite. Every test is designed to be observable — asserting on `runs.status`, `run_events` rows, `v_runs.effective_status`, `cron.job*` catalog rows, and CloudWatch log presence — with no dependency on the reaper's internal SQL structure. Because most execution requires live Supabase/AWS access, each test is tagged **[MANUAL]** (operator) or **[DEV]** (repo-side, developer agent), matching the task-list split.

The seeded thresholds (`max_runtime_seconds=3600`, `grace_seconds=120`, `start_timeout_seconds=300`) are snapshotted per run (D8), so all timeout tests use **synthetic run rows with small threshold values** to keep each check to minutes rather than the real ~62-minute window.

## Source input summary

| Item | Value |
|------|-------|
| Reaper function | `reap_stale_runs()` — materializes `timed_out` (running past `max_runtime_seconds + grace_seconds`, clock `started_at`) and `failed_to_start` (queued past `start_timeout_seconds`, clock `queued_at`); writes an explanatory `run_events` row per transition |
| Read-time view | `v_runs.effective_status` — computes the same terminal status at read time so the UI is correct even before the reaper fires (two-layer design, technical-guidelines §3, PRD FR11a) |
| Scheduler | `pg_cron`, `cron.schedule('reap-stale-runs', '* * * * *', ...)` — one tick per minute |
| Seeded identities | agent `slug='dependency-update'`; repos `llipe/memo-cli`, `llipe/tf-ecommerce-mgmt` (resolve `agent_id`/`repository_id` by these keys) |

## Acceptance criteria extraction

Numbered from the issue's "Acceptance criteria" section:

- **AC1** — `cron.job` shows `reap-stale-runs` scheduled at `* * * * *`, and `cron.job_run_details` shows successful recent executions.
- **AC2** — A synthetic `queued` run past its `start_timeout_seconds` becomes `failed_to_start` within one cron tick, with an explanatory `run_events` row.
- **AC3** — A synthetic `running` run past `max_runtime_seconds + grace_seconds` becomes `timed_out` within one cron tick, with an explanatory `run_events` row.
- **AC4** — `v_runs.effective_status` reports the terminal status for both cases *before* the reaper materializes it (two-layer design).
- **AC5** — A real long-running `llm_fix` run is not reaped early, and the observed cold-start gap is recorded against `grace_seconds = 120`.
- **AC6** — With Supabase unreachable, the agent completes and its payloads are recoverable from CloudWatch.
- **AC7** — The scheduling step and all results are documented in the deployment runbook.

**Business rules / constraints:**
- Two clocks, two states (D8/D9): `timed_out` uses `started_at`; `failed_to_start` uses `queued_at`. They must not collapse.
- Every reaper transition MUST write an explanatory `run_events` row — this event is the *only* source of the "why" (product-context success metric 3).
- Reaping is non-destructive: it only advances `queued`/`running` rows to a terminal state; it never touches already-terminal rows.
- The reaper uses `for update skip locked` — concurrent ticks must not double-process a row.

**Non-goals (must remain untested / untouched):** heartbeat detection (`last_heartbeat_at`), run cancellation (`canceled`), `run_events` retention (R3), any panel/UI work.

## E2E scenarios (black-box)

Each scenario is expressed as setup → action → observable assertion. "Wait one tick" means up to 60s for the next `* * * * *` cron fire.

### E2E-1 — Reaper is scheduled and firing (AC1) · [MANUAL]

- **Setup:** `pg_cron` enabled; `cron.schedule('reap-stale-runs', '* * * * *', $$select reap_stale_runs()$$)` executed.
- **Action:** Query `cron.job` and `cron.job_run_details`.
- **Assert:**
  - `select jobname, schedule, command, active from cron.job where jobname='reap-stale-runs';` → one row, `schedule='* * * * *'`, `active=true`.
  - `select status, return_message, start_time from cron.job_run_details where jobid=(select jobid from cron.job where jobname='reap-stale-runs') order by start_time desc limit 5;` → recent rows with `status='succeeded'`.
- **Positive/negative:** positive = job present + succeeding; negative counterpart = EC-6 (duplicate schedule) and EC-7 (function error surfaces in `job_run_details`).

### E2E-2 — Queued run past start timeout becomes `failed_to_start` with event (AC2) · [MANUAL]

- **Setup:** Insert synthetic `queued` row (see Appendix A, insert #1): `status='queued'`, `queued_at=now()`, `start_timeout_seconds=60`, real `agent_id`/`repository_id`, all NOT-NULL snapshot columns populated.
- **Action:** Wait `60s + one tick`.
- **Assert:**
  - `select status, error_code, error_message from runs where id=:id;` → `status='failed_to_start'`, `error_code='START_TIMEOUT'`, non-null `error_message`, `finished_at` set.
  - `select level, message, data->>'reason' as reason from run_events where run_id=:id order by seq;` → at least one row with `reason='START_TIMEOUT'`, `data->>'reaped_by'='reap_stale_runs'`, `level='error'`.
- **Negative pairing:** EC-1 (queued but *not yet* past threshold must remain `queued`, no event).

### E2E-3 — Running run past max_runtime+grace becomes `timed_out` with event (AC3) · [MANUAL]

- **Setup:** Insert synthetic `running` row (Appendix A, insert #2): `status='running'`, `started_at=now()`, `max_runtime_seconds=60`, `grace_seconds=10`.
- **Action:** Wait `70s + one tick`.
- **Assert:**
  - `runs.status='timed_out'`, `error_code='RUNTIME_TIMEOUT'`, `finished_at` set.
  - a `run_events` row with `reason='RUNTIME_TIMEOUT'`, `reaped_by='reap_stale_runs'`, `level='error'`.
- **Negative pairing:** EC-2 (running within threshold + grace must remain `running`, no event).

### E2E-4 — Two-layer contract: view leads the reaper (AC4) · [MANUAL]

- **Setup:** Reuse the E2E-3 synthetic `running` row.
- **Action:** In the window **after** `started_at + 70s` but **before** the next cron tick materializes the change, query `v_runs`.
- **Assert:** `select status, effective_status from v_runs where id=:id;` → `status='running'` **and** `effective_status='timed_out'` simultaneously. Symmetrically for the queued case: `status='queued'`, `effective_status='failed_to_start'`.
- **Why:** confirms the read-time layer is correct even when the reaper is up to one minute behind — the exact behavior PRD FR11a relies on and the mechanism that would otherwise *mask* an unscheduled reaper.

### E2E-5 — Healthy long-running llm_fix is not reaped early (AC5, AC-36 dynamic half) · [MANUAL]

- **Setup:** Trigger a real `llm_fix` invocation on a repo with available updates (per runbook #77 §7.8), one that legitimately runs 20+ minutes.
- **Action:** Let it run to natural completion while the reaper ticks every minute.
- **Assert:**
  - Terminal `runs.status ∈ {succeeded, failed}`, **never** `timed_out`.
  - No `run_events` row with `reaped_by='reap_stale_runs'` for this run.
  - Record the measured gap between AgentCore's invocation clock and the run's `started_at` (cold start + image pull); assert it is comfortably `< grace_seconds (120)`.
- **Note:** directly addresses dependency-update PRD open question 8 (underestimated grace kills healthy runs).

### E2E-6 — CloudWatch fallback when Supabase is unreachable (AC6) · [MANUAL]

- **Setup:** Point `SUPABASE_URL` at an unreachable host on the runtime config (record exact prior value).
- **Action:** Invoke the agent with a valid payload.
- **Assert:**
  - The agent process **completes** (exits normally); the invocation does not crash — reporting failure never kills the agent.
  - After the SDK's 3 retries, the failed payloads appear in the runtime's CloudWatch log group via stderr.
  - **Restore** `SUPABASE_URL`; confirm a subsequent invocation reports to Supabase normally.
- **Negative pairing:** EC-8 (4xx/contract error is *not* retried — distinct from the transient-unreachable path that *is* retried 3× then dumped).

### E2E-7 — Scheduling + results documented (AC7) · [DEV]

- **Setup / Action:** After E2E-1..6 results exist.
- **Assert (doc review):**
  - `docs/reference/001_schema.sql` scheduling block is uncommented.
  - The deployment runbook (`issue-77-deployment-e2e.md` section or new `issue-94-reaper-verification.md`) contains: enable-extension step, `cron.schedule` command, `cron.job*` verification queries, ready-to-paste synthetic inserts, and filled AC1–AC6 results tables in the #77 style.
  - `workstream/traceability-matrix-dep-update-agent.md` AC-36 dynamic half updated from `E2E (manual, long-running)` to exercised.

## Contract validation scenarios

The reaper and view share an implicit **state-machine contract** and the reaper↔view **consistency contract**. These are the "provider/consumer" contracts for this issue.

### CT-1 — Reaper state-transition contract · [MANUAL]

| Precondition state | Clock condition | Allowed post-reaper state | Forbidden |
|---|---|---|---|
| `queued` | `now() > queued_at + start_timeout_seconds` | `failed_to_start` | any other terminal |
| `queued` | within threshold | stays `queued` | any transition |
| `running` | `now() > started_at + max_runtime + grace` | `timed_out` | any other terminal |
| `running` | within threshold + grace | stays `running` | any transition |
| `succeeded`/`failed`/`canceled`/`timed_out`/`failed_to_start` | any | unchanged | **any mutation** |

- **Assert:** run the reaper (or wait a tick) with rows seeded in each precondition; confirm only the two "past-threshold" rows transition and terminal rows are byte-identical before/after (`select status, finished_at, error_code from runs where id = any(:ids)`).

### CT-2 — View/reaper consistency contract · [MANUAL]

- **Property:** For any run row, once the reaper has fired at/after the threshold, `runs.status == v_runs.effective_status`. Before the reaper fires but after the threshold, `v_runs.effective_status` already equals the *eventual* `runs.status`.
- **Assert:** snapshot `effective_status` at T+threshold (pre-tick) and `status` at T+threshold+tick (post-reaper); the two MUST match for both `timed_out` and `failed_to_start`.

### CT-3 — Event schema contract · [MANUAL]

- **Property:** Every reaper-written `run_events` row carries `level='error'`, a human-readable `message`, and `data` containing `reaped_by='reap_stale_runs'` and a `reason ∈ {START_TIMEOUT, RUNTIME_TIMEOUT}`; `seq` is `max(seq)+1` for that run (monotonic, no collision with agent-written events).
- **Assert:** `select seq, level, message, data from run_events where run_id=:id order by seq;` — schema and monotonicity hold.

## Edge-case catalog

All 9 categories evaluated; non-applicable ones noted with reason.

### EC-1: Queued run exactly at / just below the start-timeout boundary · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC2 |
| Category | Data Boundaries |
| Input / Setup | `queued` row, `start_timeout_seconds=60`, checked at `queued_at + 59s` and again at `+61s` |
| Expected Result | At +59s: still `queued`, no event. At +61s (+ tick): `failed_to_start` + event. |
| Risk if Missed | Off-by-one in the `now() >` comparison silently kills or spares runs at the boundary. |

### EC-2: Running run within `max_runtime` but inside grace window · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC3 |
| Category | Data Boundaries, Timing |
| Input / Setup | `running` row, `max_runtime_seconds=60`, `grace_seconds=10`; check at `started_at + 65s` |
| Expected Result | Still `running` (65 < 60+10) — grace not yet exceeded. |
| Risk if Missed | Grace collapse → healthy runs reaped exactly when the fleet's whole point (D8) is to protect them. |

### EC-3: Running row with NULL `started_at` · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC3 |
| Category | Input Domain (null) |
| Input / Setup | `status='running'`, `started_at IS NULL` (anomalous but possible) |
| Expected Result | Not reaped as `timed_out` (reaper guards `started_at is not null`); row is left for operator inspection. |
| Risk if Missed | Null-clock arithmetic could throw or mis-transition, poisoning a cron tick for all rows. |

### EC-4: Clock skew / `started_at` in the future · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC3 |
| Category | Timing |
| Input / Setup | `running` row with `started_at = now() + interval '10 min'` |
| Expected Result | Never reaped (future start can't exceed threshold); no event. |
| Risk if Missed | Skewed agent clocks could trigger spurious `timed_out`. |

### EC-5: Concurrent cron ticks / double-fire on the same row · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC2, AC3 |
| Category | Timing & Concurrency, Idempotency |
| Input / Setup | Force two overlapping `select reap_stale_runs();` executions against the same past-threshold row |
| Expected Result | Row transitions exactly once; exactly **one** explanatory `run_events` row (`for update skip locked` prevents double-processing). |
| Risk if Missed | Duplicate terminal writes / duplicate events / `seq` collision → `uq_run_events_seq` violation aborts a tick. |

### EC-6: Duplicate `cron.schedule` with the same jobname · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC1 |
| Category | Idempotency, State Transitions |
| Input / Setup | Run `cron.schedule('reap-stale-runs', ...)` twice |
| Expected Result | Exactly one active `reap-stale-runs` job (pg_cron upserts by name); not two jobs firing in parallel. |
| Risk if Missed | Two jobs double-fire the reaper every minute, amplifying EC-5. |

### EC-7: Reaper function raises inside a cron tick · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC1 |
| Category | Failure Modes |
| Input / Setup | Observe `cron.job_run_details` after normal operation; deliberately not injected — verify the *observability* path exists |
| Expected Result | Any failed tick surfaces as `status='failed'` with `return_message` in `cron.job_run_details`, not a silent no-op. |
| Risk if Missed | A silently failing reaper looks identical to a healthy one (the core defect this issue exists to prevent). |

### EC-8: Agent reporting hits a 4xx (contract) vs transient (5xx/network) · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC6 |
| Category | Failure Modes |
| Input / Setup | (a) unreachable host → transient; (b) malformed payload → 4xx |
| Expected Result | (a) retried 3× then dumped to stderr/CloudWatch; (b) **not** retried (contract error), single failure recorded. Agent completes in both cases. |
| Risk if Missed | Retry storm on non-retryable errors, or agent crash on reporting failure — violates "reporting never kills the agent." |

### EC-9: `run_events.seq` monotonicity when a run already has agent-written events · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC2, AC3 |
| Category | Data Boundaries |
| Input / Setup | Synthetic row with pre-existing `run_events` rows (seq 1..5), then reaped |
| Expected Result | Reaper event gets `seq=6` (`max(seq)+1`), no unique-constraint violation. |
| Risk if Missed | `uq_run_events_seq` collision aborts the reaper transaction, leaving the run stuck. |

**Categories marked N/A:**
- **Auth & Permissions:** N/A — the reaper runs as `security definer`; there is no user-facing auth surface in v1 (no login, R1). Agent-side Supabase auth is covered indirectly by EC-8.
- **Resource Exhaustion:** N/A for v1 scope — `run_events` volume (R3/R5) is explicitly out of scope for this issue; noted as a future concern, not tested here.
- **API Versioning:** N/A — no versioned API surface in this infrastructure change.

## Randomized tactics and seed policy

Randomized coverage targets the reaper's boundary arithmetic across many threshold/elapsed combinations, and the fallback path across many break conditions. Seeds follow `<tactic>-<AC>-<unix-ts>-<hex>`; replay by re-inserting rows generated from the captured seed.

### RT-1: Property — reaper transitions iff past threshold · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC2, AC3 |
| Tactic type | property-based |
| Input surface | Synthetic rows with randomized `(state, max_runtime_seconds, grace_seconds, start_timeout_seconds, elapsed)` within valid ranges (thresholds 1..300s, elapsed 0..600s) |
| Property / Oracle | After a reaper tick: row is terminal **iff** `elapsed > threshold(+grace)`; the transition target matches the state's contract (CT-1); exactly one explanatory event when transitioned, zero otherwise |
| Iterations | 200 |
| Seed | `prop-AC2AC3-{ts}-{hex}` (records the generated tuples) |
| Replay instruction | Re-insert the row tuples emitted for the captured seed, run one reaper tick, re-assert |
| Shrink strategy | Reduce to the single `(threshold, elapsed)` pair nearest the boundary that still mis-transitions |

### RT-2: Fuzz — malformed/extreme snapshot values · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC2, AC3 |
| Tactic type | fuzz |
| Input surface | `runs` snapshot columns: `max_runtime_seconds`, `grace_seconds`, `start_timeout_seconds` |
| Property / Oracle | Reaper never raises inside the tick (job_run_details stays `succeeded`); no row transitions on non-sensical timeouts unless genuinely past-threshold; DB constraints reject truly invalid inserts rather than the reaper mis-handling them |
| Mutation corpus | `0`, `1`, `2147483647` (int max), negative (expect insert rejection or immediate-threshold semantics), very large elapsed |
| Iterations | 100 |
| Seed | `fuzz-AC3-{ts}-{hex}` |
| Replay instruction | Re-insert mutated tuples for the captured seed; run tick; assert job succeeded + no spurious transitions |
| Shrink strategy | Binary-search the single field value that trips a tick failure |

### RT-3: Stateful random walk — mixed run population under repeated ticks · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC1, AC2, AC3, AC4 |
| Tactic type | stateful-random-walk |
| Input surface | A population of N runs in random valid states/ages; run K reaper ticks interleaved with random `v_runs` reads |
| Property / Oracle | Invariants after every tick: (1) terminal rows never mutate; (2) each past-threshold row ends terminal with exactly one reaper event; (3) at every read, `v_runs.effective_status` equals the eventual `runs.status` for that row; (4) total reaper events == total transitions |
| Iterations | 50 walks × up to 20 rows |
| Seed | `walk-AC1-4-{ts}-{hex}` |
| Replay instruction | Rebuild the population + tick order from the captured seed |
| Shrink strategy | Delta-debug the action sequence to the shortest walk that breaks an invariant |

**Failure triage:** on any randomized failure, follow the verifier failure-triage workflow — capture seed + row tuples, replay to confirm determinism, minimize via the shrink strategy, classify (spec gap → `product-engineer`; implementation defect → `developer`; non-reproducing after ≤3 tries → `inconclusive`), and report with the minimized input and related AC.

## Execution checklist

Order matters: AC1 (scheduling) must pass before AC2–AC5 (they depend on the cron tick).

- [ ] **[DEV]** Uncomment scheduling block in `001_schema.sql` (task 1.1) — precondition for E2E-7.
- [ ] **[MANUAL]** Enable `pg_cron` + schedule job (tasks 1.2, 1.3) — precondition for all timeout tests.
- [ ] **[MANUAL]** E2E-1 / AC1 — job scheduled + firing (`cron.job`, `cron.job_run_details`).
- [ ] **[MANUAL]** E2E-2 / AC2 — `failed_to_start` + event; pair EC-1, EC-9.
- [ ] **[MANUAL]** E2E-4 / AC4 (queued half) — `effective_status='failed_to_start'` before tick.
- [ ] **[MANUAL]** E2E-3 / AC3 — `timed_out` + event; pair EC-2, EC-3, EC-4, EC-9.
- [ ] **[MANUAL]** E2E-4 / AC4 (running half) — `effective_status='timed_out'` before tick.
- [ ] **[MANUAL]** CT-1 — full state-transition table (incl. terminal-rows-untouched).
- [ ] **[MANUAL]** CT-2 / CT-3 — view/reaper consistency + event schema.
- [ ] **[MANUAL]** EC-5, EC-6, EC-7 — concurrency / duplicate schedule / failed-tick observability.
- [ ] **[MANUAL]** E2E-5 / AC5 / AC-36 — healthy llm_fix not reaped; record cold-start gap vs grace=120.
- [ ] **[MANUAL]** E2E-6 / AC6 — CloudWatch fallback; pair EC-8; restore `SUPABASE_URL`.
- [ ] **[MANUAL]** RT-1, RT-2, RT-3 — randomized boundary/fuzz/walk (optional depth, seeds captured).
- [ ] **[DEV]** E2E-7 / AC7 — runbook + schema + traceability matrix updated with all results.

## Appendix A — Ready-to-paste synthetic inserts

> Resolve real foreign keys from the seed. `agent_id` and `repository_id` below are looked up by their seeded keys so the inserts stay valid across environments. Snapshot NOT-NULL columns (`agent_version`, `max_runtime_seconds`, `grace_seconds`) are populated explicitly; `id` uses `gen_random_uuid()`.

**Insert #1 — queued past start-timeout (E2E-2 / AC2):**
```sql
insert into runs (
  id, agent_id, agent_version, repository_id, installation_id,
  status, queued_at, max_runtime_seconds, grace_seconds, start_timeout_seconds
)
select
  gen_random_uuid(), a.id, a.version, r.id, r.installation_id,
  'queued', now(), 60, 10, 60
from agents a
join repositories r on r.full_name = 'llipe/memo-cli'
where a.slug = 'dependency-update'
returning id;   -- capture for assertions
```

**Insert #2 — running past max_runtime+grace (E2E-3 / AC3 / AC4):**
```sql
insert into runs (
  id, agent_id, agent_version, repository_id, installation_id,
  status, queued_at, started_at, max_runtime_seconds, grace_seconds, start_timeout_seconds
)
select
  gen_random_uuid(), a.id, a.version, r.id, r.installation_id,
  'running', now() - interval '2 min', now(), 60, 10, 300
from agents a
join repositories r on r.full_name = 'llipe/memo-cli'
where a.slug = 'dependency-update'
returning id;   -- capture for assertions
```

**Assertion queries:**
```sql
-- status + error fields
select status, error_code, error_message, finished_at from runs where id = :id;
-- explanatory reaper event
select seq, level, message, data->>'reaped_by' as reaped_by, data->>'reason' as reason
from run_events where run_id = :id order by seq;
-- two-layer check (run BEFORE the next cron tick, AFTER threshold)
select status, effective_status from v_runs where id = :id;
```

**Cleanup after verification:**
```sql
-- remove synthetic rows (events cascade via FK on delete cascade)
delete from runs where id = any(:synthetic_ids);
```

## Handoff

- Design Mode complete. Next: `developer` executes the **[DEV]** sub-tasks and hands the operator the **[MANUAL]** runbook steps.
- After implementation, run **verifier Audit Mode** against the delivered runbook + schema change + recorded operator results to produce `fidelity-report-issue-94.md`.
