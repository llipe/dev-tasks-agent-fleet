# Issue Refinement — #101: Complete Issue #94 AC5/AC6 Reaper Verification

> **Mode:** product-engineer Issue Mode → Refine
> **Repository:** `llipe/dev-tasks-agent-fleet`
> **Source issue:** [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101) — `test(infra): complete issue #94 AC5/AC6 reaper verification`
> **Parent:** [#94](https://github.com/llipe/dev-tasks-agent-fleet/issues/94) (PR #96)

## Changelog

| Version | Date       | Summary                                                        | Author           |
| ------- | ---------- | ------------------------------------------------------------- | ---------------- |
| 1.0     | 2026-09-01 | Initial refinement. Scope confirmed; no design change needed. | product-engineer |

## 1. Summary

Issue #94 scheduled the `pg_cron` reaper and verified 5 of its 7 acceptance criteria (AC1, AC2, AC3, AC4-`running`-half, AC7). Three verification checks remain and are carried here:

- **AC4 residual** — the `queued → failed_to_start` read-time half of `v_runs.effective_status` (only the `running → timed_out` half was observed under #94; the `queued` branch was verified by code inspection only).
- **AC5** — the reaper interlock (a healthy run is not reaped before its threshold) plus a *valid* cold-start gap measurement.
- **AC6** — the agent's CloudWatch stderr fallback when Supabase/PostgREST is unreachable.

This is **execution, not design**. Every procedure already exists in
[`docs/runbooks/issue-94-reaper-verification.md`](../docs/runbooks/issue-94-reaper-verification.md)
(§2.2/§2.3, §4.1, §4.2, §4.3, §4.4, §5). The deliverables are recorded observations transcribed into the runbook results tables and the two traceability matrices, then closing #94.

## 2. Why this is a separate issue

The #94 fidelity audit ([`workstream/fidelity-report-issue-94.md`](fidelity-report-issue-94.md), Drift #1/#3/#4) found the original AC5 blocker attribution over-broad: only the "real 20+ minute `llm_fix` run" framing depends on [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98). Specifically:

- The **synthetic interlock proof** (runbook §4.4) uses real thresholds (`max_runtime_seconds=3600`, `grace_seconds=120`) on a backdated synthetic row and depends on **nothing** — it is unblocked today.
- The **cold-start measurement** needs *a* real invocation, not a *long* one — also unblocked.
- The previously recorded `insert_to_start = 185.7 s` figure is **INVALID** (it includes human delay between the manual row INSERT and `agentcore invoke`; the agent's first log and `started_at` were 180 ms apart). It **MUST NOT** be cited as a cold-start measurement or used to justify a `grace_seconds` change.

## 3. Refined Scope

### In scope

1. **AC4 residual** (runbook §2.2/§2.3): insert a backdated `queued` synthetic row and query `select status, effective_status from v_runs where id=':id';` **before** the next cron tick — expect `queued | failed_to_start`.
2. **AC5 interlock half** (runbook §4.4): synthetic `running` row with real thresholds, `started_at` backdated ~30 min; confirm it stays `running` with zero reaper events across several ticks, then backdate past 3720 s and confirm it reaps.
3. **AC5 cold-start half** (runbook §4.1/§4.3): measure the true gap using the `date -u` method (`started_at` minus the recorded invoke timestamp) on any completing run; record against `grace_seconds=120`; resolve or explicitly re-scope dependency-update PRD open question 8.
4. **AC6** (runbook §5): point `SUPABASE_URL` at an unreachable host, invoke, assert the agent completes (does not crash), assert payloads reach CloudWatch via stderr after the SDK's 3 retries, then **restore `SUPABASE_URL`** and confirm normal reporting resumes.
5. **Transcription**: record all results in the runbook results tables, `workstream/traceability-matrix-issue-94.md`, and update `workstream/traceability-matrix-dep-update-agent.md` AC-36 to fully exercised.
6. **Close #94** once all 7 ACs are verified.

### Out of scope

- Fixing [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98) (agent dies mid-`validate`). Only the AC5 clause that genuinely needs a *long* run waits on it; this issue uses the synthetic proof instead.
- The Layer 2.5 automated database test harness (separate, needs approval).
- Heartbeat detection, run cancellation, `run_events` retention, panel/UI work.

## 4. Acceptance Criteria (verbatim from issue)

1. `v_runs.effective_status` confirmed to report `failed_to_start` for a past-threshold `queued` row before the reaper materializes it.
2. A healthy `running` row with real thresholds survives multiple cron ticks un-reaped, and is reaped once past `max_runtime + grace`.
3. The true cold-start gap is measured and recorded against `grace_seconds=120`, with dependency-update PRD open question 8 resolved or explicitly re-scoped.
4. With Supabase unreachable, the agent completes and its payloads are recoverable from CloudWatch; `SUPABASE_URL` is restored and verified.
5. Runbook and both traceability matrices reflect the final results.
6. Issue #94 is closed with all 7 ACs verified.

## 5. Constraints & Prerequisites

- **Live-environment task.** Requires Supabase SQL Editor and AWS (AgentCore, CloudWatch) access. The tasks marked `[MANUAL]` cannot be executed by an agent; the agent's role is `[DEV]` transcription of recorded observations and GitHub sync.
- **Invocation prerequisites** (from prior defect fixes, both now resolved but still required procedure):
  - Insert the `queued` `runs` row **before** invoking (D1 / [#100](https://github.com/llipe/dev-tasks-agent-fleet/issues/100), runbook §4.0).
  - Use the bare-payload `--prompt-file` form (runbook §4.1 / [#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97)).
- **`SUPABASE_URL` restore is mandatory** (runbook §5.5): leaving it broken silently breaks every later verification.
- **No schema or data-model change.** Synthetic SQL rows are ephemeral verification fixtures (deleted at cleanup), not migrations — no migration lifecycle applies.
- **Cleanup:** delete synthetic rows after each check (events cascade).

## 6. Definition of Done

- AC4 `queued`-half observed and recorded.
- AC5 interlock proven (synthetic §4.4) and a valid cold-start gap recorded against `grace_seconds=120`; PRD open question 8 resolved or re-scoped.
- AC6 executed: agent completes with Supabase unreachable, payloads recovered from CloudWatch, `SUPABASE_URL` restored and verified.
- Runbook §2/§4/§5 results tables and the §Verification-status-summary updated to all-PASS.
- `workstream/traceability-matrix-issue-94.md` shows 7/7 verified; `workstream/traceability-matrix-dep-update-agent.md` AC-36 marked fully exercised.
- #94 closed; #101 checklist complete.

## 7. Dependencies & References

- Runbook: [`docs/runbooks/issue-94-reaper-verification.md`](../docs/runbooks/issue-94-reaper-verification.md) §2.2, §2.3, §4.1, §4.2, §4.3, §4.4, §5
- Audit that identified the gaps: [`workstream/fidelity-report-issue-94.md`](fidelity-report-issue-94.md) (Drift #1, #3, #4)
- Matrices: [`workstream/traceability-matrix-issue-94.md`](traceability-matrix-issue-94.md), [`workstream/traceability-matrix-dep-update-agent.md`](traceability-matrix-dep-update-agent.md)
- Related defects (context/prereqs): #97, #98, #100
