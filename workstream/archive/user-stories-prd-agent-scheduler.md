# User Stories — Agent Scheduler

> Derived from [`specification-prd-agent-scheduler.md`](../specification-prd-agent-scheduler.md)
> and [`prd-agent-scheduler.md`](../docs/requirements/prd-agent-scheduler.md). Stories are
> ordered for dependency-correct delivery (foundation → trigger → guardrails →
> notifications → UI). Each story lists its spec decisions, PRD FR/AC coverage, test
> layers (test-first per repo default), and — for UI stories — its pixel contract in
> `DESIGN.md`. Story IDs continue the fleet sequence from S-148: **S-149 … S-164**.

## Changelog

| Version | Date       | Summary                                      | Author           |
| ------- | ---------- | -------------------------------------------- | ---------------- |
| 1.0     | 2026-10-13 | Initial stories from spec v1.1 / PRD v1.0.   | product-engineer |

## Legend

- **Layers** per `TESTING.md`: L1 unit, L2 component, L2.5 integration (live local Supabase, `REQUIRE_LOCAL_DB=1`), E2E (Playwright).
- **Pixel contract** names the `DESIGN.md` section a UI story must match (plus `docs/prototype/Agent Scheduler.dc.html`).
- Every story is independently shippable behind the gate: the scheduler is inert until the `pg_cron` jobs are registered (S-152), so S-149…S-151 can merge without firing anything.

---

## Wave A — Foundation (schema + invoke-path refactor)

### S-149 — `schedules` + `notifications` schema, enums, RLS
**As** the control plane, **I need** the `schedules` and `notifications` tables with their enums, indexes, and deny-all RLS, **so that** schedules and notification events have a durable system of record.
- **Spec:** SD-S1, SD-S2, SD-N1, SD-N2 (unique `(run_id, kind)`), SD-G6 reason vocabulary (as a documented set, not a DB enum).
- **Covers:** FR1, FR15, FR16 (`notify_on_success` column), FR14 (reason columns).
- **Scope:** a timestamped migration adding `schedule_state`, `cadence_kind`,
  `notification_kind` enums; the two tables with all columns/constraints/indexes from
  spec §2.1/§2.2; `enable row level security` on both (D11 deny-all, service_role only);
  the `pr_block_run_id` / `pr_block_cleared_at` columns (G5 hooks). No functions, no cron,
  no app code.
- **AC:** migration applies cleanly on `supabase db reset`; both tables are RLS deny-all
  (anon reads 0 rows, non-vacuous seeded guard); the `chk_schedule_cadence` constraint
  rejects each malformed kind/field combo; `uq_notifications_run_kind` rejects a duplicate
  `(run_id, kind)`.
- **Layers:** L2.5 (migration apply, RLS deny-all on both tables mirroring
  `rls-deny-all.test.ts`, the cadence check matrix, the notifications unique).
- **DESIGN.md:** none.

### S-150 — `buildRunInsert` trigger descriptor (parameterize manual/schedule)
**As** the invoke path, **I need** `buildRunInsert` to accept a trigger descriptor **so that** scheduled runs record `trigger_type='schedule'` / `triggered_by='schedule:<id>'` while manual runs stay byte-identical.
- **Spec:** SD-X1.
- **Covers:** FR7 (partial — the builder half; AC2 is completed by S-153).
- **Scope:** change `RunInsert`/`buildRunInsert` in `panel/lib/domain/run-insert.ts` to take
  `trigger: TriggerDescriptor`; update the manual invoke route to pass the manual
  descriptor. Purely additive to callers; all three timeout snapshots + `RunSnapshotError`
  unchanged.
- **AC:** manual descriptor produces the exact prior row shape (`manual`/`panel`); the
  schedule descriptor produces `schedule`/`schedule:<id>`; a malformed `schedule:` identity
  is rejected at the type level; the existing invoke-route tests pass unchanged.
- **Layers:** L1 (`run-insert` descriptor cases, both branches), L1 regression on the invoke
  route builder call.
