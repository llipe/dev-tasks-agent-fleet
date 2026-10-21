# Task List — Agent Scheduler (Phase 4)

> Execution plan for [`prd-agent-scheduler`](../docs/requirements/prd-agent-scheduler.md) /
> [`specification-prd-agent-scheduler`](../specification-prd-agent-scheduler.md) /
> [`user-stories-prd-agent-scheduler`](user-stories-prd-agent-scheduler.md).
> GitHub issues **#261–#276** (S-149…S-164), milestone `v3.0 — Phase 4 Agent Scheduler`.
>
> **Ordering is dependency-correct**, grouped by wave. Each story is a branch →
> reviewed PR into an integration branch, with the integration branch merged to `main`
> via a single reviewed PR at the end (human review is the gate; no agent self-merges to
> `main`). **Test-first:** within each story, author the stated test layers before the
> implementation task. `make validate` must pass before any PR is marked ready;
> `verifier` audit is mandatory pre-PR.

## Changelog

| Version | Date       | Summary                               | Author           |
| ------- | ---------- | ------------------------------------- | ---------------- |
| 1.0     | 2026-10-13 | Initial task list from stories v1.0.  | product-engineer |

## Conventions

- **Branches:** `story/S-149-schedules-schema`, etc. Integration branch:
  `integration/agent-scheduler`.
- **Commits:** Conventional Commits (`feat(scheduler): …`, `test(scheduler): …`,
  `feat(panel): …`, `docs: …`).
- **Layers** (`TESTING.md`): L1 unit, L2 component, L2.5 integration (live local Supabase,
  `REQUIRE_LOCAL_DB=1`), E2E (Playwright). `[T]` marks a test-first task that MUST precede
  its implementation `[I]`.
- **DoD per story:** tests authored first and passing · `make validate` green (both
  branches) · `coverage_gate` recorded · `verifier` audit (High fidelity, drift routed) ·
  DESIGN.md pixel match for UI stories · PR opened against `integration/agent-scheduler`
  with a body summarizing changes/tests/blocked items.
- **Open decision:** OQ-S2 (advanced cron timezone) — resolve at task 4.1 before
  implementing the cron matcher. Default: schedule-timezone.

---

## Wave A — Foundation

### S-149 (#261) — schedules + notifications schema  ·  branch `story/S-149-schedules-schema`
- [ ] 1.1 `[T]` L2.5 `panel/tests/integration/schedules-schema.test.ts`: migration applies on `db reset`; RLS deny-all on `schedules` + `notifications` (anon 0 rows, non-vacuous seeded guard); `chk_schedule_cadence` rejects each malformed kind/field combo; `uq_notifications_run_kind` rejects a duplicate `(run_id, kind)`.
- [ ] 1.2 `[I]` New migration `supabase/migrations/<ts>_scheduler_schema.sql`: enums `schedule_state` / `cadence_kind` / `notification_kind`; `schedules` table (all cols/indexes/constraints per spec §2.1, incl. `pr_block_run_id` / `pr_block_cleared_at`); `notifications` table (spec §2.2, incl. `uq_notifications_run_kind`); `enable row level security` on both.
- [ ] 1.3 `[I]` Add hand-written row types to `panel/lib/supabase/types.ts` (`ScheduleRow`, `NotificationRow`) + the `TriggerType`/enum unions if needed.
- [ ] 1.4 Run L2.5, `make validate`; record `coverage_gate`.
- [ ] 1.5 `verifier` audit; open PR → `integration/agent-scheduler`.

### S-150 (#262) — buildRunInsert trigger descriptor  ·  branch `story/S-150-run-insert-trigger`
- [ ] 2.1 `[T]` L1 `panel/tests/unit/run-insert.test.ts` additions: manual descriptor → prior `manual`/`panel` shape (byte-identical); schedule descriptor → `schedule`/`schedule:<id>`; type-level reject of a malformed identity; invoke-route builder regression.
- [ ] 2.2 `[I]` `panel/lib/domain/run-insert.ts`: add `TriggerDescriptor`, make `buildRunInsert` take `trigger`; keep timeout snapshots + `RunSnapshotError` unchanged.
- [ ] 2.3 `[I]` Update `panel/app/api/agents/[slug]/invoke/route.ts` to pass the manual descriptor (behavior unchanged).
- [ ] 2.4 `make validate` (existing invoke tests must pass unchanged); `coverage_gate`.
- [ ] 2.5 `verifier` audit; open PR.

