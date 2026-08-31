# Implementation Plan - Issue #94: Schedule pg_cron Reaper & Verify Stale-Run Detection (Phase 1 Gap)

> Source issue: [#94](https://github.com/llipe/dev-tasks-agent-fleet/issues/94) — `fix(infra): schedule pg_cron reaper and verify stale-run detection (Phase 1 gap)`
> Labels: `bug`, `phase:infrastructure`, `priority:high`, `size:S`

## Execution Roles

Each sub-task is tagged with who executes it:

- **[DEV]** — developer agent, repo-side (code/docs edits, commits, PR sync). Autonomous.
- **[MANUAL]** — operator (you), live infrastructure. Requires Supabase dashboard / SQL Editor, AWS AgentCore, CloudWatch access the agent does not have.

The **[MANUAL]** steps are grouped into an operator runbook (Task 6 deliverable). The developer agent authors that runbook, hands it to you, then records your reported results back into the runbook and the issue checklist — mirroring the #77 flow.

## Relevant Files

- `docs/reference/001_schema.sql` - Contains `reap_stale_runs()`, the `v_runs` view with `effective_status`, and the `cron.schedule` block (now uncommented). **[DEV] — DONE (1.1)**
- `docs/runbooks/issue-94-reaper-verification.md` - **NEW** operator runbook: reaper scheduling, AC1–AC6 verification steps with ready-to-paste SQL, results tables, troubleshooting index, and known limitations. **[DEV] — DONE (6.1–6.3)**
- `docs/runbooks/issue-77-deployment-e2e.md` - Cross-links to the new reaper runbook and flags the two invocation gotchas (no-row-on-direct-invoke; CLI ≥0.28.0 double-wrap) affecting its §7.7–7.10 steps. **[DEV] — DONE**
- `workstream/pending-manual-config-dependency-update-agent.md` - Superseded location of the scheduling command (step 5); referenced, not the target of new work. **[DEV] (reference only)**
- `workstream/traceability-matrix-dep-update-agent.md` - AC-36 marked `E2E (manual, long-running)`; update the dynamic-half status after the interlock check. **[DEV] — pending (4.4)**
- `workstream/test-plan-issue-94.md` - Compliance test plan (verifier Design Mode). **[DEV] — DONE**
- `workstream/traceability-matrix-issue-94.md` - AC → test → result mapping. **[DEV] — DONE**

## Notes

- **No application code changes.** This issue is infrastructure scheduling + verification + documentation. The only repo edits are SQL uncomment and Markdown.
- **No branch push to `main`, no `--body` inline for issue/PR ops** (repo git-guard invariants).
- **Migration note:** Task 1 enables a Postgres extension (`pg_cron`) and registers a cron job on the **production** Supabase database. This is a live-DB change and carries a confirmation gate (sub-task 1.2). It is operator-executed.
- The seeded `dependency-update` agent has `max_runtime_seconds=3600`, `grace_seconds=120`, `start_timeout_seconds=300`. Because these are **snapshotted per run** (D8), verification uses synthetic run rows with small thresholds instead of waiting out the real 62-minute window.

## Tasks

- [x] 1.0 Schedule the reaper (PRD FR3, D10)

  > Note: `reap_stale_runs()` and the commented `cron.schedule` block already exist in `001_schema.sql`. This task activates them in the live Supabase project and reconciles the repo file with the deployed state.

  - [x] 1.1 **[DEV]** Uncomment the scheduling block at the tail of `docs/reference/001_schema.sql` (lines 323–325: `create extension if not exists pg_cron;` and the `cron.schedule('reap-stale-runs', ...)` call). Keep the explanatory comment about enabling the extension in the dashboard.
  - [x] 1.2 **[MANUAL]** ⚠️ live-DB change — confirmation gate. Enable the `pg_cron` extension in the Supabase project: Database → Extensions → enable `pg_cron` (or run `create extension if not exists pg_cron;` in the SQL Editor). Confirm before running — this modifies the production database.
  - [x] 1.3 **[MANUAL]** Schedule the job in the SQL Editor: `select cron.schedule('reap-stale-runs', '* * * * *', $$select reap_stale_runs()$$);`
  - [x] 1.4 **[MANUAL]** Verify Acceptance Criterion 1 — job registered: `select * from cron.job;` shows `reap-stale-runs` scheduled at `* * * * *`.
  - [x] 1.5 **[MANUAL]** Verify Acceptance Criterion 1 — job firing: `select * from cron.job_run_details order by start_time desc limit 5;` shows recent successful executions.
  - [ ] 1.6 **[DEV]** Record the AC1 result (job schedule + recent run details output) in the runbook results table.

- [ ] 2.0 Verify AC4 — `failed_to_start` (parent PRD AC4, D9)

  > Note: `start_timeout_seconds` is snapshotted per run (D8). Insert a `queued` row with a **backdated** `queued_at` so it is already past its `start_timeout_seconds` — this avoids waiting the full threshold; you only wait for the next cron tick.
  > Executed insert (backdated form): `queued_at = now() - interval '90 seconds'`, `start_timeout_seconds = 60`, resolving `agent_id`/`repository_id` from the seed (agent `dependency-update`, repo `llipe/memo-cli`).

  - [x] 2.1 **[DEV]** Provide the exact insert SQL in the runbook: a `runs` row with `status='queued'`, backdated `queued_at` (`now() - interval '90 seconds'`), `start_timeout_seconds=60`, `agent_id`/`repository_id` resolved from the seed, and all NOT-NULL snapshot columns populated (`agent_version`, `max_runtime_seconds`, `grace_seconds`, `id` via `gen_random_uuid()`).
  - [x] 2.2 **[MANUAL]** Run the insert against the live DB.
  - [x] 2.3 **[MANUAL]** Wait for one cron tick (up to ~60s — job runs at the top of each minute; the row is already past threshold).
  - [x] 2.4 **[MANUAL]** Verify Acceptance Criterion 2 — assert `status='failed_to_start'`: `select status, error_code, error_message from runs where id = '<uuid>';`
  - [x] 2.5 **[MANUAL]** Verify Acceptance Criterion 2 — assert an explanatory `run_events` row exists: `select seq, level, message, data->>'reaped_by' as reaped_by, data->>'reason' as reason from run_events where run_id = '<uuid>' order by seq;` (expect `reaped_by='reap_stale_runs'`, `reason='START_TIMEOUT'` — this event has no other source).
  - [ ] 2.6 **[DEV]** Record the AC4 result in the runbook.

- [ ] 3.0 Verify AC5 — `timed_out` + two-layer contract (parent PRD AC5, D8; technical-guidelines §3; PRD FR11a)

  > Note: Same synthetic-row trick with backdated timestamps. `started_at = now() - interval '75 seconds'` with `max_runtime_seconds=60`, `grace_seconds=10` (threshold 70s) makes the row eligible immediately; you only wait one cron tick. The two-layer check (3.3) is time-sensitive — read `v_runs` before the next tick materializes the change.

  - [x] 3.1 **[DEV]** Provide the exact insert SQL in the runbook: a `runs` row with `status='running'`, backdated `started_at` (`now() - interval '75 seconds'`), `max_runtime_seconds=60`, `grace_seconds=10`, plus all other NOT-NULL columns (`agent_id`/`repository_id` from the seed).
  - [x] 3.2 **[MANUAL]** Run the insert against the live DB.
  - [x] 3.3 **[MANUAL]** Verify Acceptance Criterion 4 (two-layer, read-time) — **before** the reaper fires, confirm `v_runs.effective_status` already reports `timed_out`: `select status, effective_status from v_runs where id = '<uuid>';` (expect `status='running'`, `effective_status='timed_out'`). If the tick already fired, use `select cron.unschedule('reap-stale-runs');` → insert → check `v_runs` → re-schedule to observe the split reliably.
  - [x] 3.4 **[MANUAL]** Wait for one cron tick (row already past the 70s threshold).
  - [x] 3.5 **[MANUAL]** Verify Acceptance Criterion 3 — assert `status='timed_out'`: `select status, error_code, error_message from runs where id = '<uuid>';`
  - [x] 3.6 **[MANUAL]** Verify Acceptance Criterion 3 — assert the explanatory `run_events` row exists (`reason='RUNTIME_TIMEOUT'`, `reaped_by='reap_stale_runs'`).
  - [ ] 3.7 **[DEV]** Record the AC5 + two-layer (AC4) results in the runbook, noting explicitly that `effective_status` agreed with `timed_out` before materialization.

- [ ] 4.0 Verify AC-36 dynamic half — reaper interlock (dependency-update PRD AC-36, §12.4, open question 8)

  > Note: Task 7.13 (issue #77) already confirmed the static half — `agents.max_runtime_seconds` (3600) equals `maxLifetime` in `agentcore.json` (3600). This task exercises the dynamic half, never run before.
  >
  > **⚠️ Known interaction — `v_runs` not updating after `agentcore invoke` is EXPECTED, not a bug (diagnosed 2026-08-27).**
  > Per **D1** and specification §14, the **front-end inserts the `queued` `runs` row** (`{run_id, status:'queued'}`) *before* invoking AgentCore. The agent SDK only **updates** that pre-existing row — `agent_reporter.py::RunReporter.start()` calls `_db.update("runs", "id=eq.<run_id>", {status:'running', started_at:...})`, never an insert. When you call `agentcore invoke` directly (the Next.js panel is Phase 2 and does not exist yet), **no row is inserted**, so the agent's PATCH matches zero rows (PostgREST returns HTTP 200 on a zero-match UPDATE — silent no-op) and nothing ever appears in `runs`/`v_runs`. This is the same "explicitness over inference" contract: the run's existence is asserted by the front-end, not reconstructed from the invoke.
  >
  > **Workaround to still verify AC5/AC-36 without the front-end:** manually insert the `queued` row first (simulating what the panel would do), *then* invoke with the same `run_id`. Insert with the real snapshot timeouts (3600/120/300) so the reaper does not touch a healthy run:
  > ```sql
  > insert into runs (id, agent_id, agent_version, repository_id, installation_id,
  >                   status, queued_at, max_runtime_seconds, grace_seconds, start_timeout_seconds)
  > select '<uuid>', a.id, a.version, r.id, r.installation_id,
  >        'queued', now(), 3600, 120, 300
  > from agents a join repositories r on r.full_name = 'llipe/tf-ecommerce-mgmt'
  > where a.slug = 'dependency-update';
  > ```
  > Then `agentcore invoke '{"prompt":"{\"run_id\":\"<uuid>\", ...}"}'`. The agent's `start()` will now find and flip the row to `running`, and `v_runs` will update.

  - [ ] 4.1 **[MANUAL]** Insert the `queued` row (workaround above) simulating the front-end, then trigger a real `llm_fix` run with the same `run_id` that legitimately takes 20+ minutes on a repo with available updates (per runbook #77 sub-task 7.8 invocation shape).
  - [ ] 4.2 **[MANUAL]** Verify Acceptance Criterion 5 — confirm the healthy run is **not** reaped early: it reaches a normal terminal `status` (`succeeded`/`failed`), never `timed_out`, despite exceeding 20 minutes (well under the 3600+120 threshold). Also confirm no `run_events` row has `reaped_by='reap_stale_runs'` for this run.
  - [ ] 4.3 **[MANUAL]** Measure the actual gap between AgentCore's clock and the agent's `started_at` on the real run (container cold start + image pull): `select queued_at, started_at, extract(epoch from (started_at - queued_at)) as start_gap_seconds from runs where id = '<uuid>';`. Record whether `grace_seconds=120` comfortably covers it — this is dependency-update PRD open question 8; underestimating it means the reaper kills healthy runs.
  - [ ] 4.4 **[DEV]** Record the AC-36 dynamic-half result + observed cold-start gap in the runbook, note the front-end-row-insert prerequisite (D1) discovered here, and update `workstream/traceability-matrix-dep-update-agent.md` to reflect the dynamic half is now exercised.

- [ ] 5.0 Verify AC3 — CloudWatch fallback (parent PRD AC3; §8, R5; technical-guidelines §3/§14)

  > Note: Reporting must never kill the agent. When PostgREST is unreachable, the SDK dumps payloads to stderr → CloudWatch after 3 retries.

  - [ ] 5.1 **[MANUAL]** Point `SUPABASE_URL` at an unreachable host on the runtime config (or otherwise break PostgREST reachability). Record the exact change made so it can be reverted.
  - [ ] 5.2 **[MANUAL]** Invoke the agent (any valid payload).
  - [ ] 5.3 **[MANUAL]** Verify Acceptance Criterion 6 — assert the agent **completes** rather than crashing (the run process exits normally; reporting failure does not propagate).
  - [ ] 5.4 **[MANUAL]** Verify Acceptance Criterion 6 — assert the failed payloads appear in CloudWatch via stderr after the SDK's 3 retries (search the runtime log group for the dumped payload lines).
  - [ ] 5.5 **[MANUAL]** ⚠️ Restore `SUPABASE_URL` to the correct value and confirm normal reporting resumes.
  - [ ] 5.6 **[DEV]** Record the AC3 result in the runbook, including the exact break/restore steps used.

- [ ] 6.0 Documentation (Acceptance Criterion 7)

  - [x] 6.1 **[DEV]** DECIDED: separate runbook `docs/runbooks/issue-94-reaper-verification.md` (content too substantial for the #77 runbook; #77 cross-links to it). Original wording: add a "Reaper scheduling & stale-run verification" section to `docs/runbooks/issue-77-deployment-e2e.md`, OR create `docs/runbooks/issue-94-reaper-verification.md`. Prefer co-locating with the deployment runbook unless it becomes unwieldy; record the decision either way (the scheduling step currently lives only in the superseded `workstream/pending-manual-config-dependency-update-agent.md` step 5 and the dependency-update PRD table).
  - [x] 6.2 **[DEV]** Write the operator runbook content: prerequisites (schema applied, seed applied, agent deployed), the exact enable-extension + `cron.schedule` commands, the `cron.job` / `cron.job_run_details` verification queries, and the ready-to-paste synthetic-row inserts for Tasks 2 and 3 with all NOT-NULL columns filled.
  - [x] 6.3 **[DEV]** Add results-recording tables/checkboxes for AC3/AC4/AC5/AC-36 in the same style as #77 sub-tasks 7.7/7.8/7.10 (per-check pass/fail + observed `status`/`outcome`/event), for the operator to fill during Tasks 1–5.
  - [ ] 6.4 **[DEV]** After the operator reports Task 1–5 results, transcribe them into the runbook results tables and the GitHub issue checklist.

- [ ] 7.0 Acceptance-criteria-to-verification mapping & wrap-up

  - [ ] 7.1 **[DEV]** Confirm every issue AC maps to a completed verification step:
    - AC1 (job scheduled + firing) → 1.4, 1.5
    - AC2 (`failed_to_start` + event) → 2.4, 2.5
    - AC3 (`timed_out` + event) → 3.5, 3.6
    - AC4 (`v_runs.effective_status` before reaper) → 3.3
    - AC5 (healthy `llm_fix` not reaped + cold-start gap) → 4.2, 4.3
    - AC6 (Supabase unreachable → agent completes, CloudWatch recoverable) → 5.3, 5.4
    - AC7 (scheduling + results documented) → Task 6
  - [ ] 7.2 **[DEV]** Confirm out-of-scope items were not touched: no heartbeat detection, no run cancellation, no `run_events` retention, no panel work.
  - [ ] 7.3 **[DEV]** Sync the GitHub issue #94 checklist to final state and post a completion summary comment (via `github-ops`, `--body-file`).