- **DESIGN.md:** none.

### S-151 — Supabase Vault secret + `pg_net` enablement + DB settings (migration + runbook)
**As** the operator, **I need** `pg_net` and Supabase Vault enabled and the scheduler secret + base-URL/cap settings provisioned **so that** the `pg_cron` jobs can call the panel securely.
- **Spec:** SD-A2, SD-T4, SD-T8, SD-G4 (`app.scheduler_max_inflight`), SD-X4.
- **Covers:** FR8 (storage half), §9 dependencies.
- **Scope:** migration `create extension if not exists pg_net`; the Vault secret bootstrap
  note (`scheduler_trigger_secret`); DB settings `app.panel_base_url`,
  `app.scheduler_max_inflight` (default 3); a runbook `docs/runbooks/scheduler-deployment.md`
  (enable `pg_net` + Vault in the dashboard, set the Vault secret + `fly secrets`
  `SCHEDULER_TRIGGER_SECRET`, set the DB settings) — **delivered in this same PR** per
  AGENTS.md FR-49a.
- **AC:** `pg_net` present after reset; `vault.read_secret('scheduler_trigger_secret')`
  resolves in a local test context; the runbook documents each privileged step.
- **Layers:** L2.5 (extension present, a settings read).
- **DESIGN.md:** none.

---

## Wave B — Trigger path (A1)

### S-152 — `compute_next_run_at` (cadence math + DST + cron parser) + RPC
**As** the scheduler, **I need** an authoritative DB function that computes a schedule's next firing instant in its timezone **so that** presets fire at the correct wall-clock time across DST and the UI preview has one source of truth.
- **Spec:** SD-T1, SD-T3, SD-T5, SD-T6.
- **Covers:** FR2, FR3; AC1 (DST).
- **Scope:** plpgsql `compute_next_run_at(schedule_row, from_ts)` for all five kinds
  (hourly/daily/weekly/every_n_hours/advanced) evaluated via `at time zone`; the closed
  cron grammar matcher (`* / number / list / range / */step`, bounded lookahead) for
  `advanced`; a Supabase RPC wrapper the panel calls for the live preview and next-3
  (SD-T6 — one implementation, no TS reimpl). **OQ-S2 resolution baked in: `advanced` cron
  is interpreted in the schedule timezone** (confirm at review; recommended, consistent
  with presets).
- **AC:** daily/weekly presets yield the correct UTC instant on both sides of a DST
  transition (fixed-clock fixtures, AC1); `every_n_hours` chains from `last_fired_at`;
  `advanced` cron matches/rejects per the grammar; an unparseable cron returns null + a
  surfaced error; the RPC returns the same values the internal computation does.
- **Layers:** L2.5 (per-kind + DST matrix against a real DB with a fixed clock; cron
  accept/reject table; RPC parity with the direct call). L1 for the TS cron-grammar
  client-side pre-validator used by the dialog (reject-before-save).
- **DESIGN.md:** none (feeds §5.7.2 preview).

### S-153 — Fire endpoint `POST /api/internal/schedules/[id]/fire` + shared-secret auth
**As** `pg_cron`, **I need** an authenticated internal endpoint that performs a scheduled invocation via the existing invoke path **so that** Postgres triggers execution without holding AWS credentials, and no open invoke hole exists.
- **Spec:** SD-T9, SD-A1, SD-X1 (consumes S-150).
- **Covers:** FR5, FR6, FR8 (verification half), FR7/AC2 (completes), FR25 (internal class), AC3.
- **Scope:** the `internal` route class in `lib/auth/route-policy.ts` + `middleware.ts`
  (bypass session, never short-circuit to 200); the handler: constant-time secret compare
  (fail-closed 401, never logged), load schedule (409 on stale/disabled), re-run guardrails
  (hooks for S-154/S-156, no-ops until those land), Ajv-validate params, insert queued run
  via the schedule descriptor, `invokeAgentRuntime`, `markRunFailedToStart` on throw,
  `202 {run_id}` / `200 {skipped,reason}`. Reuses the manual route's normative ordering
  exactly.
