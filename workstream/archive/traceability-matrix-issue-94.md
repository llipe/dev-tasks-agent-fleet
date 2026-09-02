# Traceability Matrix — Issue #94: Schedule pg_cron Reaper & Verify Stale-Run Detection

> **Mode:** verifier Design Mode
> **Repository:** `llipe/dev-tasks-agent-fleet`
> **Source issue:** [#94](https://github.com/llipe/dev-tasks-agent-fleet/issues/94)
> **Companion:** `workstream/test-plan-issue-94.md`

Mapping format: `AC-ID -> Test-Case-ID -> Observed-Result -> Pass/Fail/Drift`. Observed-result and verdict columns are filled during execution (Audit Mode); in Design Mode they are `pending`.

## AC coverage

Every AC has at least one positive test and at least one negative/edge test.

| AC | Description | Positive test(s) | Negative / edge test(s) | Exec role | Observed result | Verdict |
|----|-------------|------------------|-------------------------|-----------|-----------------|---------|
| **AC1** | `reap-stale-runs` scheduled `* * * * *` and `cron.job_run_details` shows successful recent runs | E2E-1 | EC-6 (duplicate schedule → single job), EC-7 (failed tick surfaces in job_run_details) | [MANUAL] | job registered `* * * * *`, active; recent `succeeded` runs | ✅ PASS |
| **AC2** | Synthetic `queued` past `start_timeout_seconds` → `failed_to_start` + explanatory event within one tick | E2E-2, CT-1 (queued past-threshold row), CT-3 (event schema) | EC-1 (boundary ±1s), EC-9 (seq monotonicity), CT-1 (queued within-threshold stays `queued`) | [MANUAL] | synthetic row → `failed_to_start`/`START_TIMEOUT` + event; also orphan run `cba355cb-…` reaped at 324s vs 300s | ✅ PASS |
| **AC3** | Synthetic `running` past `max_runtime+grace` → `timed_out` + explanatory event within one tick | E2E-3, CT-1 (running past-threshold row), CT-3 (event schema) | EC-2 (within grace stays running), EC-3 (null started_at not reaped), EC-4 (future started_at not reaped), EC-9 | [MANUAL] | **real run `f63ac9f3-…`**: elapsed 3732.30s vs 3720s threshold, `RUNTIME_TIMEOUT`, event at `seq=10` | ✅ PASS |
| **AC4** | `v_runs.effective_status` reports terminal status **before** the reaper materializes it (two-layer) | E2E-4 (both queued + running halves), CT-2 (view/reaper consistency) | CT-1 terminal-rows-untouched (view must not diverge for already-terminal rows) | [MANUAL] | `running` half: synthetic split observed pre-tick + real-run convergence. **`queued`→`failed_to_start` read-time half observed 2026-09-01 under [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101)** — pre-tick view read `queued | failed_to_start` on the §2.2 row. Both branches now observed. | ✅ PASS |
| **AC5** | Real long-running `llm_fix` not reaped early; cold-start gap recorded vs `grace_seconds=120` (AC-36 dynamic half) | E2E-5 | EC-2 (grace-window protection, synthetic analog), EC-4 (clock skew) | [MANUAL] | **verified 2026-09-01 under [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101)** via §4.4 synthetic interlock proof (real thresholds 3600/120: un-reaped across ticks while healthy, reaped once past 3720 s) + valid §4.1 cold-start ≈ **4.2 s** ≪ grace 120. Original 20-min-`llm_fix` framing (blocked by #98) superseded by the synthetic proof. | ✅ PASS |
| **AC6** | Supabase unreachable → agent completes and payloads recoverable from CloudWatch | E2E-6 | EC-8 (4xx not retried vs transient retried 3× then dumped) | [MANUAL] | **verified 2026-09-01/02 under [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101)** — run `378e8636-…` with unresolvable `SUPABASE_URL` completed `failed` (no crash/hang), SDK dumped every lost payload to CloudWatch (`payload perdido` lines), `SUPABASE_URL` restored. Failure-classification defect (`UNHANDLED_ERROR` → classified `CredentialError`) fixed in [#106](https://github.com/llipe/dev-tasks-agent-fleet/issues/106)/PR #107, pending redeploy — does not affect the core AC6 claim | ✅ PASS |
| **AC7** | Scheduling step + all results documented in the deployment runbook | E2E-7 (doc review: schema uncommented, runbook sections, matrix updated) | — (documentation completeness; negative = missing section/result flagged during review) | [DEV] | schema uncommented; `issue-94-reaper-verification.md` created; §18 + ADR-004 recorded | ✅ PASS |

## Contract & randomized coverage roll-up

| Test | Type | ACs covered | Exec role |
|------|------|-------------|-----------|
| CT-1 | State-transition contract | AC2, AC3, AC4 | [MANUAL] |
| CT-2 | View/reaper consistency contract | AC4 | [MANUAL] |
| CT-3 | Event schema contract | AC2, AC3 | [MANUAL] |
| RT-1 | Property: transition iff past threshold | AC2, AC3 | [MANUAL] |
| RT-2 | Fuzz: malformed/extreme snapshot values | AC2, AC3 | [MANUAL] |
| RT-3 | Stateful walk: mixed population under repeated ticks | AC1, AC2, AC3, AC4 | [MANUAL] |

## Edge-case coverage index

| EC | Category | ACs | Positive or negative role |
|----|----------|-----|---------------------------|
| EC-1 | Data Boundaries | AC2 | boundary (negative pairing for E2E-2) |
| EC-2 | Data Boundaries / Timing | AC3, AC5 | negative (within-grace must not reap) |
| EC-3 | Input Domain (null) | AC3 | negative (null clock guard) |
| EC-4 | Timing | AC3, AC5 | negative (future start not reaped) |
| EC-5 | Timing & Concurrency / Idempotency | AC2, AC3 | negative (no double-process / double-event) |
| EC-6 | Idempotency / State | AC1 | negative (single job on re-schedule) |
| EC-7 | Failure Modes | AC1 | observability (failed tick visible) |
| EC-8 | Failure Modes | AC6 | negative (4xx not retried) |
| EC-9 | Data Boundaries | AC2, AC3 | negative (seq monotonicity, no uq collision) |

## Coverage status

- **ACs designed:** 7 / 7 — every AC maps to ≥1 positive and ≥1 negative/edge test.
- **ACs verified:** 7 / 7 — AC1–AC7 all PASS. (AC5, the AC4 `queued`-half, and AC6 were completed under [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101) on 2026-09-01/02.)
- **ACs pending:** 0 / 7.
- **Residual verification owner:** none remaining. [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101) completed the residual AC4-`queued`-half, AC5, and AC6 checks.
- **Post-verification follow-ups (defects/hardening, not #94/#101 blockers):** [#106](https://github.com/llipe/dev-tasks-agent-fleet/issues/106) (fixed, PR #107) transport-error classification; [#108](https://github.com/llipe/dev-tasks-agent-fleet/issues/108) Secrets Manager classification; [#109](https://github.com/llipe/dev-tasks-agent-fleet/issues/109) RequestException-subclass test hardening. The #106 classification fix awaits merge + runtime redeploy before it is re-observed live; the AC6 *core* claim (agent completes, CloudWatch recoverable) is already verified and independent of that redeploy.
- **Invalid measurement — do not cite:** the cold-start figure of 185.7 s recorded during AC5 attempts is confounded by human delay between the row INSERT and `agentcore invoke` (the agent's first log and `started_at` are 180 ms apart). It is not a cold-start measurement and must not inform a `grace_seconds` decision.
- **Bonus coverage achieved:** EC-9 (`seq` monotonicity) confirmed incidentally — the reaper event on the real run took `seq=10` after the agent's 1–9 with no `uq_run_events_seq` collision.
- **Out-of-scope, intentionally untested:** heartbeat detection, run cancellation, `run_events` retention (R3), panel/UI — matches issue "Out of scope"; the plan asserts these remain untouched (task 7.2) rather than testing them.

## Notes on evidence type

Because this issue is infrastructure/verification, "test evidence" is live-environment observation (SQL result rows, `cron.job*` catalog rows, CloudWatch log lines, runbook content) rather than an automated test-suite run. Audit Mode will collect these as the per-AC evidence and fill the Observed-result / Verdict columns above.
