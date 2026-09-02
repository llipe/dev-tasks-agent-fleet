# Compliance Test Plan — Issue #101: Complete Issue #94 AC5/AC6 Reaper Verification

> **Mode:** verifier Design Mode (test-first)
> **Repository:** `llipe/dev-tasks-agent-fleet`
> **Source issue:** [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101) — `test(infra): complete issue #94 AC5/AC6 reaper verification`
> **Refinement:** `workstream/issue-101-reaper-verification-residual-refinement.md`
> **Task list:** `workstream/tasks-issue-101-reaper-verification-residual.md`
> **Companion matrix:** `workstream/traceability-matrix-issue-101.md`
> **Parent plan (reused IDs):** `workstream/test-plan-issue-94.md`
> **Runbook (all procedures authored):** `docs/runbooks/issue-94-reaper-verification.md` §2.2/§2.3, §4.0–§4.4, §5
> **Reference artifacts:** `docs/reference/001_schema.sql` (`reap_stale_runs()`, `v_runs`), `agents/dependency-update/agentcore/agentcore.json` (`SUPABASE_URL`)

## Nature of this plan

Like #94, this issue is **infrastructure + verification, not application code**. The "system under test" is the already-scheduled `reap_stale_runs()` function, the read-time `v_runs.effective_status` view, and the agent SDK's CloudWatch fallback on a live AgentCore runtime. Test cases are **black-box behavioral checks executed as SQL/CLI assertions against a live environment**, tagged **[MANUAL]** (operator) or **[DEV]** (repo-side transcription/sync), matching the task-list split.

#101 is the **residual subset of #94** — it does not re-derive the whole plan. It carries exactly the checks #94 left open:

- the `queued → failed_to_start` **read-time** half of AC4 (only the `running → timed_out` half was observed under #94);
- the AC5 **interlock** proof (a healthy run is not reaped before threshold) via the synthetic proof that depends on nothing, plus a **valid cold-start** measurement;
- **AC6** (CloudWatch fallback when Supabase is unreachable).

To preserve traceability, test IDs that are **behaviorally identical to a #94 case are reused verbatim** (E2E-4, E2E-5, E2E-6, CT-2, CT-3, EC-2, EC-4, EC-8, EC-9, RT-1). IDs prefixed **`V101-`** are new checks specific to this issue's transcription/closeout obligations. No new synthetic-insert design is introduced — Appendix A points back to the runbook's authored SQL.

**Snapshot-threshold note (D8):** all timeout checks use **synthetic run rows with real or small threshold values** so each check completes in minutes, not the seeded ~62-minute window. The interlock proof deliberately uses the **real** thresholds (3600/120) because AC5's claim is specifically about a *legitimately long* healthy run.

## Source input summary

| Item | Value |
|------|-------|
| Reaper function | `reap_stale_runs()` — `timed_out` (running past `max_runtime_seconds + grace_seconds`, clock `started_at`) and `failed_to_start` (queued past `start_timeout_seconds`, clock `queued_at`); writes one explanatory `run_events` row per transition; since #99 also closes open `run_steps` on both branches |
| Read-time view | `v_runs.effective_status` — two independent read-time branches: `running → timed_out` (observed under #94) and `queued → failed_to_start` (**not yet observed** — this plan's AC4 target) |
| Scheduler | `pg_cron`, `reap-stale-runs`, `* * * * *` — already scheduled and firing (#94 AC1 PASS) |
| Invocation prereqs | Pre-insert the `queued` row before invoking (D1 / #100, runbook §4.0); bare-payload `--prompt-file` form (#97, runbook §4.1) |
| Seeded identities | agent `slug='dependency-update'`; repos `llipe/memo-cli`, `llipe/tf-ecommerce-mgmt` |
| SDK fallback | On unreachable PostgREST, transient failures retry 3× (`HTTP_RETRIES=3`) then dump payloads to stderr → CloudWatch; agent completes regardless; 4xx not retried |

## Acceptance criteria extraction

Numbered from the issue's "Acceptance criteria" section (mapped to the underlying #94 ACs they close):

- **AC1 (#101)** — `v_runs.effective_status` reports `failed_to_start` for a past-threshold `queued` row **before** the reaper materializes it. _(closes #94 AC4 `queued`-half)_
- **AC2 (#101)** — A healthy `running` row with real thresholds survives multiple cron ticks un-reaped, and is reaped once past `max_runtime + grace`. _(closes #94 AC5 interlock half; dep-update AC-36 dynamic half)_
- **AC3 (#101)** — The true cold-start gap is measured and recorded against `grace_seconds=120`, with dependency-update PRD open question 8 resolved or explicitly re-scoped. _(closes #94 AC5 cold-start half)_
- **AC4 (#101)** — With Supabase unreachable, the agent completes and its payloads are recoverable from CloudWatch; `SUPABASE_URL` is restored and verified. _(closes #94 AC6)_
- **AC5 (#101)** — Runbook and both traceability matrices reflect the final results. _(documentation completeness)_
- **AC6 (#101)** — Issue #94 is closed with all 7 ACs verified. _(closeout)_

**Business rules / constraints:**
- Two clocks, two states (D8/D9): the `queued` branch keys on `queued_at + start_timeout_seconds`; it must resolve to `failed_to_start`, never `timed_out`.
- The interlock is **threshold-driven**: a healthy run must be untouched *before* the boundary and reaped *after* it — proving both directions is required (an always-spare reaper would falsely "pass" the un-reaped half).
- The cold-start gap **MUST** be measured as `started_at − invoke-timestamp` (the `date -u` method), **never** `started_at − queued_at` on a hand-inserted row. The prior **185.7 s figure is INVALID** and must not be cited or used for a `grace_seconds` decision.
- `SUPABASE_URL` **MUST** be restored after AC6 (runbook §5.5); leaving it broken silently invalidates every later verification.
- Reporting failure **MUST NOT** kill the agent (AC6 core property).

**Non-goals (must remain untested / untouched):** fixing #98 (agent dies mid-`validate`); the Layer 2.5 automated DB test harness; heartbeat detection, run cancellation, `run_events` retention (R3), panel/UI. The real-20-minute-`llm_fix` framing of AC5 is intentionally **replaced** by the synthetic interlock proof so this issue does not wait on #98.

## E2E scenarios (black-box)

"Wait one tick" = up to 60 s for the next `* * * * *` fire. Reused IDs match `test-plan-issue-94.md`; `V101-*` are new.

### E2E-4 (queued half) — View leads the reaper for the `queued → failed_to_start` branch (AC1 #101 / #94 AC4) · [MANUAL]

- **Setup:** Insert a synthetic `queued` row with `queued_at` backdated 90 s and `start_timeout_seconds=60` so it is already past threshold (runbook §2.2). Capture `id`.
- **Action:** **Immediately, before the next cron tick**, read the view.
- **Assert:** `select status, effective_status from v_runs where id=:id;` → `status='queued'` **and** `effective_status='failed_to_start'` simultaneously.
- **Positive/negative:** positive = the split is observed on the `queued` branch. Edge (recovery) = if the tick already fired and both columns read `failed_to_start`, use the runbook §3.3 unschedule → insert → observe → **re-schedule** fallback; forgetting to re-schedule is the trap.
- **Why:** #94 verified only the `running` branch of `v_runs`; the `queued` branch was accepted by inspection of the same `case` expression. This is the missing observation.

### E2E-5 — Healthy long-running run is not reaped early; cold-start gap recorded (AC2 + AC3 #101 / #94 AC5, dep-update AC-36) · [MANUAL]

Split into an interlock half (V101-1, unblocked) and a cold-start half (V101-2, unblocked). The original "let a real 20-min `llm_fix` run complete" action is **out of scope** here (blocked by #98); the synthetic proof supersedes it.

#### V101-1 — Synthetic interlock proof (runbook §4.4)

- **Setup:** Insert a synthetic `running` row with **real** thresholds (`max_runtime_seconds=3600`, `grace_seconds=120`), `started_at` backdated ~30 min (well under 3720 s). Capture `id`.
- **Action:** Let the reaper tick across several minutes; read `runs`/`v_runs` and count reaper events. Then backdate `started_at` past 3720 s (`now() - interval '63 min'`) and wait one tick.
- **Assert:**
  - While healthy: `status='running'`, `effective_status='running'`, and `select count(*) from run_events where run_id=:id and data->>'reaped_by'='reap_stale_runs';` = **0** across every tick.
  - After crossing the boundary: `status='timed_out'`, `error_code='RUNTIME_TIMEOUT'`, exactly one explanatory event.
- **Positive/negative:** positive = un-reaped while healthy (the interlock); negative/edge = reaps only after the boundary — proving the reaper is threshold-driven, not indiscriminate.

#### V101-2 — Valid cold-start measurement (runbook §4.0/§4.1/§4.3)

- **Setup:** Pre-insert the `queued` row (§4.0 / D1 / #100); put its `id` as `run_id` in `/tmp/invoke-94.json`.
- **Action:** Record the invoke wall-clock with `date -u +"%Y-%m-%dT%H:%M:%S.%3NZ"`, then `agentcore invoke --prompt-file /tmp/invoke-94.json` (bare payload, §4.1). Confirm `started_at` becomes non-null.
- **Assert:**
  - **True cold-start gap = `started_at` − (recorded `date -u` timestamp)**, recorded distinctly from `started_at − queued_at`.
  - Gap is comfortably `< grace_seconds (120)`; record the number and the resolution/re-scope of dependency-update PRD open question 8.
- **Guard (negative):** explicitly reject `started_at − queued_at` on a hand-inserted row as the cold-start figure; the 185.7 s value is INVALID.

### E2E-6 — CloudWatch fallback when Supabase is unreachable (AC4 #101 / #94 AC6) · [MANUAL]

- **Setup:** Record the correct `SUPABASE_URL` from `agents/dependency-update/agentcore/agentcore.json` (`runtimes[].envVars`), then point it at an unreachable host (runbook §5.1). Pre-insert the `queued` row (§4.0).
- **Action:** Invoke with the bare-payload `--prompt-file` form (§4.1).
- **Assert:**
  - The agent **completes** (normal exit); the invocation does not crash — reporting failure never kills the agent.
  - After the SDK's 3 retries, the failed payloads appear in the runtime's CloudWatch log group via stderr (`aws logs tail ... | grep -iE "supabase|retry|payload|report"`).
  - **Restore** `SUPABASE_URL` (§5.5); a subsequent invocation reports to Supabase normally (`select status from runs where id=:new_id;` updates).
- **Negative pairing:** EC-8 (4xx contract error is *not* retried, distinct from the transient path retried 3× then dumped).

### V101-3 — Runbook + both matrices reflect final results (AC5 #101) · [DEV]

- **Setup / Action:** After E2E-4/-5/-6 observations exist.
- **Assert (doc review):**
  - Runbook §2/§4/§5 results tables filled from recorded observations; the §Verification-status-summary AC5/AC6 rows and the AC4 note flipped to **PASS**.
  - `workstream/traceability-matrix-issue-94.md` AC4/AC5/AC6 Observed-result + Verdict columns filled; Coverage-status shows **7/7 verified**; the "185.7 s invalid — do not cite" caution retained.
  - `workstream/traceability-matrix-dep-update-agent.md` AC-36 updated to **fully exercised** (static + dynamic).
  - No residual `⏳ PENDING` / `not executed` markers tied to #101 remain.

### V101-4 — Issue #94 closed with all 7 ACs verified (AC6 #101) · [MANUAL/DEV]

- **Setup / Action:** After V101-3 passes.
- **Assert:** All 7 #94 ACs (AC1–AC7) read PASS in the runbook summary; #94 is `CLOSED` with a closing comment linking the evidence (matrices + runbook). The #101 checklist is fully `[x]` and reconciled with the local task list.

## Contract validation scenarios

Only the contracts touched by the residual checks are (re)asserted here; the full CT-1 transition table was already exercised under #94.

### CT-2 (queued branch) — View/reaper consistency for `queued → failed_to_start` · [MANUAL]

- **Property:** For a past-threshold `queued` row, `v_runs.effective_status='failed_to_start'` **before** the reaper fires, and `runs.status` equals that same value **after** the next tick. The pre-tick read and post-tick materialized value MUST match.
- **Assert:** snapshot `effective_status` at insert-time (pre-tick) and `status` after one tick; both `failed_to_start`. (This is the `queued`-branch instance of #94 CT-2, whose `running` branch already passed.)

### CT-3 (START_TIMEOUT) — Event schema contract for the reaped `queued` row · [MANUAL]

- **Property:** The reaper-written event for the `queued`-branch reap carries `level='error'`, human-readable `message`, `data->>'reaped_by'='reap_stale_runs'`, `data->>'reason'='START_TIMEOUT'`, and `seq = max(seq)+1`.
- **Assert:** `select seq, level, message, data from run_events where run_id=:id order by seq;`

## Edge-case catalog

Categories relevant to the residual scope are enumerated; others were covered under #94 and are not re-run. Reused IDs match `test-plan-issue-94.md`.

### EC-4: Clock skew / `started_at` in the future (interlock guard) · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC2 (#101) |
| Category | Timing |
| Input / Setup | The interlock synthetic row (V101-1) while still healthy — `started_at` well within `now()`; confirm no future-dated skew trips a spurious reap |
| Expected Result | Not reaped while `elapsed < 3720 s`; zero reaper events. |
| Risk if Missed | A skew or off-by-one would reap a healthy long run — the exact failure AC5 exists to rule out. |

### EC-2: Running row inside the grace window is not reaped · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC2 (#101) |
| Category | Data Boundaries, Timing |
| Input / Setup | Interlock row at `elapsed` between `max_runtime` (3600) and `max_runtime + grace` (3720) |
| Expected Result | Still `running` — grace not yet exceeded. |
| Risk if Missed | Grace collapse → healthy runs reaped exactly when the fleet's whole point (D8) is to protect them. |

### EC-8: Agent reporting hits transient (unreachable) vs 4xx (contract) · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC4 (#101) |
| Category | Failure Modes |
| Input / Setup | (a) unreachable `SUPABASE_URL` → transient; (b) malformed payload → 4xx |
| Expected Result | (a) retried 3× then dumped to stderr/CloudWatch; (b) **not** retried (contract error), single failure recorded. Agent completes in both cases. |
| Risk if Missed | Retry storm on non-retryable errors, or agent crash on reporting failure — violates "reporting never kills the agent." |

### EC-9: `run_events.seq` monotonicity when the row already has events · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC1, AC2 (#101) |
| Category | Data Boundaries |
| Input / Setup | The `queued`-branch reap (E2E-4) and the interlock boundary reap (V101-1), each on a row that may already carry events |
| Expected Result | Reaper event gets `seq = max(seq)+1`, no `uq_run_events_seq` violation. |
| Risk if Missed | A collision aborts the reaper transaction, leaving the run stuck. |

### V101-EC-1: `SUPABASE_URL` left broken after AC6 · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC4 (#101) |
| Category | State / Failure Modes (procedural) |
| Input / Setup | After E2E-6, before any later check |
| Expected Result | `SUPABASE_URL` restored to the recorded value and a post-restore invocation reports normally; if skipped, later pre-inserted rows get reaped `failed_to_start` with `started_at=null` and zero agent events — the tell-tale of a still-broken URL. |
| Risk if Missed | Every subsequent verification silently produces false negatives. |

**Categories marked N/A** (unchanged from #94): Auth & Permissions (reaper is `security definer`, no v1 login — R1); Resource Exhaustion (R3/R5 out of scope); API Versioning (no versioned surface). Input-Domain-null (EC-3) and the start-timeout boundary (EC-1) were exercised under #94 and are not re-run.

## Randomized tactics and seed policy

The residual scope has one high-value randomized target: the interlock boundary (does a healthy run stay un-reaped across the full sub-threshold range, and reap exactly once past it). Seeds follow `<tactic>-<AC>-<unix-ts>-<hex>`; replay by re-inserting rows generated from the captured seed. RT-2/RT-3 from #94 are not re-run here (already exercised); RT-1 is re-scoped to the interlock direction.

### RT-1 (interlock) — Property: a healthy run is reaped iff past `max_runtime + grace` · [MANUAL]
| Field | Value |
|---|---|
| AC(s) | AC2 (#101) |
| Tactic type | property-based |
| Input surface | Synthetic `running` rows with fixed real thresholds (3600/120) and randomized `elapsed` drawn across `[0, 5000] s` (straddling the 3720 s boundary) |
| Property / Oracle | After a reaper tick: row is `timed_out` **iff** `elapsed > 3720`; while `elapsed ≤ 3720` it stays `running` with zero reaper events; on transition, exactly one explanatory event with `reason='RUNTIME_TIMEOUT'` |
| Iterations | 100 |
| Seed | `prop-AC2-{ts}-{hex}` (records the generated `elapsed` values) |
| Replay instruction | Re-insert rows for the captured `elapsed` values, run one reaper tick, re-assert |
| Shrink strategy | Reduce to the single `elapsed` nearest 3720 s that mis-transitions |

**Failure triage:** on any randomized failure, follow the verifier failure-triage workflow — capture seed + `elapsed`, replay to confirm determinism, minimize to the nearest-boundary value, classify (spec gap → `product-engineer`; implementation defect → `developer`; non-reproducing after ≤3 tries → `inconclusive`), report with the minimized input and related AC.

## Execution checklist

Order matters: the reaper is already scheduled (#94 AC1 PASS), so AC1/AC2/AC3/AC4 checks below can run immediately; AC5/AC6 are transcription/closeout and depend on all observations existing.

- [ ] **[MANUAL]** E2E-4 (queued half) / AC1 — `effective_status='failed_to_start'` before tick; pair CT-2(queued), CT-3(START_TIMEOUT), EC-9.
- [ ] **[MANUAL]** V101-1 / AC2 — interlock: healthy row un-reaped across ticks, then reaped past 3720 s; pair EC-2, EC-4, RT-1(interlock).
- [ ] **[MANUAL]** V101-2 / AC3 — valid `date -u` cold-start gap recorded vs grace=120; reject the 185.7 s figure; resolve/re-scope PRD open question 8.
- [ ] **[MANUAL]** E2E-6 / AC4 — CloudWatch fallback; pair EC-8; **restore `SUPABASE_URL`** (V101-EC-1).
- [ ] **[DEV]** V101-3 / AC5 — runbook §2/§4/§5 results tables + both traceability matrices updated; no residual PENDING markers.
- [ ] **[MANUAL/DEV]** V101-4 / AC6 — all 7 #94 ACs PASS; #94 closed with evidence-linking comment; #101 checklist reconciled.

## Appendix A — Synthetic inserts and invocation forms

No new SQL is designed here — use the **authored, ready-to-paste** blocks in the runbook to keep this plan and the operator procedure in lockstep:

| Check | Runbook block |
|-------|---------------|
| E2E-4 (queued half) | §2.2 insert (backdated `queued_at`, `start_timeout_seconds=60`) + §2.3 pre-tick `v_runs` query |
| V101-1 (interlock) | §4.4 synthetic `running` insert (real thresholds, backdated `started_at`), then backdate past 3720 s |
| V101-2 (cold-start) | §4.0 pre-insert + §4.1 `date -u` + `agentcore invoke --prompt-file` + §4.3 gap computation |
| E2E-6 (AC6) | §5.1 break `SUPABASE_URL` → §5.2–§5.4 invoke + CloudWatch tail → §5.5 restore |
| Cleanup | `delete from runs where id = any(:synthetic_ids);` (events cascade) after each check |

**Invocation prerequisites (both mandatory, both authored in the runbook):**
- Pre-insert the `queued` row before invoking (§4.0 / D1 / #100) — a direct invoke leaves the run invisible.
- Use the **bare inner JSON** via `--prompt-file` (§4.1 / #97) — the pre-wrapped form's double-wrap history is documented there.

## Handoff

- Design Mode complete. Every AC maps to ≥1 positive and ≥1 negative/edge check (see `workstream/traceability-matrix-issue-101.md`).
- Next: `developer` executes the **[DEV]** transcription/sync sub-tasks and hands the operator the **[MANUAL]** runbook steps (§2.2/§2.3, §4.0–§4.4, §5).
- After execution, run **verifier Audit Mode** against the delivered runbook results + both updated matrices + the #94 closeout to produce `fidelity-report-issue-101.md`.