- **AC:** unauthenticated/wrong-secret → 401 (not 404/409, which would mean the handler ran
  past auth); correct secret fires a run with `trigger_type='schedule'`/`triggered_by=
  'schedule:<id>'` (AC2); an invoke throw marks `failed_to_start`; a stale/disabled schedule
  → 409; secret never in logs.
- **Layers:** L1 (constant-time compare decision; route-policy `internal` classification;
  handler ordering with mocked invoke/queries), L2.5 (real insert + schedule-descriptor row
  shape), E2E (unauth 401, mirroring the auth-gate E2E).
- **DESIGN.md:** none.

### S-154 — `fire_due_schedules()` due-evaluation `pg_cron` tick + G4 cap + G2 no-catch-up
**As** the scheduler, **I need** a minute `pg_cron` job that finds due schedules, enforces the concurrency cap, dispatches via `pg_net`, and advances the cursor without catch-up **so that** schedules fire on cadence, bounded, with no backlog.
- **Spec:** SD-T2, SD-T4, SD-T7, SD-G2, SD-G4, SD-G0 (effective_status).
- **Covers:** FR4, FR5, FR10 (G2), FR12 (G4); AC5, AC7.
- **Scope:** plpgsql `fire_due_schedules()` (`security definer`): in-flight count (G4),
  select due `is_enabled and state='active' and next_run_at<=now()` `for update skip locked`
  LIMIT `(cap − in_flight)`, over-cap → `last_skipped_reason='concurrency_cap'`; per selected
  schedule emit `net.http_post` (secret from Vault) and advance `next_run_at` via
  `compute_next_run_at(now())` (G2 no-catch-up); `cron.schedule('fire-due-schedules','* * * * *',…)`.
- **AC:** 5 due with cap 3 → 3 dispatch, 2 skipped `concurrency_cap`, re-evaluated next tick
  (AC7); a due time passed while down → next future occurrence only, miss recorded (AC5/G2);
  `next_run_at` advances monotonically; stale `running` counts against the cap for at most a
  tick (safe over-count).
- **Layers:** L2.5 (cap matrix, no-catch-up, cursor advance, `pg_net` call shape — the HTTP
  target stubbed/inspected).
- **DESIGN.md:** none.

---

## Wave C — Guardrails

### S-155 — G1 overlap suppression
**As** the scheduler, **I need** to skip a firing while a prior run for the same (agent, repository) is non-terminal **so that** long runs don't double-fire.
- **Spec:** SD-G1, SD-G0, SD-G6 (unified reason).
- **Covers:** FR9, FR14; AC4.
- **Scope:** overlap check in `fire_due_schedules()` and re-checked at the fire endpoint
  (defense in depth), using `effective_status in ('queued','running')`; set
  `state='blocked'`, `block_reason='overlap'`; auto-clear on the next tick once terminal.
- **AC:** a non-terminal prior run blocks the next due firing with reason `overlap`;
  clears automatically when that run reaches a terminal state (AC4); a stale `running`
  does not block forever (resolves via effective_status / the reaper).
- **Layers:** L2.5 (block + auto-clear across a status transition).
- **DESIGN.md:** reason chip rendered by S-161 (§5.7).

### S-156 — G5 open-PR backoff (phased a+c) + manual clear
**As** the operator, **I need** a schedule to stop firing while a prior run of the same (agent, repository) has an unresolved PR, cleared manually or by a later manual run **so that** unattended fix-mode schedules don't stack PRs.
- **Spec:** SD-G5, SD-G5a, SD-N3 (PR detection by sweep sets the block).
- **Covers:** FR13, FR13a, FR13b, FR14; AC8. (FR-FF1 auto-poll explicitly out of scope — the `pr_block_run_id`/`pr_block_cleared_at` hooks from S-149 are its future seam.)
- **Scope:** open-PR check (most-recent `pull_request` artifact for the schedule's
  (agent, repository), unresolved) → `state='blocked'`, `block_reason='open_pr'`,
  `pr_block_run_id` set; manual clear Server Action setting `pr_block_cleared_at` (G5-c);
  supersede-by-later-manual-run logic (G5-a).
