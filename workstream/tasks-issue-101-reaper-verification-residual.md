# Implementation Plan - Issue #101: Complete Issue #94 AC5/AC6 Reaper Verification

> Source: [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101) · Refinement: `workstream/issue-101-reaper-verification-residual-refinement.md`
> Runbook (all procedures already authored): `docs/runbooks/issue-94-reaper-verification.md`
>
> **Task-type legend:** `[MANUAL]` = live-environment operator step (Supabase SQL Editor / AWS AgentCore / CloudWatch) that an agent cannot execute; `[DEV]` = repo-side transcription, matrix update, or GitHub sync the agent can perform from recorded observations.
>
> **No schema/data-model change:** synthetic SQL rows are ephemeral verification fixtures (deleted at cleanup), not migrations. Migration lifecycle tasks are intentionally omitted for that reason.

## Relevant Files

- `docs/runbooks/issue-94-reaper-verification.md` - Operator runbook; §2/§4/§5 results tables and the §Verification-status-summary get filled in from recorded observations.
- `workstream/traceability-matrix-issue-94.md` - AC4/AC5/AC6 Observed-result + Verdict columns and the Coverage-status section updated to 7/7 verified.
- `workstream/traceability-matrix-dep-update-agent.md` - AC-36 row updated to "fully exercised" once the AC5 dynamic half is complete.
- `docs/reference/001_schema.sql` - Read-only reference for `reap_stale_runs()` and `v_runs` (not modified).
- `agents/dependency-update/agentcore/agentcore.json` - Read-only reference for the correct `SUPABASE_URL` value (record before AC6, restore after).
- `/tmp/invoke-94.json` - Ephemeral bare-payload invocation file (not committed).

## Tasks