### S-151 (#263) — pg_net + Vault + settings + runbook  ·  branch `story/S-151-pgnet-vault-settings`
- [ ] 3.1 `[T]` L2.5 `panel/tests/integration/scheduler-extensions.test.ts`: `pg_net` present after reset; a `vault.read_secret('scheduler_trigger_secret')` resolves in the local test context; the DB settings read back.
- [ ] 3.2 `[I]` Migration: `create extension if not exists pg_net`; Vault secret bootstrap note; `app.panel_base_url` / `app.scheduler_max_inflight` (default 3) settings.
- [ ] 3.3 `[I]` `docs/runbooks/scheduler-deployment.md` (same PR, FR-49a): enable `pg_net` + Vault in the dashboard; set the Vault secret + `fly secrets SCHEDULER_TRIGGER_SECRET`; set the DB settings; the privileged-step checklist.
- [ ] 3.4 `make validate`; `coverage_gate`.
- [ ] 3.5 `verifier` audit; open PR.

---

## Wave B — Trigger (A1)

### S-152 (#264) — compute_next_run_at + DST + cron + RPC  ·  branch `story/S-152-compute-next-run`
- [ ] 4.1 **Resolve OQ-S2** (advanced cron timezone — default schedule-tz) and note it in the migration + the issue.
- [ ] 4.2 `[T]` L2.5 `panel/tests/integration/compute-next-run.test.ts`: per-kind matrix with a fixed clock; **DST matrix** (daily/weekly at a fixed local time yields the shifted UTC instant on both sides — AC1); `every_n_hours` chains from `last_fired_at`; cron accept/reject table; unparseable → null + surfaced error; **RPC parity** with the direct call.
- [ ] 4.3 `[T]` L1 `panel/tests/unit/cadence-cron.test.ts`: the TS client-side cron grammar pre-validator (reject-before-save), mirroring the plpgsql grammar.
- [ ] 4.4 `[I]` Migration: plpgsql `compute_next_run_at(schedule_row, from_ts)` (5 kinds via `at time zone`); the closed cron matcher (bounded lookahead); the Supabase RPC wrapper (SD-T6).
- [ ] 4.5 `[I]` `panel/lib/domain/cadence.ts`: the TS cron pre-validator + the human-summary/label formatters (pure; the next-run math stays server-side via RPC).
- [ ] 4.6 `make validate`; `coverage_gate`.
- [ ] 4.7 `verifier` audit; open PR.

### S-153 (#265) — fire endpoint + shared-secret internal class  ·  branch `story/S-153-fire-endpoint`
- [ ] 5.1 `[T]` L1 `panel/tests/unit/internal-auth.test.ts`: constant-time compare decision (fail-closed on absent/short/mismatch); `route-policy` `internal` classification (exact `/api/internal/**`, siblings unaffected).
- [ ] 5.2 `[T]` L1 `panel/tests/unit/fire-route.test.ts`: handler ordering with mocked invoke/queries — 401 before any work on bad secret; 409 on stale/disabled; insert-then-invoke; `markRunFailedToStart` on throw; 202/200 shapes.
- [ ] 5.3 `[T]` L2.5 `panel/tests/integration/fire-insert.test.ts`: a correct-secret fire inserts a run with `trigger_type='schedule'`/`triggered_by='schedule:<id>'` (AC2).
- [ ] 5.4 `[T]` E2E `panel/tests/e2e/scheduler-internal-auth.spec.ts`: unauthenticated `POST /api/internal/schedules/<id>/fire` → 401.
- [ ] 5.5 `[I]` `lib/auth/route-policy.ts` + `middleware.ts`: the `internal` route class (bypass session, never 200-short-circuit).
- [ ] 5.6 `[I]` `panel/app/api/internal/schedules/[id]/fire/route.ts`: constant-time secret check (fail-closed 401, never logged) → load schedule (409) → guardrail hooks (no-ops until S-154/S-155/S-156) → `validateParams` → `buildRunInsert` schedule descriptor → `insertQueuedRun` → `invokeAgentRuntime` → `markRunFailedToStart` on throw → 202/200.
- [ ] 5.7 `make validate`; `coverage_gate`.
- [ ] 5.8 `verifier` audit; open PR.