- **AC:** a scheduled run that opened a PR blocks the next firing with reason `open_pr`;
  the manual clear resumes firing; a later manual run of the same (agent, repository)
  supersedes the block; v1 does NOT consult GitHub (documented limitation).
- **Layers:** L2.5 (block on artifact present, manual clear, supersede path), L1 (resolve
  predicate).
- **DESIGN.md:** the "PR handled · resume anyway" ghost action rendered by S-161 (§5.7).

### S-157 — G3 circuit breaker (consecutive-failure auto-pause)
**As** the scheduler, **I need** to auto-pause a schedule after N consecutive failed firings and notify **so that** a broken schedule stops hammering a broken agent.
- **Spec:** SD-G3, SD-N1 (`schedule_auto_paused`), SD-G6.
- **Covers:** FR11; AC6. (Depends on S-153 for invoke-time failures and S-158 for reaper-materialized failures feeding the counter.)
- **Scope:** `consecutive_failures` increment on a terminal-failure run / fire-time error,
  reset on success; at `>= auto_pause_threshold` flip `state='paused'`,
  `block_reason='auto_paused:consecutive_failures'`, and insert the `schedule_auto_paused`
  notification in the same transaction; the counter is updated at BOTH the fire endpoint
  and the sweep (S-158).
- **AC:** 3 consecutive failures → `paused` + exactly one `schedule_auto_paused`
  notification + stops firing; a manual resume (S-161) clears it; one subsequent success
  resets the counter to 0 (AC6).
- **Layers:** L2.5 (increment/reset/threshold transition writes exactly one notification),
  L1 (threshold decision).
- **DESIGN.md:** paused state + auto-pause reason chip rendered by S-161 (§5.7); the
  notification by S-162 (§5.8).

---

## Wave D — Notifications (table consumers)

### S-158 — Notify-sweep `pg_cron` tick (durable recording + reaper-materialized failures)
**As** the system, **I need** a minute sweep that records notable scheduled-run events the panel didn't observe **so that** reaper-materialized failures and late PR artifacts still notify exactly once.
- **Spec:** SD-N1 (sweep source), SD-N2, SD-N3, SD-G3 (counter for reaper failures).
- **Covers:** FR15, FR16, FR17; AC9 (recording), AC10.
- **Scope:** plpgsql `sweep_schedule_notifications()`: insert `run_failed` for scheduled
  runs newly terminal-failed (incl. reaper `timed_out`/`failed_to_start`) via `on conflict
  (run_id,kind) do nothing`; insert `pr_opened` for scheduled runs that now have a
  `pull_request` artifact + set the G5 block (SD-N3); insert `run_succeeded` only when the
  schedule's `notify_on_success` is on; update `consecutive_failures` + apply G3 for
  reaper-materialized failures; `cron.schedule('scheduler-notify-sweep','* * * * *',…)`.
- **AC:** a reaper-marked `timed_out` scheduled run yields exactly one `run_failed`
  notification (AC10) and increments the counter; the sweep is idempotent (re-run → no
  dupes); `run_succeeded` only with opt-in; a late PR artifact yields one `pr_opened` + the
  G5 block.
- **Layers:** L2.5 (reaper-failure → notification + counter; idempotency; opt-in success;
  PR-opened → block).
- **DESIGN.md:** none (feeds §5.8).

