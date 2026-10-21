# Traceability Matrix — Agent Scheduler (verifier, Design Mode)

> Companion to [`test-plan-prd-agent-scheduler.md`](test-plan-prd-agent-scheduler.md).
> Maps every acceptance criterion to ≥1 positive and ≥1 negative/edge test, and records the
> `AC-ID → Test-Case-ID → Observed-Result → Pass/Fail/Drift` structure to be filled during
> Audit Mode. All "Observed/Result" cells are **PENDING** until implementation + audit.

## Changelog

| Version | Date       | Summary                               | Author   |
| ------- | ---------- | ------------------------------------- | -------- |
| 1.0     | 2026-10-13 | Initial matrix from the test plan.    | verifier |

## AC → test coverage (positive + negative/edge)

| AC | Positive test(s) | Negative / edge test(s) | Story / Layer | Observed | Result |
| --- | --- | --- | --- | --- | --- |
| AC1 (DST) | CT-3, RT-2, E2E-1 (persist) | EC-1 (spring-forward gap), EC-2 (fall-back double), EC-3, EC-5, EC-6, EC-7 | S-152 / L2.5+L1 | PENDING | PENDING |
| AC2 (schedule run tag) | CT-1 (positive), CT-8, E2E-1 assert | CT-1 (negative: bad identity / `RunSnapshotError`), CT-2 (fire never-start → `failed_to_start`) | S-150+S-153 / L1+L2.5 | PENDING | PENDING |
| AC3 (internal 401) | CT-2 (correct secret), E2E-4 (correct) | E2E-4 (unauth/wrong), EC-26, EC-27, EC-29, release-gate `checkInternalRejected` | S-153+S-160 / L1+E2E | PENDING | PENDING |
| AC4 (G1 overlap) | guardrail-overlap block + auto-clear | EC-10 (stale running not forever), EC-11 (different repo not blocked) | S-155 / L2.5 | PENDING | PENDING |
| AC5 (G2 no-catch-up) | fire-due-schedules recovery = next only | EC-14 (down several ticks → no burst), EC-5 (past `next_run_at`) | S-154 / L2.5 | PENDING | PENDING |
| AC6 (G3 breaker) | 3 fails → paused + 1 notification | EC-15 (mixed fire/sweep source), EC-16 (success resets), resume clears | S-157 / L2.5+L1 | PENDING | PENDING |
| AC7 (G4 cap) | 5 due / cap 3 → 3 fire | EC-12 (boundary K / K+1 / cap-met), EC-13 (stale over-count), RT-5 | S-154 / L2.5 | PENDING | PENDING |
| AC8 (G5 open-PR) | block → manual clear → resume | EC-17 (most-recent PR governs), EC-18 (new PR re-blocks), EC-19 (combined w/ G1), v1 no GitHub call | S-156 / L2.5+L1 | PENDING | PENDING |
| AC9 (notifications exactly-once) | one row per failure/pause/PR; success w/ opt-in | CT-4, EC-20 (no double), EC-21 (sweep idempotent), EC-22 (opt-in off), RT-4 | S-158 / L2.5 | PENDING | PENDING |
| AC10 (reaper failure notifies) | reaper `timed_out` → 1 `run_failed` | EC-20 (also panel-observed → still one), EC-21 | S-158 / L2.5 | PENDING | PENDING |
| AC11 (panel feed) | E2E-6 feed + mark-read | CT-7 (RLS deny-all / anon 0 rows), EC-32 (inert detail) | S-163 / L2+L2.5+E2E | PENDING | PENDING |
| AC12 (daily digest) | notable day → 1 email + marked | EC-23 (multi-day backlog), EC-24 (empty → 204/no send), EC-25 (send-then-mark seam) | S-159 / L1+L2.5 | PENDING | PENDING |
| AC13 (schema-driven form) | E2E-2 (each agent), CT-5 positive | CT-5 negative (invalid params rejected at save + fire) | S-162 / L1+L2+E2E | PENDING | PENDING |
| AC14 (CRUD behind login) | E2E-5 pause/resume/delete | E2E-3 (unauth → /login or 401), EC-28/EC-29 (internal class split) | S-161 / L2+L2.5+E2E | PENDING | PENDING |
| AC15 (no static keys) | CT-6 (OIDC→STS, `credentialSource: fly-oidc`) | CT-6 negative (`SES_SEND_FAILED` no leak), no static key in `fly secrets` | S-159 / L1+live | PENDING | PENDING |

## Coverage assertion

- **15 / 15 ACs** have at least one positive and one negative/edge test. **No uncovered AC.**
- Business-rule invariants are each pinned by a test: explicitness (every skip/block/pause
  has a reason — EC-10/11/12/14/17/19), snapshot-over-live (CT-1 negative), exactly-once
  (CT-4, EC-20/21, RT-4), effective_status-not-raw (EC-10/13), fail-closed internal auth
  (EC-26/27/29), no-catch-up (AC5/EC-14), channel-agnostic (recording tested independent of
  delivery: S-158 vs S-159/S-163), untrusted-detail-as-text (EC-32).
- **Randomized coverage:** RT-1…RT-5 carry seeds + replay per the failure-triage workflow.

## FR → AC → test rollup (completeness check)

Every FR (FR1–FR26) traces to an AC and thus to a test via the stories' FR→story map
([`user-stories-prd-agent-scheduler.md`](user-stories-prd-agent-scheduler.md) §Coverage).
FRs without a dedicated AC (foundation/config: FR1 schema, FR7 builder half, FR8 storage,
FR16 column, FR20 channel-agnostic, FR21 config) are covered by:
CT-7/CT-4 (FR1), CT-1 (FR7), CT-8/EC (FR8), EC-22 (FR16), S-158-vs-S-159/S-163 separation
(FR20), CT-6 (FR21).

## Audit-Mode fill-in protocol

When `verifier` runs Audit Mode post-implementation, each row's **Observed** gets the
evidence source (test file:case + run result) and **Result** becomes `Pass` / `Fail` /
`Drift` with an impact (Critical/Major/Minor) and intent (Intended/Unintended/Undetermined)
class. Drift routes to `product-engineer`'s `activity-drift-reconciliation`.
