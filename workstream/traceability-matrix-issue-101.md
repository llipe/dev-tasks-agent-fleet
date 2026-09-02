# Traceability Matrix — Issue #101: Complete Issue #94 AC5/AC6 Reaper Verification

> **Mode:** verifier Design Mode
> **Repository:** `llipe/dev-tasks-agent-fleet`
> **Source issue:** [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101)
> **Companion:** `workstream/test-plan-issue-101.md`
> **Rolls up into:** `workstream/traceability-matrix-issue-94.md` (AC4/AC5/AC6), `workstream/traceability-matrix-dep-update-agent.md` (AC-36)

Mapping format: `AC-ID -> Test-Case-ID -> Observed-Result -> Pass/Fail/Drift`. Observed-result and verdict columns are filled during execution (Audit Mode); in Design Mode they are `pending`. Test IDs reused verbatim from `test-plan-issue-94.md` are marked `(reused)`; `V101-*` and `V101-EC-*` are new to this issue.

## AC coverage

Every #101 AC has at least one positive test and at least one negative/edge test. The right-hand column records which #94 AC each closes.

| AC (#101) | Description | Positive test(s) | Negative / edge test(s) | Exec role | Closes | Observed result | Verdict |
|-----------|-------------|------------------|-------------------------|-----------|--------|-----------------|---------|
| **AC1** | `v_runs.effective_status` reports `failed_to_start` for a past-threshold `queued` row before the reaper materializes it | E2E-4 (queued half) (reused), CT-2 (queued branch), CT-3 (START_TIMEOUT) | EC-9 (seq monotonicity), E2E-4 recovery path (§3.3 unschedule/re-schedule if tick fired) | [MANUAL] | #94 AC4 (`queued` half) | pre-tick view read `queued \| failed_to_start` (2026-09-01) | ✅ PASS |
| **AC2** | Healthy `running` row with real thresholds survives multiple ticks un-reaped, then reaps once past `max_runtime + grace` | V101-1 (interlock, healthy → un-reaped) | EC-2 (inside grace not reaped), EC-4 (no future-skew reap), V101-1 boundary half (reaps only past 3720 s), RT-1 (interlock property) | [MANUAL] | #94 AC5 (interlock), dep-update AC-36 (dynamic half) | un-reaped across ticks (0 reaper events), reaped after backdating past 3720 s (2026-09-01) | ✅ PASS |
| **AC3** | True cold-start gap measured and recorded vs `grace_seconds=120`; PRD open question 8 resolved or re-scoped | V101-2 (valid `date -u` gap < 120) | V101-2 guard (reject `started_at−queued_at`; 185.7 s INVALID) | [MANUAL] | #94 AC5 (cold-start) | ≈ 4.2 s ≪ 120; PRD open question 8 resolved (grace adequate) (2026-09-01) | ✅ PASS |
| **AC4** | With Supabase unreachable, agent completes and payloads recoverable from CloudWatch; `SUPABASE_URL` restored + verified | E2E-6 (reused: completes + CloudWatch payloads) | EC-8 (4xx not retried vs transient retried 3×), V101-EC-1 (restore `SUPABASE_URL`) | [MANUAL] | #94 AC6 | run `378e8636-…`: completed `failed` (no crash), payloads dumped to CloudWatch, `SUPABASE_URL` restored (2026-09-02). Classification defect → #106/PR #107 (fixed, pending redeploy) | ✅ PASS |
| **AC5** | Runbook and both traceability matrices reflect final results | V101-3 (doc review: tables filled, matrices at 7/7) | V101-3 negative (grep finds no residual `⏳ PENDING`/`not executed` tied to #101; "185.7 s invalid" caution retained) | [DEV] | documentation completeness | runbook §2/§4/§5 + status-summary updated; issue-94 matrix 7/7; dep-update AC-36 fully exercised; "185.7 s invalid" caution retained (2026-09-02) | ✅ PASS |
| **AC6** | Issue #94 closed with all 7 ACs verified | V101-4 (all 7 #94 ACs PASS, #94 CLOSED) | V101-4 negative (must not close while any #94 AC still PENDING or PR unmerged) | [MANUAL/DEV] | closeout | #94 now at **7/7** verified; ready to close (pending user go-ahead) | ⏳ ready |

## Contract & randomized coverage roll-up

| Test | Type | ACs (#101) covered | Exec role | Note |
|------|------|--------------------|-----------|------|
| CT-2 (queued branch) | View/reaper consistency contract | AC1 | [MANUAL] | `queued` instance of #94 CT-2 (`running` branch already PASS) |
| CT-3 (START_TIMEOUT) | Event schema contract | AC1 | [MANUAL] | reaper event schema on the `queued`-branch reap |
| RT-1 (interlock) | Property: reap iff past `max_runtime+grace` | AC2 | [MANUAL] | re-scoped from #94 RT-1 to the interlock direction |

## Edge-case coverage index

| EC | Category | ACs (#101) | Positive or negative role |
|----|----------|------------|---------------------------|
| EC-2 (reused) | Data Boundaries / Timing | AC2 | negative (inside grace must not reap) |
| EC-4 (reused) | Timing | AC2 | negative (future/skew start not reaped) |
| EC-8 (reused) | Failure Modes | AC4 | negative (4xx not retried vs transient retried) |
| EC-9 (reused) | Data Boundaries | AC1, AC2 | negative (seq monotonicity, no uq collision) |
| V101-EC-1 (new) | State / Failure Modes (procedural) | AC4 | negative (must restore `SUPABASE_URL`) |

## Coverage status

- **ACs designed:** 6 / 6 (#101) — every AC maps to ≥1 positive and ≥1 negative/edge test.
- **ACs verified:** 0 / 6 — Design Mode; execution pending (Audit Mode fills verdicts).
- **Blocked ACs:** none. The AC2 interlock uses the synthetic proof (runbook §4.4) that depends on nothing; #98 is explicitly out of scope. The AC3 cold-start needs *a* invocation, not a *long* one.
- **Roll-up targets on completion:** `traceability-matrix-issue-94.md` → AC4/AC5/AC6 PASS (7/7); `traceability-matrix-dep-update-agent.md` → AC-36 fully exercised.
- **Invalid measurement — do not cite:** the cold-start figure of 185.7 s is confounded by human delay between the row INSERT and `agentcore invoke` (agent first log and `started_at` 180 ms apart). It is not a cold-start measurement and must not inform a `grace_seconds` decision. V101-2's positive assertion is the *valid* `date -u`-based gap.
- **Out-of-scope, intentionally untested:** #98 fix, Layer 2.5 DB test harness, heartbeat detection, run cancellation, `run_events` retention (R3), panel/UI. The real-20-minute-`llm_fix` framing of #94 AC5 is deliberately replaced by V101-1.

## Notes on evidence type

As with #94, "test evidence" is live-environment observation (SQL result rows, `v_runs` reads, `run_events` rows, CloudWatch log lines) plus repo-side doc/matrix state — not an automated test-suite run. Audit Mode collects these as per-AC evidence and fills the Observed-result / Verdict columns above.