### S-159 — SES sender module + IAM + daily digest endpoint/tick
**As** the operator, **I need** one daily email digest of notable notifications **so that** I'm informed without per-run spam, over the no-static-keys credential path.
- **Spec:** SD-N6, SD-N6a, SD-N7, SD-N8, SD-X2.
- **Covers:** FR19, FR20, FR21; AC12, AC15 (SES half). (Depends on S-153 internal class, S-158 recording.)
- **Scope:** `panel/lib/aws/ses.ts` (`@aws-sdk/client-ses`, reuses `lib/aws/credentials.ts`
  Fly OIDC → STS; `SES_SEND_FAILED` classifier, never leaks content/creds); the IAM role
  gains `ses:SendEmail`/`SendRawEmail` on the verified sender ARN (never `*`);
  `POST /api/internal/notifications/digest` (shared-secret) selecting `emailed_at is null`,
  **204 + no send on empty window**, else render + send + set `emailed_at` **only on
  confirmed send** (exactly-once, retry-safe); daily `cron.schedule('scheduler-daily-digest',
  '<minute> <hour> * * *',…)` at the configured local hour converted to a static UTC cron
  (SD-N6a). Secrets `NOTIFICATION_SENDER`/`NOTIFICATION_RECIPIENT` + runbook update.
- **AC:** a day with notable events → exactly one email + those rows marked `emailed_at`
  (AC12); an empty window → 204, no email; a send failure leaves `emailed_at` null (retries
  next day); no static AWS keys (OIDC → STS, AC15); the digest covers notable events only.
- **Layers:** L1 (digest selection, empty→204, exactly-once marking, SES error classifier —
  SES mocked at the SDK boundary), L2.5 (`emailed_at` marking against a real DB),
  release-gate note (the digest endpoint rejects unauth — part of S-160).
- **DESIGN.md:** the digest footer note in §5.8.

### S-160 — Release-gate assertion: `/api/internal/**` rejects unauthenticated
**As** the operator, **I need** the auth release gate to mechanically prove the internal scheduler endpoints are not an open invoke hole **so that** a regression can't ship a public fire path.
- **Spec:** SD-A4.
- **Covers:** FR26, AC3 (mechanized), AC14 (boundary split asserted).
- **Scope:** add a pure `checkInternalRejected(probe)` to `panel/scripts/panel-auth-check.mjs`
  and a probe to `scripts/verify-panel-auth.sh`: an unauthenticated `POST
  /api/internal/schedules/<nonexistent>/fire` must return 401 (not 200/404/409). CI runs the
  new parser unit test; the live wrapper runs against the deployed host.
- **AC:** the gate fails the release if the internal endpoint returns anything but 401 to an
  unauthenticated/wrong-secret probe; the parser unit test covers accept/reject;
  `shellcheck` clean.
- **Layers:** L1 (parser decision), release-gate wiring.
- **DESIGN.md:** none.

---

## Wave E — UI (pinned to DESIGN.md §5.7/§5.8)

### S-161 — `/schedules` list + CRUD (list, pause/resume, delete, blocked/skipped reasons)
**As** the operator, **I need** a fleet-wide schedules screen to see and manage all schedules **so that** I can create, pause, resume, and delete them and understand why one didn't fire.
- **Spec:** SD-UI-1, SD-A3, SD-G6 (reason surface), SD-G1/G5 clears.
- **Covers:** FR22, FR14 (reason display), FR13a (PR-handled clear), AC14 (CRUD behind login).
- **Scope:** `/schedules` route + `getSchedules` server read (SD2, RLS deny-all); the
  semantic-table-on-grid per §5.7; State/Agent/Repository/Cadence/Next run/Last run/Actions;
  the unified blocked/skipped reason row + the `open_pr` "PR handled · resume anyway" clear
  (S-156 action); pause/resume/delete Server Actions (`app/(panel)/schedules/actions.ts`,
  SD2 exemption already covers `app/**/actions.ts`); the delete `alertdialog` (§5.7.3); the
  sidebar `Schedules` `DisabledNavItem` → live `NavItem` (`CalendarDots`); the empty state;
  the create-success flash.
- **AC:** matches `DESIGN.md §5.7` + `docs/prototype/Agent Scheduler.dc.html` (grid columns,
  state pills incl. hollow paused dot, cadence formats, reason chips); CRUD operations
  redirect `/login` (UI) / 401 (API) when unauthenticated (AC14); delete keeps the
  schedule's runs; the nav item is active on `/schedules`.