- [ ] 1.0 Implement Issue #101 - https://github.com/llipe/dev-tasks-agent-fleet/issues/101: Complete Issue #94 AC5/AC6 Reaper Verification

  > Note: Execution-only. Every SQL/CLI procedure already exists in the runbook; do not redesign. The `[MANUAL]` steps produce observations that the `[DEV]` steps transcribe.

  > **Progress note (2026-09-01):** Partial verification session complete — AC1, AC2, AC3 PASS (steps 1.1–1.14). AC4/Part D (steps 1.15–1.20) **deferred** by user decision ("good validation for now"). `[DEV]` transcription (1.21–1.27) and #94 closeout intentionally NOT started — #94 must not be closed until AC4 is also verified and the PR is merged. Cold-start gap measured ≈ 4.2 s vs `grace_seconds=120` (well under; PRD open question 8 resolvable as "grace adequate"). The `date -u` `%3N` note: value came through as `.3N` (macOS/BSD `date` does not expand `%3N`), so sub-second precision is unreliable but the whole-second gap conclusion holds.

  ### AC4 residual — `queued → failed_to_start` read-time half

  - [x] 1.1 **[MANUAL]** Run the runbook §2.2 insert to create a synthetic `queued` row with `queued_at` backdated 90 s (`start_timeout_seconds=60`); capture the returned `id`.
  - [x] 1.2 **[MANUAL]** Immediately (before the next cron tick) run `select status, effective_status from v_runs where id=':id';` and record the row — expect `queued | failed_to_start`.
  - [x] 1.3 **[MANUAL]** Cleanup: `delete from runs where id=':id';` (events cascade).
  - [x] 1.4 **Verify Acceptance Criterion 1:** `v_runs.effective_status` reports `failed_to_start` for a past-threshold `queued` row before the reaper materializes it. **PASS.** (Positive: expected split observed. Edge: if the tick already fired, use the runbook §3.3 unschedule/observe/re-schedule fallback, then re-schedule.)

  ### AC5 — interlock half (synthetic proof, runbook §4.4)

  - [x] 1.5 **[MANUAL]** Insert a synthetic `running` row with REAL thresholds (`max_runtime_seconds=3600`, `grace_seconds=120`), `started_at` backdated ~30 min (well under 3720 s); capture the `id`.
  - [x] 1.6 **[MANUAL]** Across several cron ticks, confirm it stays `status='running'` with `effective_status='running'` and **zero** `run_events` rows where `data->>'reaped_by' = 'reap_stale_runs'`.
  - [x] 1.7 **[MANUAL]** Backdate `started_at` past the threshold (`now() - interval '63 min'`, > 3720 s) and confirm it reaps to `timed_out` / `RUNTIME_TIMEOUT` with the explanatory event.
  - [x] 1.8 **[MANUAL]** Cleanup: delete the synthetic row.
  - [x] 1.9 **Verify Acceptance Criterion 2:** a healthy `running` row survives multiple ticks un-reaped and is reaped once past `max_runtime + grace`. **PASS.** (Positive: un-reaped while healthy. Negative/edge: reaps only after crossing the boundary — proves the interlock is threshold-driven, not indiscriminate.)

  ### AC5 — cold-start half (runbook §4.0/§4.1/§4.3)

  - [x] 1.10 **[MANUAL]** Pre-insert the `queued` `runs` row for a real invocation (runbook §4.0 / D1 / #100); capture the `id` into `/tmp/invoke-94.json` as `run_id`.
  - [x] 1.11 **[MANUAL]** Record the invoke timestamp with `date -u +"%Y-%m-%dT%H:%M:%S.%3NZ"`, then invoke with the bare-payload form `agentcore invoke --prompt-file /tmp/invoke-94.json` (runbook §4.1 / #97). Confirm `started_at` becomes non-null.
  - [x] 1.12 **[MANUAL]** Compute the TRUE cold-start gap = `started_at` − (the recorded `date -u` timestamp), NOT `started_at - queued_at`. Record both, labelled distinctly, against `grace_seconds=120`. **Observed ≈ 4.2 s** (`started_at 22:00:32.506` − `T_invoke 22:00:28.3`), well under grace 120.
  - [x] 1.13 **[MANUAL]** Cleanup: delete the run row if it was a throwaway measurement invocation.
  - [x] 1.14 **Verify Acceptance Criterion 3:** the true cold-start gap is measured and recorded against `grace_seconds=120`. **PASS** (≈4.2 s ≪ 120). (Edge: explicitly reject the invalid 185.7 s figure. Decision: dependency-update PRD open question 8 resolvable as "grace 120 s adequate".)

  ### AC6 — CloudWatch fallback when Supabase unreachable (runbook §5) — ⏳ DEFERRED (not executed this session)

  - [ ] 1.15 **[MANUAL]** Record the current correct `SUPABASE_URL` from `agents/dependency-update/agentcore/agentcore.json` (`runtimes[].envVars`), then point it at an unreachable host on the runtime config (runbook §5.1).
  - [ ] 1.16 **[MANUAL]** Pre-insert the `queued` row (§4.0), record the invoke timestamp, and invoke with the bare-payload `--prompt-file` form (§4.1).
  - [ ] 1.17 **[MANUAL]** Assert the agent **completes** (normal exit, no crash) — reporting failure must never kill the agent.
  - [ ] 1.18 **[MANUAL]** Assert payloads are dumped to stderr → CloudWatch after the SDK's 3 retries (`aws logs tail ... | grep -iE "supabase|retry|payload|report"`). Confirm 4xx-vs-transient behavior per EC-8 (only transient failures retried before the dump).
  - [ ] 1.19 **[MANUAL]** ⚠️ **Restore `SUPABASE_URL`** to the recorded value (§5.5) and confirm normal reporting resumes (`select status from runs where id=':new_id';` updates normally).
  - [ ] 1.20 **Verify Acceptance Criterion 4:** with Supabase unreachable the agent completes and payloads are recoverable from CloudWatch; `SUPABASE_URL` is restored and verified. (Negative path is the AC itself; the restore step is the guard against silently breaking later runs.)

  ### Transcription, matrices, and closeout

  - [~] 1.21 **[DEV]** Transcribe all recorded observations into the runbook results tables: §2 (AC4 `queued`-half), §4.2/§4.3/§4.4 (AC5), §5 (AC6), and flip the §Verification-status-summary AC5/AC6 rows and the AC4 note to PASS. **PARTIAL (2026-09-01):** §2.3 AC4-queued-half note + §4 AC5 results table flipped to PASS; §Verification-status-summary AC4→observed, AC5→PASS. **AC6/§5 remains PENDING** (Part D not executed).
  - [~] 1.22 **[DEV]** Update `workstream/traceability-matrix-issue-94.md`: fill AC4/AC5/AC6 Observed-result + Verdict columns; update the Coverage-status section and retain the "185.7 s invalid — do not cite" caution. **PARTIAL (2026-09-01):** AC4/AC5 → PASS with observed evidence; Coverage-status now **6 / 7 verified** (AC6 pending, NOT 7/7); caution retained. AC6 verdict left PENDING.
  - [x] 1.23 **[DEV]** Update `workstream/traceability-matrix-dep-update-agent.md` AC-36 to "fully exercised" (static + dynamic halves complete). **Done (2026-09-01)** — dynamic half verified via §4.4 synthetic proof + cold-start ≈ 4.2 s.
  - [ ] 1.24 **Verify Acceptance Criterion 5:** runbook and both traceability matrices reflect the final results (grep for remaining `⏳ PENDING` / `not executed` markers tied to #101 and confirm none remain). **PARTIAL** — AC1/AC2/AC3 evidence transcribed; AC6 markers intentionally remain until Part D runs.
  - [ ] 1.25 **[DEV]** Reconcile the #101 GitHub issue checklist with this task list (delegate to `github-ops`); post a brief results summary comment (via `--body-file`, per repo rule).
  - [ ] 1.26 **[MANUAL/DEV]** Verify Acceptance Criterion 6 & close: confirm all 7 #94 ACs are verified, then close issue #94 with a closing comment linking the evidence (delegate the close/comment to `github-ops`). **BLOCKED** — #94 at 6/7; AC6 (CloudWatch fallback) not yet verified. Closeout gate forbids closing. Not done.
  - [ ] 1.27 **[DEV]** Acceptance-criteria-to-evidence mapping check: confirm each of #101's 6 ACs maps to a recorded observation (SQL rows / CloudWatch lines / matrix rows) — AC1→1.1-1.4, AC2→1.5-1.9, AC3→1.10-1.14, AC4→1.15-1.20, AC5→1.21-1.24, AC6→1.26.

## Notes on quality gates

This issue produces **no application code** — it verifies live infrastructure and updates docs/matrices. The standard JS/TS quality gates (`lint`, `format:check`, `typecheck`, `test`, `audit`) do not apply to Markdown-only + live-observation changes. The applicable "gate" is: all runbook results tables filled, both matrices consistent, and #94 closed. **Current state (2026-09-01): #94 at 6/7 verified — AC6 (Supabase-unreachable CloudWatch fallback, Part D) deferred; #94 NOT closed.** If any doc edit touches a fenced code block, keep it faithful to the runbook's authored SQL/CLI (do not paraphrase procedures).
