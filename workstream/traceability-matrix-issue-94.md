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
| **AC1** | `reap-stale-runs` scheduled `* * * * *` and `cron.job_run_details` shows successful recent runs | E2E-1 | EC-6 (duplicate schedule → single job), EC-7 (failed tick surfaces in job_run_details) | [MANUAL] | pending | pending |
| **AC2** | Synthetic `queued` past `start_timeout_seconds` → `failed_to_start` + explanatory event within one tick | E2E-2, CT-1 (queued past-threshold row), CT-3 (event schema) | EC-1 (boundary ±1s), EC-9 (seq monotonicity), CT-1 (queued within-threshold stays `queued`) | [MANUAL] | pending | pending |
| **AC3** | Synthetic `running` past `max_runtime+grace` → `timed_out` + explanatory event within one tick | E2E-3, CT-1 (running past-threshold row), CT-3 (event schema) | EC-2 (within grace stays running), EC-3 (null started_at not reaped), EC-4 (future started_at not reaped), EC-9 | [MANUAL] | pending | pending |
| **AC4** | `v_runs.effective_status` reports terminal status **before** the reaper materializes it (two-layer) | E2E-4 (both queued + running halves), CT-2 (view/reaper consistency) | CT-1 terminal-rows-untouched (view must not diverge for already-terminal rows) | [MANUAL] | pending | pending |
| **AC5** | Real long-running `llm_fix` not reaped early; cold-start gap recorded vs `grace_seconds=120` (AC-36 dynamic half) | E2E-5 | EC-2 (grace-window protection, synthetic analog), EC-4 (clock skew) | [MANUAL] | pending | pending |
| **AC6** | Supabase unreachable → agent completes and payloads recoverable from CloudWatch | E2E-6 | EC-8 (4xx not retried vs transient retried 3× then dumped) | [MANUAL] | pending | pending |
| **AC7** | Scheduling step + all results documented in the deployment runbook | E2E-7 (doc review: schema uncommented, runbook sections, matrix updated) | — (documentation completeness; negative = missing section/result flagged during review) | [DEV] | pending | pending |

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

- **ACs covered:** 7 / 7 — every AC maps to ≥1 positive and ≥1 negative/edge test (AC7 is documentation, negative role = review flags a missing section).
- **Uncovered ACs:** none.
- **Out-of-scope, intentionally untested:** heartbeat detection, run cancellation, `run_events` retention (R3), panel/UI — matches issue "Out of scope"; the plan asserts these remain untouched (task 7.2) rather than testing them.

## Notes on evidence type

Because this issue is infrastructure/verification, "test evidence" is live-environment observation (SQL result rows, `cron.job*` catalog rows, CloudWatch log lines, runbook content) rather than an automated test-suite run. Audit Mode will collect these as the per-AC evidence and fill the Observed-result / Verdict columns above.