- **Layers:** L2 (table, state pills, reason chips, pause/resume/delete wiring, nav flip,
  empty state), L2.5 (the Server-Action writes against a real DB), E2E (CRUD behind login).
- **Pixel contract:** `DESIGN.md §5.7` (+ §5.7.3 delete).

### S-162 — New/Edit schedule dialog (schema-driven form + cadence picker + preview + guardrails)
**As** the operator, **I need** a dialog to create or edit a schedule with the agent's params and a cadence picker **so that** any agent is schedulable with a correct, previewed cadence.
- **Spec:** SD-UI-2, SD-T6 (RPC preview), SD-A3.
- **Covers:** FR24, FR3 (tz default), FR11/FR16 (threshold + success opt-in in the guardrail section), AC13.
- **Scope:** the dialog per §5.7.2: agent select → schema-driven `fieldrow` form (reuses
  `lib/schema/form.ts` + `validateParams`), repository select (separate, first, when
  required), the cadence segmented control + kind fields + timezone (default
  `America/Santiago`), the live summary + next-3-runs **Preview** sourced from the S-152 RPC,
  the collapsible guardrails (auto_pause_threshold default 3, notify_on_success default off,
  the always-on G1/G5 read-only lines), the footer with pending/disabled submit; create +
  edit Server Actions validating params against `params_schema` at save.
- **AC:** matches `DESIGN.md §5.7.2`; renders the correct param form for each enabled agent
  from its `params_schema` and validates with Ajv at save (AC13); the preview updates live
  and agrees with the stored `next_run_at`; an invalid cadence disables submit; a new agent
  needs no scheduler-specific code.
- **Layers:** L1 (cadence client pre-validator, form field mapping), L2 (dialog: kind
  switching, preview rendering, param controls, guardrail disclosure, submit states), L2.5
  (create/edit persists a correct row + `next_run_at`), E2E (create a schedule per agent).
- **Pixel contract:** `DESIGN.md §5.7.2`.

### S-163 — Notifications feed + top-bar bell + mark-read
**As** the operator, **I need** an in-panel notifications feed and a bell with an unread badge **so that** I see notable scheduled-run events in real-ish time without email.
- **Spec:** SD-UI-3, SD-N5, SD-N8.
- **Covers:** FR18, FR20 (panel as one consumer); AC11.
- **Scope:** `/notifications` route + top-bar `Bell` + unread badge + popover (5 newest) per
  §5.8; `getNotifications`/`getUnreadCount` server reads (SD2, RLS deny-all); the grouped
  feed (kind-colored dots, unread edge/weight, untrusted detail as text only, run/schedule/PR
  links, relative time); mark-(all)-read Server Action; the daily-digest footer note; the
  sidebar `Notifications` nav flip to live.
- **AC:** matches `DESIGN.md §5.8` + prototype; renders newest-first with unread treatment
  and mark-(all)-read (AC11); detail renders inert text only (never markup/metadata link);
  reads server-side with RLS deny-all preserved; the bell badge reflects the unread count.
- **Layers:** L2 (feed, bell/badge, popover, mark-read, nav flip, untrusted-detail-as-text),
  L2.5 (reads + mark-read against a real DB), E2E (feed renders + marks read).
- **Pixel contract:** `DESIGN.md §5.8`.

### S-164 — Agent-page scheduled indicator
**As** the operator, **I need** a read-only "N schedules" pointer on the agent run-history header **so that** I can jump from an agent to its schedules.
- **Spec:** SD-UI-4.
- **Covers:** FR23.
- **Scope:** a `N schedules` count (server-read) in the `/agents/[slug]` header linking to
  `/schedules?agent=<slug>` (which renders the §5.7 header filter chip). No CRUD on the agent
  page.
- **AC:** matches `DESIGN.md §5.7.1`; the count is accurate; the link lands on `/schedules`
  filtered to the agent; zero schedules renders nothing (or a `0`-state per the prototype).
- **Layers:** L2 (indicator render + link), L2.5 (count query).
- **Pixel contract:** `DESIGN.md §5.7.1`.

