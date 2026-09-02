# Implementation Plan - Issue #94: Schedule pg_cron Reaper & Verify Stale-Run Detection (Phase 1 Gap)

> Source issue: [#94](https://github.com/llipe/dev-tasks-agent-fleet/issues/94) — `fix(infra): schedule pg_cron reaper and verify stale-run detection (Phase 1 gap)`
> Labels: `bug`, `phase:infrastructure`, `priority:high`, `size:S`

## Execution Roles

Each sub-task is tagged with who executes it:

- **[DEV]** — developer agent, repo-side (code/docs edits, commits, PR sync). Autonomous.
- **[MANUAL]** — operator (you), live infrastructure. Requires Supabase dashboard / SQL Editor, AWS AgentCore, CloudWatch access the agent does not have.

The **[MANUAL]** steps were grouped into an operator runbook (Task 6 deliverable, now `docs/runbooks/issue-94-reaper-verification.md`). The developer agent authored that runbook, handed it to the operator, and transcribed the reported results back into the runbook, the traceability matrix, and the issue checklist — mirroring the #77 flow. Residual **[MANUAL]** steps (Tasks 4 and 5) are carried by [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101).

## Relevant Files

**Created:**

- `docs/runbooks/issue-94-reaper-verification.md` — operator runbook: scheduling, AC1–AC6 procedures with ready-to-paste SQL, results tables, verification status summary, follow-up table, troubleshooting index, known limitations. **[DEV] — DONE (6.1–6.3)**
- `docs/adr/ADR-004-schedule-pg-cron-reaper.md` — records the decision to activate the schedule in the schema reference, keep a dedicated runbook, and route surfaced defects to their own issues. Includes verified-behaviour evidence and consequences. **[DEV] — DONE**
- `workstream/test-plan-issue-94.md` — compliance test plan (verifier Design Mode). **[DEV] — DONE**
- `workstream/traceability-matrix-issue-94.md` — AC → test → observed-result → verdict mapping. **[DEV] — DONE**
- `workstream/fidelity-report-issue-94.md` — verifier Audit Mode report (Fidelity Medium, 7 drift findings). **[DEV] — DONE**

**Modified:**

- `docs/reference/001_schema.sql` — uncommented the `create extension if not exists pg_cron;` + `cron.schedule('reap-stale-runs', ...)` block at the tail (7-line change; no other schema edit). **[DEV] — DONE (1.1)**
- `docs/technical-guidelines.md` — §2/§3/§7/§14 refreshed from pending-intent to scheduled-and-verified; new §18 subsection registering #97–#101, the verified reaper properties, the accepted ~61-min stale window, and the invalid-185.7 s bar. Changelog → 1.5 (developer) then 1.6 (technical-writer). **[DEV] + technical-writer — DONE**
- `docs/runbooks/issue-77-deployment-e2e.md` — cross-links the reaper runbook; warning about the two invocation gotchas moved **ahead of §7.7** so a top-down reader hits it before the broken examples. **[DEV] + technical-writer — DONE**
- `TESTING.md` — Layer 2.5 gap analysis, ranked reaper/DB gap table, follow-up-issue testing consequences (incl. #101), coverage-baseline caveat. **[qa-engineer] + [DEV] — DONE**
- `workstream/traceability-matrix-dep-update-agent.md` — AC-36 row records the static half verified (#77) and the **partial** dynamic-half evidence (run `f63ac9f3-…` not reaped across ~61 min); full dynamic verification still pending. **[DEV] — DONE (4.4, partial)**
- `workstream/pending-manual-config-dependency-update-agent.md` — step 5 struck through and marked superseded by #94 (schedule now ships inside `001_schema.sql`); §4 table row corrected `#77` → `#94`. **[technical-writer] — DONE**
- `agents/dependency-update/README.md` — §Invocation gained a ⚠️ block: the pre-wrapped form is broken on CLI ≥0.28.0, with the working `--prompt-file` recipe and the #100 pre-insert requirement. **[technical-writer] — DONE**
- `README.md` — documentation map gained `docs/adr/` and `docs/runbooks/` rows. **[technical-writer] — DONE**
- `.gitignore` — ignores operator scratch `invoke-*.json` payloads. **[DEV] — DONE**

**Not modified (deliberately):** no application code. No Python, TypeScript, or panel/UI file was touched — confirmed by the verifier audit (full diff = 1 SQL comment removal + docs + workstream artifacts).

## Outcome Summary (final state)

**Status:** 5 of 7 acceptance criteria verified. Shipped as PR [#96](https://github.com/llipe/dev-tasks-agent-fleet/pull/96) (ready for review, base `main`, branch `issue/94-schedule-pg-cron-reaper`, 5 commits `9036501`→`72ea8c3`).

| Issue AC | Description | Verdict |
|---|---|---|
| AC1 | `reap-stale-runs` scheduled `* * * * *` and firing | ✅ PASS |
| AC2 | `queued` past threshold → `failed_to_start` + event | ✅ PASS |
| AC3 | `running` past threshold → `timed_out` + event | ✅ PASS (**real hung run**, not only synthetic) |
| AC4 | `v_runs.effective_status` leads the reaper | ⚠️ PASS (partial) — `running` half observed; `queued` half by inspection only |
| AC5 | Healthy long run not reaped + cold-start gap | ⏳ PENDING → [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101) |
| AC6 | Supabase unreachable → agent completes, CloudWatch recoverable | ⏳ PENDING → [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101) |
| AC7 | Scheduling + results documented | ✅ PASS |

**Headline evidence (AC3).** Real run `f63ac9f3-14b0-4157-9484-f2f6b062f846` hung during its `validate` step and never reported terminal status. The reaper caught it at `elapsed 3732.30 s` against the `3720 s` threshold (`max_runtime 3600 + grace 120`) — **12.3 s late, inside one cron tick, never early** — set `error_code=RUNTIME_TIMEOUT`, and wrote the explanatory event at `seq=10` after the agent's `seq` 1–9 with no `uq_run_events_seq` collision. It also sat untouched for the full ~61 minutes beforehand.

**Quality gates** (`agents/dependency-update/app/dependencyUpdate`, `make validate`): ✅ PASS — 362 tests, 94% coverage, `pip-audit --strict` clean. No application code was modified by this issue.

**Completion gates:** `coverage_gate: PASS` (qa-engineer, scoped to the Python package). verifier audit: **Fidelity Medium**, highest drift **Major**, summary posted to PR #96 + issue #94, artifact at `workstream/fidelity-report-issue-94.md`. technical-writer: **`drift-fixed`**.

**Issue closure:** PR #96 uses **`Refs #94`**, not `Closes #94` — verified via GraphQL that `closingIssuesReferences` is empty, so merging will **not** auto-close #94 with two ACs unverified. Issue #94 stays open until [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101) lands.

**Five follow-up issues raised** (all out of scope for #94 — the reaper behaved correctly in every observed case):

| Issue | Type | Summary |
|---|---|---|
| [#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97) | defect | `unwrap_payload` strips one `prompt` wrapper, but `agentcore` CLI ≥0.28.0 wraps the argument itself → documented examples double-wrap and die with `INVALID_PARAMS` |
| [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98) | defect | Run dies during `validate` without reporting terminal status. Blocks **only** AC5's "20+ minute run" clause |
| [#99](https://github.com/llipe/dev-tasks-agent-fleet/issues/99) | defect | `reap_stale_runs()` leaves open `run_steps` pinned `running` inside a terminal run |
| [#100](https://github.com/llipe/dev-tasks-agent-fleet/issues/100) | docs | Control plane must insert the `queued` runs row before invoking (D1); agent only PATCHes |
| [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101) | verification | Carries the residual AC4-`queued`-half, AC5, and AC6 checks |

**⚠️ Invalid measurement — do not cite.** A cold-start figure of `185.7 s` was recorded during an AC5 attempt. It is **invalid**: it includes human delay between the manual row `INSERT` and the `agentcore invoke`. The agent's first log (`19:34:47.530`) and `started_at` (`19:34:47.710`) are 180 ms apart, so the app reported start essentially instantly. It must not be cited as a cold-start measurement or used to justify a `grace_seconds` change. dependency-update PRD open question 8 remains **open**.

**Correction to the original blocker attribution.** The task list initially parked all of AC5 behind #98. The verifier audit found that over-broad: only the "real 20+ minute `llm_fix` run" framing depends on #98. The synthetic interlock proof (runbook §4.4) uses real thresholds and depends on nothing, and the cold-start measurement needs *a* real invocation, not a *long* one. #101 splits AC5 accordingly.

---

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
  - [x] 1.4 **[MANUAL]** Verify issue AC1 — job registered: `select * from cron.job;` shows `reap-stale-runs` scheduled at `* * * * *`.
  - [x] 1.5 **[MANUAL]** Verify issue AC1 — job firing: `select * from cron.job_run_details order by start_time desc limit 5;` shows recent successful executions.
  - [x] 1.6 **[DEV]** Record the AC1 result in the runbook results table — done, §1. Verbatim query output was not retained; recorded as operator attestation with that caveat stated explicitly.

- [x] 2.0 Verify **issue AC2** — `failed_to_start` (parent PRD AC4, D9)

  > Note: `start_timeout_seconds` is snapshotted per run (D8). Insert a `queued` row with a **backdated** `queued_at` so it is already past its `start_timeout_seconds` — this avoids waiting the full threshold; you only wait for the next cron tick.
  > Executed insert (backdated form): `queued_at = now() - interval '90 seconds'`, `start_timeout_seconds = 60`, resolving `agent_id`/`repository_id` from the seed (agent `dependency-update`, repo `llipe/memo-cli`).

  - [x] 2.1 **[DEV]** Provide the exact insert SQL in the runbook: a `runs` row with `status='queued'`, backdated `queued_at` (`now() - interval '90 seconds'`), `start_timeout_seconds=60`, `agent_id`/`repository_id` resolved from the seed, and all NOT-NULL snapshot columns populated (`agent_version`, `max_runtime_seconds`, `grace_seconds`, `id` via `gen_random_uuid()`).
  - [x] 2.2 **[MANUAL]** Run the insert against the live DB.
  - [x] 2.3 **[MANUAL]** Wait for one cron tick (up to ~60s — job runs at the top of each minute; the row is already past threshold).
  - [x] 2.4 **[MANUAL]** Verify issue AC2 — assert `status='failed_to_start'`: `select status, error_code, error_message from runs where id = '<uuid>';`
  - [x] 2.5 **[MANUAL]** Verify issue AC2 — assert an explanatory `run_events` row exists: `select seq, level, message, data->>'reaped_by' as reaped_by, data->>'reason' as reason from run_events where run_id = '<uuid>' order by seq;` (expect `reaped_by='reap_stale_runs'`, `reason='START_TIMEOUT'` — this event has no other source).
  - [x] 2.6 **[DEV]** Record the AC2 result in the runbook — done, `issue-94-reaper-verification.md` §2 results table.

- [x] 3.0 Verify **issue AC3 + AC4** — `timed_out` + two-layer contract (parent PRD AC5, D8; technical-guidelines §3; PRD FR11a)

  > Note: Same synthetic-row trick with backdated timestamps. `started_at = now() - interval '75 seconds'` with `max_runtime_seconds=60`, `grace_seconds=10` (threshold 70s) makes the row eligible immediately; you only wait one cron tick. The two-layer check (3.3) is time-sensitive — read `v_runs` before the next tick materializes the change.

  - [x] 3.1 **[DEV]** Provide the exact insert SQL in the runbook: a `runs` row with `status='running'`, backdated `started_at` (`now() - interval '75 seconds'`), `max_runtime_seconds=60`, `grace_seconds=10`, plus all other NOT-NULL columns (`agent_id`/`repository_id` from the seed).
  - [x] 3.2 **[MANUAL]** Run the insert against the live DB.
  - [x] 3.3 **[MANUAL]** Verify issue AC4 (two-layer, read-time) — ⚠️ `running` half only; the `queued` half is carried by #101 — **before** the reaper fires, confirm `v_runs.effective_status` already reports `timed_out`: `select status, effective_status from v_runs where id = '<uuid>';` (expect `status='running'`, `effective_status='timed_out'`). If the tick already fired, use `select cron.unschedule('reap-stale-runs');` → insert → check `v_runs` → re-schedule to observe the split reliably.
  - [x] 3.4 **[MANUAL]** Wait for one cron tick (row already past the 70s threshold).
  - [x] 3.5 **[MANUAL]** Verify issue AC3 — assert `status='timed_out'`: `select status, error_code, error_message from runs where id = '<uuid>';`
  - [x] 3.6 **[MANUAL]** Verify issue AC3 — assert the explanatory `run_events` row exists (`reason='RUNTIME_TIMEOUT'`, `reaped_by='reap_stale_runs'`).
  - [x] 3.7 **[DEV]** Record the AC3 + two-layer (AC4) results in the runbook — done, §3 results table plus a dedicated real-run block for `f63ac9f3-…`, noting `effective_status` agreed with `timed_out` before materialization.

- [ ] 4.0 ⏳ **PENDING → [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101)** · Verify **issue AC5** / dep-update AC-36 dynamic half — reaper interlock (§12.4, open question 8)

  > Note: Task 7.13 (issue #77) already confirmed the static half — `agents.max_runtime_seconds` (3600) equals `maxLifetime` in `agentcore.json` (3600). This task exercises the dynamic half, never run before.
  >
  > **⚠️ Gotcha 1 — `v_runs` not updating after `agentcore invoke` is EXPECTED, not a bug** (diagnosed 2026-08-31, now tracked as [#100](https://github.com/llipe/dev-tasks-agent-fleet/issues/100)).
  > Per **D1** and specification §14, the **front-end inserts the `queued` `runs` row** (`{run_id, status:'queued'}`) *before* invoking AgentCore. The agent SDK only **updates** that pre-existing row — `agent_reporter.py::RunReporter.start()` calls `_db.update("runs", "id=eq.<run_id>", {status:'running', started_at:...})`, never an insert. When you call `agentcore invoke` directly (the Next.js panel is Phase 2 and does not exist yet), **no row is inserted**, so the agent's PATCH matches zero rows (PostgREST returns HTTP 200 on a zero-match UPDATE — silent no-op) and nothing ever appears in `runs`/`v_runs`. This upholds the same "explicitness over inference" contract: the run's existence is asserted by the control plane, not reconstructed from the invoke.
  >
  > **⚠️ Gotcha 2 — the pre-wrapped `{"prompt": "..."}` invoke form is BROKEN on `agentcore` CLI ≥0.28.0** (tracked as [#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97)).
  > `agentcore invoke [prompt]` treats its argument **as** the prompt and wraps it itself. `unwrap_payload()` strips exactly **one** level, so an already-wrapped payload arrives double-wrapped; one unwrap leaves `{"prompt": "{...}"}`, whose only key is `prompt`, and validation dies with `INVALID_PARAMS` / `"Invalid payload — missing required fields"`. **Pass the bare inner JSON via `--prompt-file`.**
  >
  > **Working procedure (both gotchas handled):**
  > ```sql
  > -- 1. Insert the queued row first, with REAL snapshot timeouts so the reaper leaves a healthy run alone
  > insert into runs (id, agent_id, agent_version, repository_id, installation_id,
  >                   status, queued_at, max_runtime_seconds, grace_seconds, start_timeout_seconds)
  > select gen_random_uuid(), a.id, a.version, r.id, r.installation_id,
  >        'queued', now(), 3600, 120, 300
  > from agents a join repositories r on r.full_name = 'llipe/tf-ecommerce-mgmt'
  > where a.slug = 'dependency-update'
  > returning id;   -- capture this UUID
  > ```
  > ```bash
  > # 2. Write /tmp/invoke-94.json containing ONLY the inner payload (no "prompt" key):
  > #    {"run_id":"<UUID>","repository_org":"llipe","repository_name":"tf-ecommerce-mgmt",
  > #     "params":{"fix_mode":"llm_fix","max_fix_attempts":3}}
  > #    NOTE: repository_name is the repo name only, never org/repo.
  > cd agents/dependency-update
  > date -u +"%Y-%m-%dT%H:%M:%S.%3NZ"   # record — required for a VALID cold-start measurement (4.3)
  > agentcore invoke --prompt-file /tmp/invoke-94.json
  > ```
  > The agent's `start()` will then find the row, flip it to `running`, and `v_runs` will update.
  >
  > **⚠️ Blocker scope.** [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98) (agent dies mid-`validate`) blocks **only** 4.1/4.2's "run that legitimately takes 20+ minutes" framing. It does **not** block: (a) the interlock proof — runbook §4.4 uses real thresholds on a synthetic row and needs no invocation at all; or (b) 4.3's cold-start measurement, which needs *a* real invocation, not a *long* one. Do not park all of AC5 behind #98.

  - [ ] 4.1 **[MANUAL]** Insert the `queued` row (workaround above) simulating the front-end, then trigger a real `llm_fix` run with the same `run_id` that legitimately takes 20+ minutes on a repo with available updates (per runbook #77 sub-task 7.8 invocation shape).
  - [ ] 4.2 **[MANUAL]** Verify issue AC5 — confirm the healthy run is **not** reaped early: it reaches a normal terminal `status` (`succeeded`/`failed`), never `timed_out`, despite exceeding 20 minutes (well under the 3600+120 threshold). Also confirm no `run_events` row has `reaped_by='reap_stale_runs'` for this run.
        **Unblocked alternative (recommended):** run the **synthetic interlock proof** in runbook §4.4 instead — insert a `running` row with real thresholds (3600/120) and `started_at` backdated ~30 min, confirm it stays `running` with zero reaper events across several ticks, then backdate past 3720 s and confirm it reaps. Same predicate, ~10 min, no dependency on #98.
  - [ ] 4.3 **[MANUAL]** Measure the **true** cold-start gap. Record the invoke moment (`date -u +"%Y-%m-%dT%H:%M:%S.%3NZ"` immediately before `agentcore invoke`), then compute `started_at` **minus that timestamp**. Do **not** use `extract(epoch from (started_at - queued_at))` when the row was inserted by hand — that includes human delay and produced the invalid 185.7 s figure. Record against `grace_seconds=120`; this closes dependency-update PRD open question 8. Needs only *a* completing run, not a long one.
  - [x] 4.4 **[DEV]** (partial evidence recorded; full dynamic half still pending) Record the AC-36 dynamic-half result + observed cold-start gap in the runbook, note the front-end-row-insert prerequisite (D1) discovered here, and update `workstream/traceability-matrix-dep-update-agent.md` to reflect the dynamic half is now exercised.

- [ ] 5.0 ⏳ **PENDING → [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101)** · Verify **issue AC6** — CloudWatch fallback (parent PRD AC3; §8, R5; technical-guidelines §3/§14)

  > Note: Reporting must never kill the agent. When PostgREST is unreachable, the SDK dumps payloads to stderr → CloudWatch after 3 retries.

  - [ ] 5.1 **[MANUAL]** Point `SUPABASE_URL` at an unreachable host on the runtime config (or otherwise break PostgREST reachability). Record the exact change made so it can be reverted.
  - [ ] 5.2 **[MANUAL]** Invoke the agent (any valid payload).
  - [ ] 5.3 **[MANUAL]** Verify issue AC6 — assert the agent **completes** rather than crashing (the run process exits normally; reporting failure does not propagate).
  - [ ] 5.4 **[MANUAL]** Verify issue AC6 — assert the failed payloads appear in CloudWatch via stderr after the SDK's 3 retries (search the runtime log group for the dumped payload lines).
  - [ ] 5.5 **[MANUAL]** ⚠️ Restore `SUPABASE_URL` to the correct value and confirm normal reporting resumes.
  - [ ] 5.6 **[DEV]** Record the AC6 result in the runbook, including the exact break/restore steps used. → [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101)

- [x] 6.0 Documentation (Acceptance Criterion 7)

  - [x] 6.1 **[DEV]** DECIDED: separate runbook `docs/runbooks/issue-94-reaper-verification.md` (content too substantial for the #77 runbook; #77 cross-links to it). Original wording: add a "Reaper scheduling & stale-run verification" section to `docs/runbooks/issue-77-deployment-e2e.md`, OR create `docs/runbooks/issue-94-reaper-verification.md`. Prefer co-locating with the deployment runbook unless it becomes unwieldy; record the decision either way (the scheduling step currently lives only in the superseded `workstream/pending-manual-config-dependency-update-agent.md` step 5 and the dependency-update PRD table).
  - [x] 6.2 **[DEV]** Write the operator runbook content: prerequisites (schema applied, seed applied, agent deployed), the exact enable-extension + `cron.schedule` commands, the `cron.job` / `cron.job_run_details` verification queries, and the ready-to-paste synthetic-row inserts for Tasks 2 and 3 with all NOT-NULL columns filled.
  - [x] 6.3 **[DEV]** Add results-recording tables/checkboxes for AC3/AC4/AC5/AC-36 in the same style as #77 sub-tasks 7.7/7.8/7.10 (per-check pass/fail + observed `status`/`outcome`/event), for the operator to fill during Tasks 1–5.
  - [x] 6.4 **[DEV]** (AC1–AC4 + AC7 transcribed; AC5/AC6 recorded as PENDING) After the operator reports Task 1–5 results, transcribe them into the runbook results tables and the GitHub issue checklist.

- [x] 7.0 Acceptance-criteria-to-verification mapping & wrap-up

  - [x] 7.1 **[DEV]** Confirm every issue AC maps to a verification step, with final verdicts:
    - AC1 (job scheduled + firing) → 1.4, 1.5 — ✅ **PASS** (operator attestation; verbatim output not retained, corroborated indirectly since AC2/AC3 could only materialize with the job firing)
    - AC2 (`failed_to_start` + event) → 2.4, 2.5 — ✅ **PASS** (synthetic row, plus an unplanned orphan confirmation on run `cba355cb-…` reaped at 324 s vs 300 s)
    - AC3 (`timed_out` + event) → 3.5, 3.6 — ✅ **PASS** (synthetic **and** real hung run `f63ac9f3-…` at 3732.30 s vs 3720 s, event at `seq=10`)
    - AC4 (`v_runs.effective_status` before reaper) → 3.3 — ⚠️ **PASS (partial)**: the `running`→`timed_out` half was observed; the `queued`→`failed_to_start` half of the same `case` expression was verified by **inspection only**, never observed. Runbook §2 contains no `v_runs` query. Residual check (~2 min) carried by [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101)
    - AC5 (healthy `llm_fix` not reaped + cold-start gap) → 4.2, 4.3 — ⏳ **PENDING** → [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101). Partial evidence exists: run `f63ac9f3-…` sat `running` ~61 min with zero reaper events until its legitimate boundary
    - AC6 (Supabase unreachable → agent completes, CloudWatch recoverable) → 5.3, 5.4 — ⏳ **PENDING** → [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101). Not executed; no blocker claimed or apparent
    - AC7 (scheduling + results documented) → Task 6 — ✅ **PASS**
  - [x] 7.2 **[DEV]** Confirm out-of-scope items were not touched: no heartbeat detection, no run cancellation, no `run_events` retention, no panel work. **Verified by the verifier audit** — full diff is a 7-line SQL comment removal + docs + workstream artifacts; `heartbeat`/`cancel`/`retention` appear only in explanatory prose (`last_heartbeat_at` named as the future lever for tightening the stale window), never as new behaviour.
  - [x] 7.3 **[DEV]** Sync the GitHub issue #94 checklist to final state and post a completion summary comment (via `github-ops`, `--body-file`). Issue Scope + Execution Task List checkboxes synced; verifier audit summary posted to both PR #96 and issue #94.