### S-154 (#266) — fire_due_schedules tick + G4 + G2  ·  branch `story/S-154-due-tick`
- [ ] 6.1 `[T]` L2.5 `panel/tests/integration/fire-due-schedules.test.ts`: 5 due / cap 3 → 3 dispatch + 2 `concurrency_cap` skip, re-eval next tick (AC7); no-catch-up (passed due → next future only, miss recorded — AC5); `next_run_at` monotonic advance; `net.http_post` call shape (HTTP target stubbed/inspected); stale `running` over-counts safely for one tick.
- [ ] 6.2 `[I]` Migration: plpgsql `fire_due_schedules()` (in-flight count → due select `for update skip locked` LIMIT cap−inflight → over-cap skip reason → `net.http_post` with the Vault secret → advance `next_run_at` via `compute_next_run_at(now())`); `cron.schedule('fire-due-schedules','* * * * *',…)`.
- [ ] 6.3 `make validate`; `coverage_gate`.
- [ ] 6.4 `verifier` audit; open PR.

---

## Wave C — Guardrails

### S-155 (#267) — G1 overlap suppression  ·  branch `story/S-155-overlap`
- [ ] 7.1 `[T]` L2.5 `panel/tests/integration/guardrail-overlap.test.ts`: a non-terminal prior run (by `effective_status`) blocks the next firing (`block_reason='overlap'`); auto-clears across a status transition to terminal (AC4); a stale `running` does not block forever.
- [ ] 7.2 `[I]` Add the overlap check to `fire_due_schedules()` and re-check at the fire endpoint; set/clear `state='blocked'`/`block_reason='overlap'`.
- [ ] 7.3 `make validate`; `coverage_gate`; `verifier`; PR.

### S-156 (#268) — G5 open-PR backoff (a+c) + manual clear  ·  branch `story/S-156-open-pr-backoff`
- [ ] 8.1 `[T]` L1: the resolve predicate (unresolved vs cleared vs superseded).
- [ ] 8.2 `[T]` L2.5 `panel/tests/integration/guardrail-open-pr.test.ts`: block when the schedule's (agent,repo) has an unresolved `pull_request` artifact (`block_reason='open_pr'`, `pr_block_run_id` set); manual clear (`pr_block_cleared_at`) resumes; a later manual run supersedes (AC8); v1 never calls GitHub.
- [ ] 8.3 `[I]` Open-PR check in `fire_due_schedules()` + fire endpoint; the manual-clear Server Action (`setPrBlockCleared`); the supersede-by-manual-run logic.
- [ ] 8.4 `make validate`; `coverage_gate`; `verifier`; PR.

### S-157 (#269) — G3 circuit breaker  ·  branch `story/S-157-circuit-breaker`
- [ ] 9.1 `[T]` L1: the threshold decision (increment/reset/trip).
- [ ] 9.2 `[T]` L2.5 `panel/tests/integration/guardrail-autopause.test.ts`: 3 consecutive failures → `state='paused'` + exactly one `schedule_auto_paused` notification + stops firing (AC6); a resume clears; one success resets the counter.
- [ ] 9.3 `[I]` `consecutive_failures` increment/reset at the fire endpoint; the `>= auto_pause_threshold` transition (flip `paused` + insert `schedule_auto_paused` in one tx). (Reaper-failure counter path lands with S-158.)
- [ ] 9.4 `make validate`; `coverage_gate`; `verifier`; PR.

---

## Wave D — Notifications