---

## Coverage Validation

### FR → story

| FR | Story(ies) |
| --- | --- |
| FR1 schedules table | S-149 |
| FR2 structured cadence | S-152, S-162 |
| FR3 timezone + DST | S-152, S-162 |
| FR4 due-tick | S-154 |
| FR5 pg_net → endpoint | S-153, S-154 |
| FR6 reuse invoke path | S-153 |
| FR7 trigger_type/triggered_by | S-150 (builder) + S-153 (wired) |
| FR8 shared-secret class | S-151 (storage) + S-153 (verify) |
| FR9 G1 overlap | S-155 |
| FR10 G2 no-catch-up | S-154 |
| FR11 G3 circuit breaker | S-157 |
| FR12 G4 concurrency cap | S-154 |
| FR13 G5 open-PR backoff | S-156 |
| FR13a manual clear | S-156 + S-161 (action UI) |
| FR13b supersede by manual run | S-156 |
| FR14 unified blocked/skipped | S-149 (columns) + S-155/S-156 (set) + S-161 (display) |
| FR15 notifications table | S-149, S-158 |
| FR16 notable event set | S-158 (+ S-162 success opt-in config) |
| FR17 durable + exactly-once | S-158 |
| FR18 panel feed | S-163 |
| FR19 daily digest | S-159 |
| FR20 channel-agnostic | S-158 (recording) + S-159/S-163 (consumers) |
| FR21 sender/recipient config | S-159 |
| FR22 /schedules CRUD | S-161 |
| FR23 agent indicator | S-164 |
| FR24 schema-driven form | S-162 |
| FR25 auth split | S-153 (internal) + S-161/S-162/S-163 (human) |
| FR26 release-gate assertion | S-160 |

### AC → story

| AC | Story |
| --- | --- |
| AC1 DST | S-152 |
| AC2 trigger-tagged run | S-150 + S-153 |
| AC3 internal 401 | S-153 + S-160 |
| AC4 G1 | S-155 |
| AC5 G2 | S-154 |
| AC6 G3 | S-157 |
| AC7 G4 | S-154 |
| AC8 G5 | S-156 |
| AC9 notifications recorded | S-158 |
| AC10 reaper failure notifies | S-158 |
| AC11 panel feed | S-163 |
| AC12 daily digest | S-159 |
| AC13 schema-driven form | S-162 |
| AC14 CRUD behind login | S-161 (+ S-153/S-160 boundary) |
| AC15 no static keys | S-159 |

**Every FR and AC is covered.** No orphan stories; no uncovered requirements.

### Dependency order (for `plan`)

```
S-149 ─┬─ S-150 ─┐
       │         ├─ S-153 ─┬─ S-154 ─┬─ S-155
S-151 ─┘  S-152 ─┘         │         ├─ S-156
                            │         └─ S-157 ─┐
                            │                   ├─ S-158 ─ S-159 ─ S-160
                            └───────────────────┘
UI (S-161…S-164) depend on their data stories (S-154/S-156/S-157/S-158) but can
start against the schema (S-149) with the server actions stubbed; recommend
S-161 → S-162 → S-163 → S-164 after Wave C/D land.
```

### DESIGN.md impact (UI stories)

| Story | Pixel contract |
| --- | --- |
| S-161 | §5.7 (+ §5.7.3) |
| S-162 | §5.7.2 |
| S-163 | §5.8 |
| S-164 | §5.7.1 |

All four reference `docs/prototype/Agent Scheduler.dc.html` as the committed visual source.
No new DESIGN token or component variant is introduced by any story (DESIGN.md v1.11).

### Test-first note

Per the repo default, every story is delivered test-first: L1/L2 (and L2.5 where a DB is
involved) authored before implementation, with the guardrail/cron stories (S-152, S-154–S-158)
carrying the heaviest L2.5 burden against the live local Supabase stack (the reaper
integration-test precedent). `verifier` Design Mode should produce the compliance test plan
before implementation starts.