### S-158 (#270) — notify-sweep tick  ·  branch `story/S-158-notify-sweep`
- [ ] 10.1 `[T]` L2.5 `panel/tests/integration/notify-sweep.test.ts`: a reaper-marked `timed_out` scheduled run → exactly one `run_failed` notification (AC10) + counter increment + G3 applied; sweep idempotent (re-run → no dupes); `run_succeeded` only with opt-in; a late PR artifact → one `pr_opened` + the G5 block (SD-N3).
- [ ] 10.2 `[I]` Migration: plpgsql `sweep_schedule_notifications()` (insert `run_failed` for newly terminal-failed scheduled runs incl. reaper, `on conflict do nothing`; `pr_opened` + G5 block for new PR artifacts; `run_succeeded` on opt-in; update `consecutive_failures` + G3 for reaper failures); `cron.schedule('scheduler-notify-sweep','* * * * *',…)`.
- [ ] 10.3 `make validate`; `coverage_gate`; `verifier`; PR.

### S-159 (#271) — SES sender + IAM + daily digest  ·  branch `story/S-159-ses-digest`
- [ ] 11.1 `[T]` L1 `panel/tests/unit/ses.test.ts` + `digest.test.ts`: digest selection (`emailed_at is null`); empty window → 204/no send; exactly-once marking (only on confirmed send); `SES_SEND_FAILED` classifier (no content/cred leak) — SES mocked at the SDK boundary.
- [ ] 11.2 `[T]` L2.5 `panel/tests/integration/digest-marking.test.ts`: `emailed_at` set only after a (mocked-accept) send; a send failure leaves it null.
- [ ] 11.3 `[I]` `panel/lib/aws/ses.ts` (`@aws-sdk/client-ses`, reuse `lib/aws/credentials.ts`; classifier); pin `@aws-sdk/client-ses` in `panel/package.json` (audit-clean, `@smithy/core` dedup).
- [ ] 11.4 `[I]` `panel/app/api/internal/notifications/digest/route.ts` (shared-secret; select → 204-on-empty → render+send+mark); migration `cron.schedule('scheduler-daily-digest','<min> <hour> * * *',…)` (local hour → static UTC, SD-N6a).
- [ ] 11.5 `[I]` IAM: panel role gains `ses:SendEmail`/`SendRawEmail` on the verified sender ARN; secrets `NOTIFICATION_SENDER`/`NOTIFICATION_RECIPIENT`; update `docs/runbooks/scheduler-deployment.md` (SES sender verification + digest verify).
- [ ] 11.6 `make validate`; `coverage_gate`; `verifier`; PR.

### S-160 (#272) — release-gate assertion  ·  branch `story/S-160-release-gate`
- [ ] 12.1 `[T]` L1 `panel/tests/unit/panel-auth-check.test.ts` additions: `checkInternalRejected(probe)` accept/reject (401 pass; 200/404/409 fail).
- [ ] 12.2 `[I]` Add `checkInternalRejected` to `panel/scripts/panel-auth-check.mjs`; add the probe to `scripts/verify-panel-auth.sh` (unauth `POST /api/internal/schedules/<nonexistent>/fire` must 401); wire CI parser test; `shellcheck` the wrapper.
- [ ] 12.3 `make validate`; `coverage_gate`; `verifier`; PR.

---

## Wave E — UI (pinned to DESIGN.md §5.7/§5.8)

### S-161 (#273) — /schedules list + CRUD  ·  branch `story/S-161-schedules-list`
- [ ] 13.1 `[T]` L2 `panel/tests/component/schedules-table.test.tsx`: grid columns, state pills (incl. hollow paused dot), cadence formats, reason chips, pause/resume/delete wiring, nav flip, empty state — against DESIGN.md §5.7.
- [ ] 13.2 `[T]` L2.5 `panel/tests/integration/schedule-mutations.test.ts`: the pause/resume/delete Server Actions against a real DB (delete keeps produced runs).
- [ ] 13.3 `[T]` E2E `panel/tests/e2e/schedules-crud.spec.ts`: CRUD behind login (unauth → /login or 401, AC14).
- [ ] 13.4 `[I]` `getSchedules` query; `app/(panel)/schedules/page.tsx` + the semantic-table-on-grid components (§5.7); the unified reason row + `open_pr` "PR handled · resume anyway" clear (S-156 action); `app/(panel)/schedules/actions.ts` (pause/resume/delete); the delete `alertdialog` (§5.7.3); sidebar `Schedules` → live `NavItem` (`CalendarDots`); empty state + create flash.
- [ ] 13.5 Pixel match vs `docs/prototype/Agent Scheduler.dc.html`; `make validate`; `coverage_gate`; `verifier`; PR.

### S-162 (#274) — new/edit dialog + cadence picker + preview  ·  branch `story/S-162-schedule-dialog`
- [ ] 14.1 `[T]` L1: the cadence client pre-validator + form field mapping (reuse `lib/schema/form.ts`).
- [ ] 14.2 `[T]` L2 `panel/tests/component/schedule-dialog.test.tsx`: kind switching, preview rendering (from the RPC, mocked), param controls per schema, guardrail disclosure, submit pending/disabled — against §5.7.2.
- [ ] 14.3 `[T]` L2.5: create/edit persists a correct row + `next_run_at` (via the S-152 RPC).
- [ ] 14.4 `[T]` E2E: create a schedule for each enabled agent (schema-driven form, AC13).
- [ ] 14.5 `[I]` The dialog (§5.7.2): agent/repository selects, schema-driven `fieldrow` form + `validateParams` at save, cadence segmented control + kind fields + timezone (default America/Santiago), live summary + next-3 Preview from the RPC, collapsible guardrails (threshold default 3, notify_on_success default off, always-on G1/G5 lines); create + edit Server Actions.
- [ ] 14.6 Pixel match; `make validate`; `coverage_gate`; `verifier`; PR.

### S-163 (#275) — notifications feed + bell  ·  branch `story/S-163-notifications-feed`
- [ ] 15.1 `[T]` L2 `panel/tests/component/notifications-feed.test.tsx`: feed (grouped, kind dots, unread edge/weight, untrusted detail as text only), bell + unread badge, popover, mark-(all)-read, nav flip — against §5.8.
- [ ] 15.2 `[T]` L2.5: `getNotifications`/`getUnreadCount` + mark-read against a real DB (RLS deny-all preserved).
- [ ] 15.3 `[T]` E2E: feed renders + marks read (AC11).
- [ ] 15.4 `[I]` `/notifications` route + top-bar `Bell`/badge/popover; the queries; the grouped feed (inert text detail); mark-(all)-read Server Action; the daily-digest footer note; sidebar `Notifications` → live.
- [ ] 15.5 Pixel match; `make validate`; `coverage_gate`; `verifier`; PR.

### S-164 (#276) — agent-page scheduled indicator  ·  branch `story/S-164-agent-indicator`
- [ ] 16.1 `[T]` L2 + L2.5: the indicator render + link (§5.7.1); the count query.
- [ ] 16.2 `[I]` `N schedules` count in `/agents/[slug]` header linking to `/schedules?agent=<slug>`; zero-state per the prototype.
- [ ] 16.3 Pixel match; `make validate`; `coverage_gate`; `verifier`; PR.

---

## Integration & merge

- [ ] 17.1 All story PRs merged into `integration/agent-scheduler`.
- [ ] 17.2 Pre-merge drift/stale-doc sweep (technical-guidelines current-state rows, TESTING.md package/layer rows, DESIGN.md confirmed, roadmap row flipped to Done).
- [ ] 17.3 Full `make validate` on the integration branch (both branches green); E2E suite incl. the new scheduler specs; coverage rollup.
- [ ] 17.4 Operator deploy per `docs/runbooks/scheduler-deployment.md`: enable `pg_net`+Vault, set secrets/settings, SES sender verify, register the 3 `pg_cron` jobs, IAM `ses:SendEmail`; run the auth release gate (now asserting the internal-endpoint 401) against the deployed host.
- [ ] 17.5 Live verification: create a near-future schedule, confirm it fires once (trigger_type='schedule'), a guardrail skip is visible, a notification is recorded, and a digest sends.
- [ ] 17.6 Single reviewed PR `integration/agent-scheduler` → `main` (human review is the gate).

## Verifier Design-Mode recommendation

Before implementation starts, run `verifier` in **Design Mode** against this task list +
the spec to produce the compliance test plan (heaviest focus: the DST matrix S-152/AC1,
the guardrail matrix S-154–S-157, the exactly-once/reaper-failure notify-sweep S-158/AC10,
and the internal-endpoint auth S-153/S-160/AC3). The scheduler's correctness is almost
entirely in the plpgsql + Layer 2.5 surface, so the test plan should bias there.
