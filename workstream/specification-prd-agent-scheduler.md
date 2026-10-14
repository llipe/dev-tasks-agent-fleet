# Technical Specification — Agent Scheduler

> HOW-level design for [`prd-agent-scheduler.md`](../docs/requirements/prd-agent-scheduler.md).
> Grounds every PRD requirement in the current code and data model. The scheduler runs
> on the deployed `pg_cron`, triggers execution via `pg_net` → an internal panel
> endpoint (A1), reuses the existing manual-invoke path, and records notifications in a
> channel-agnostic table consumed by an in-panel feed and a daily SES digest.

## Changelog

| Version | Date       | Summary                                                                 | Author           |
| ------- | ---------- | ----------------------------------------------------------------------- | ---------------- |
| 1.1     | 2026-10-13 | **UI sections finalized.** The Claude Design prototype was delivered and reviewed (`docs/prototype/Agent Scheduler.dc.html`, same Nocturne `_ds` bundle as every existing screen) and folded into `DESIGN.md` v1.11 (§5.7 Schedules + §5.7.1/§5.7.2/§5.7.3, §5.8 Notifications, §4.1 nav-state, §10 icons). §7 (SD-UI-*) flipped from PENDING PROTOTYPE to **FINAL**, each decision pinned to its DESIGN.md section. No non-UI change. | product-engineer |
| 1.0     | 2026-10-13 | Initial spec from PRD v1.0. UI sections (SD-UI-*) are grounded in the current Nocturne system but marked **PENDING PROTOTYPE** — they will be pinned to pixel-exact `DESIGN.md` §5 references once the Claude Design prototype (`workstream/claude-design-prompt-agent-scheduler.md`) is delivered and folded into `DESIGN.md`. All non-UI sections are final. | product-engineer |

---

## 1. Scope & Grounding

This spec covers the `schedule` branch of `runs.trigger_type` (already in the enum,
unused). It reuses, without re-implementing:

- the manual invoke path: `panel/app/api/agents/[slug]/invoke/route.ts` →
  `lib/domain/run-insert.ts` (`buildRunInsert`) → `lib/supabase/queries.ts`
  (`insertQueuedRun`, `markRunFailedToStart`, `updateRunInvocationRefs`) →
  `lib/aws/invoke.ts` (`invokeAgentRuntime`) over `lib/aws/credentials.ts` (Fly OIDC → STS);
- the `pg_cron` + plpgsql pattern proven by the reaper
  (`supabase/migrations/20260902200101_initial_schema.sql`, `reap_stale_runs()`,
  `cron.schedule('reap-stale-runs','* * * * *', …)`);
- the `effective_status` view logic (`v_runs`, `lib/domain/status.ts`) for staleness-aware
  guardrails;
- the `pull_request` artifact read (`getPullRequestArtifactsForRuns`) for G5;
- the server-only Supabase boundary (SD2) and the ADR-007 login gate (`middleware.ts`).

**Decision prefix:** scheduler decisions are numbered `SD-S*` (schema), `SD-T*`
(trigger/cron), `SD-G*` (guardrails), `SD-N*` (notifications), `SD-A*` (auth/boundary),
`SD-UI-*` (UI, pending prototype), `SD-X*` (cross-cutting).

---

## 2. Data Model

### 2.1 `schedules` table (SD-S1)

```sql
create type schedule_state as enum ('active', 'paused', 'blocked');
create type cadence_kind   as enum ('hourly', 'daily', 'weekly', 'every_n_hours', 'advanced');

create table schedules (
  id                      uuid primary key default gen_random_uuid(),
  agent_id                uuid not null references agents(id) on delete cascade,
  repository_id           uuid references repositories(id) on delete cascade,
  installation_id         uuid references github_installations(id) on delete set null,

  name                    text,                      -- optional operator label
  params                  jsonb not null default '{}'::jsonb,   -- validated vs params_schema at write

  -- cadence (structured is the source of truth, SD-T1)
  cadence_kind            cadence_kind not null,
  cadence_minute          smallint,                  -- 0..59   (daily/weekly/hourly)
  cadence_hour            smallint,                  -- 0..23   (daily/weekly)
  cadence_weekday         smallint,                  -- 0..6, 0=Sunday (weekly)
  cadence_interval_hours  smallint,                  -- 1..168  (every_n_hours)
  cadence_cron            text,                      -- 5-field (advanced only)
  timezone                text not null default 'America/Santiago',   -- IANA

  state                   schedule_state not null default 'active',
  is_enabled              boolean not null default true,   -- operator on/off, distinct from paused/blocked

  -- guardrail bookkeeping
  consecutive_failures    integer not null default 0,
  auto_pause_threshold    integer not null default 3,      -- G3 (FR11), per-schedule
  block_reason            text,                            -- unified blocked/skipped reason (FR14)
  blocked_at              timestamptz,
  last_skipped_reason     text,
  last_skipped_at         timestamptz,

  -- notification opt-in
  notify_on_success       boolean not null default false,  -- FR16

  -- firing bookkeeping
  last_fired_at           timestamptz,                     -- when a fire was dispatched
  last_run_id             uuid references runs(id) on delete set null,
  next_run_at             timestamptz,                     -- computed; the due cursor (SD-T3)
  last_fire_error         text,                            -- pg_net/endpoint failure (R-S2)

  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now(),

  constraint chk_schedule_cadence check (
    case cadence_kind
      when 'hourly'        then cadence_minute is not null
      when 'daily'         then cadence_minute is not null and cadence_hour is not null
      when 'weekly'        then cadence_minute is not null and cadence_hour is not null
                                 and cadence_weekday is not null
      when 'every_n_hours' then cadence_interval_hours is not null and cadence_interval_hours >= 1
      when 'advanced'      then cadence_cron is not null
    end
  )
);

create index idx_schedules_due     on schedules (next_run_at)
  where is_enabled and state = 'active';
create index idx_schedules_agent   on schedules (agent_id);
create index idx_schedules_repo    on schedules (repository_id);

create trigger trg_schedules_updated
  before update on schedules for each row execute function set_updated_at();

alter table schedules enable row level security;   -- deny-all (D11), service_role only
```

**Notes.**
- `state` vs `is_enabled` (SD-S2): `is_enabled` is the operator's explicit on/off;
  `state` is the system-derived lifecycle (`active` → `paused` by G3, `blocked` by
  G1/G5). A paused-by-G3 schedule has `is_enabled = true, state = 'paused'`; a resume
  clears `state` back to `active` and resets `consecutive_failures`. A schedule the
  operator turns off has `is_enabled = false` and is simply not evaluated.
- `block_reason`/`last_skipped_reason` are the single unified "why it didn't fire"
  surface (FR14): one of `overlap`, `open_pr`, `concurrency_cap`, `missed_tick`.
  `blocked` (sticky, in `state`) is used for `overlap`/`open_pr`; `skipped` (transient,
  in `last_skipped_*`) for `concurrency_cap`/`missed_tick`.
- `next_run_at` is the **due cursor** (SD-T3), recomputed after each evaluation; the
  index on it is the hot path for the due-tick.

### 2.2 `notifications` table (SD-N1)

```sql
create type notification_kind as enum (
  'run_failed', 'schedule_auto_paused', 'pr_opened', 'run_succeeded'
);

create table notifications (
  id             uuid primary key default gen_random_uuid(),
  kind           notification_kind not null,
  schedule_id    uuid references schedules(id) on delete set null,
  agent_id       uuid references agents(id) on delete set null,
  repository_id  uuid references repositories(id) on delete set null,
  run_id         uuid references runs(id) on delete set null,

  title          text not null,                 -- rendered summary line
  detail         text,                          -- reason / error_code / PR url (untrusted → text only)
  data           jsonb not null default '{}'::jsonb,

  read_at        timestamptz,                   -- panel feed (FR18)
  emailed_at     timestamptz,                   -- digest delivery marker (FR19)

  created_at     timestamptz not null default now(),

  -- exactly-once per (kind, run) for run-tied events (FR17)
  constraint uq_notifications_run_kind unique (run_id, kind)
);

create index idx_notifications_created on notifications (created_at desc);
create index idx_notifications_unread  on notifications (created_at desc) where read_at is null;
create index idx_notifications_undelivered on notifications (created_at) where emailed_at is null;

alter table notifications enable row level security;   -- deny-all (D11)
```

**Exactly-once (SD-N2).** The `uq_notifications_run_kind` partial-free unique on
`(run_id, kind)` makes the notify-sweep idempotent for run-tied events (`run_failed`,
`pr_opened`, `run_succeeded`): an `insert … on conflict (run_id, kind) do nothing`
cannot double-record. `schedule_auto_paused` is keyed by the G3 transition writing the
row inside the same statement that flips `state` (so it fires once per pause). Rows
with `run_id is null` (auto-pause) are exempt from the unique — acceptable because the
pause transition is itself single-shot.

### 2.3 `buildRunInsert` parameterization (SD-X1, FR7)

`panel/lib/domain/run-insert.ts` currently hardcodes `trigger_type: "manual"` and
`triggered_by: "panel"`. Change the `RunInsert` type and `buildRunInsert` to accept a
**trigger descriptor**:

```ts
type TriggerDescriptor =
  | { triggerType: "manual"; triggeredBy: "panel" }
  | { triggerType: "schedule"; triggeredBy: `schedule:${string}` };
```

`buildRunInsert` takes `trigger: TriggerDescriptor` and writes `trigger_type`/`triggered_by`
from it. The manual invoke route passes the manual descriptor (behavior byte-identical);
the fire endpoint passes `{ triggerType: "schedule", triggeredBy: "schedule:<id>" }`. All
three timeout snapshots and the existing `RunSnapshotError` discipline are unchanged. This
is the ONLY change to the shared insert builder, and it is purely additive to callers.

---

## 3. Trigger Architecture (A1)

### 3.1 Due-evaluation `pg_cron` tick (SD-T2, FR4/FR5)

A single job mirrors the reaper exactly:

```sql
select cron.schedule('fire-due-schedules', '* * * * *', $$select fire_due_schedules()$$);
```

`fire_due_schedules()` (plpgsql, `security definer`, `search_path = public`):

1. Compute the current in-flight scheduled-run count (G4): `select count(*) from runs
   where trigger_type = 'schedule' and status in ('queued','running')` — refined by
   `effective_status` is unnecessary here because the reaper converges `running`→terminal
   within a tick; a stale `running` counting against the cap for one extra minute is a
   safe over-count.
2. Select due, clear schedules: `is_enabled and state = 'active' and next_run_at <= now()`,
   ordered by `next_run_at asc`, `for update skip locked`, LIMIT (G4 cap − in_flight).
   If the cap is already met, select zero and mark the would-be-due ones
   `last_skipped_reason = 'concurrency_cap'` (SD-G4).
3. For each selected schedule, re-check the per-schedule guardrails inline (SD-G1 overlap,
   SD-G5 open-PR) — see §4. A schedule failing a guardrail is set `state='blocked'` with
   `block_reason` and **skipped** (not fired, `next_run_at` left so it re-evaluates).
4. For a schedule that passes, issue the `pg_net` POST (SD-T4) and set `last_fired_at =
   now()`, then **advance `next_run_at`** to the next computed occurrence (SD-T3).

Due-ness is driven entirely by `next_run_at` (a materialized cursor), NOT by `pg_cron`
per-schedule cron entries — there is one cron job, like the reaper. This keeps `pg_cron`'s
own schedule table static and puts all cadence logic in plpgsql where the timezone/DST
math lives.

### 3.2 `next_run_at` computation + DST (SD-T3, FR3)

`compute_next_run_at(schedule, from_ts)` (plpgsql, pure) returns the next firing instant
`> from_ts`, evaluated **in the schedule's `timezone`** using Postgres timezone-aware
arithmetic (`timezone(tz, ts)` / `at time zone`), so wall-clock presets are correct
across DST:

- `hourly` → next instant at minute `cadence_minute` of some hour.
- `daily` → next `cadence_hour:cadence_minute` **local** day boundary; converted to UTC
  via `at time zone`, so a `07:00 America/Santiago` schedule yields a different UTC instant
  on either side of the DST change — exactly AC1.
- `weekly` → next occurrence of `cadence_weekday` at the local time.
- `every_n_hours` → `last_fired_at` (or `created_at`) + `interval 'N hours'`.
- `advanced` → parse the 5-field cron. **Decision SD-T5:** `advanced` cron is interpreted
  in the schedule's `timezone` as well (not UTC), via a small plpgsql cron matcher that
  steps minute-by-minute from `from_ts` in local time to the next match (bounded lookahead,
  e.g. 366 days, else null + a surfaced error). A nonstandard but closed cron grammar is
  accepted: `minute hour day-of-month month day-of-week`, each `*`, a number, a
  comma-list, a range, or `*/step`. Anything else is rejected at write-time by the panel
  validator (SD-UI/validate), never stored.

`compute_next_run_at` is called: on schedule create/edit (panel-side via an equivalent TS
mirror OR a DB round-trip — **SD-T6: the DB function is authoritative**; the panel calls a
Supabase RPC to compute `next_run_at` and the preview "next 3 runs" so there is one
implementation of the cadence math, not a TS copy that can drift from the plpgsql one),
and after each firing (to advance the cursor). The "next 3 runs" preview (SD-UI) calls the
same RPC three times with `from_ts` chained.

### 3.3 `pg_net` call (SD-T4, FR5)

```sql
-- inside fire_due_schedules(), per due schedule:
perform net.http_post(
  url     := <panel_base_url> || '/api/internal/schedules/' || sched.id || '/fire',
  headers := jsonb_build_object(
               'Content-Type', 'application/json',
               'X-Scheduler-Secret', vault.read_secret('scheduler_trigger_secret')
             ),
  body    := '{}'::jsonb,
  timeout_milliseconds := 5000
);
```

- `pg_net` is **fire-and-forget** by nature (async queue table); the tick does not block on
  the HTTP response. The panel endpoint is responsible for the full invoke; the tick only
  records that it dispatched (`last_fired_at`). The HTTP outcome is observable in
  `net._http_response` for diagnostics; `last_fire_error` is set opportunistically on the
  next tick if the prior dispatch's response was an error status (SD-T7 — best-effort, not a
  hard dependency).
- The panel base URL is a DB setting (`app.panel_base_url`) or a Vault secret, set per
  environment (local vs. the Fly public host). SD-T8.
- The secret is read from **Supabase Vault** (`vault.read_secret`), never inlined in the job
  body (SD-A2).

### 3.4 The fire endpoint (SD-T9, FR6)

`POST /api/internal/schedules/[id]/fire` (new route handler, inline route-segment config
per the §12 convention):

1. **Auth (SD-A1):** read `X-Scheduler-Secret`, constant-time compare against
   `SCHEDULER_TRIGGER_SECRET` (`fly secrets`), fail-closed `401` on absent/mismatch. Never
   logged. (See §5.)
2. Load the schedule by id; if missing/disabled/not `active`, `409` (a stale dispatch — the
   schedule changed between tick and call) — recorded, not an error.
3. **Re-run the guardrails server-side** (defense in depth — the tick checked them, but the
   state may have changed): overlap (G1), open-PR (G5), concurrency cap (G4). If blocked,
   write the block state and return `200 {skipped: true, reason}` (the dispatch was correct;
   the skip is a valid outcome, not a failure).
4. Resolve agent + repository, Ajv-validate `schedule.params` against `agents.params_schema`
   (same `validateParams` as manual invoke; a schedule whose params no longer validate — the
   agent schema changed — fails with `INVALID_PARAMS`, records a `run_failed`-style
   notification, and counts toward G3). 
5. Generate `run_id`, `buildRunInsert({ …, trigger: { triggerType:'schedule',
   triggeredBy:'schedule:'+id } })`, `insertQueuedRun`.
6. `invokeAgentRuntime(...)`. On throw → `markRunFailedToStart` + increment
   `consecutive_failures`. On success → reset `consecutive_failures = 0`, set
   `last_run_id`, `last_fired_at`.
7. Apply G3: if `consecutive_failures >= auto_pause_threshold`, flip `state='paused'`,
   `block_reason='auto_paused:consecutive_failures'`, and insert the `schedule_auto_paused`
   notification in the same transaction.
8. Return `202 { run_id }` (fired) or `200 { skipped, reason }`.

This reuses the manual route's exact normative ordering (D1 insert-then-invoke); the only
additions are the guardrail checks (before) and the G3 counter update (after). The invoke
itself is byte-identical to the manual path (same credential provider, same payload builder).

---

## 4. Guardrails

All guardrail evaluations use `effective_status` (via `v_runs`), never the raw `runs.status`
column, so a stale `running` does not block forever (SD-G0).

- **SD-G1 (overlap, FR9).** Block if any run for the **same (agent_id, repository_id)** has
  `effective_status in ('queued','running')`. Set `state='blocked'`, `block_reason='overlap'`.
  Cleared automatically on the next tick once that run is terminal (the block is re-evaluated,
  not sticky-until-manual).
- **SD-G2 (missed-tick, FR10).** No catch-up. `fire_due_schedules()` advances `next_run_at`
  to the next future occurrence from `now()` (not from the missed slot), so a gap produces at
  most the next scheduled firing. A detectably-missed slot sets `last_skipped_reason='missed_tick'`.
- **SD-G3 (circuit breaker, FR11).** `consecutive_failures` increments on a terminal-failure
  run or a fire-time error; resets to 0 on a success. At `>= auto_pause_threshold`, flip to
  `paused` + notify. Counter updates happen BOTH at the fire endpoint (invoke-time failures)
  AND in the notify-sweep (reaper-materialized terminal failures) — see SD-N3 — so a
  `timed_out` scheduled run that the panel never saw still counts.
- **SD-G4 (concurrency cap, FR12).** Global in-flight cap `K` (DB setting
  `app.scheduler_max_inflight`, default 3). Enforced in the due-tick's LIMIT and re-checked at
  the fire endpoint. Over-cap due schedules get `last_skipped_reason='concurrency_cap'` and are
  re-evaluated next tick (no backlog).
- **SD-G5 (open-PR backoff, FR13).** Block if the schedule's most-recent PR-producing run (a
  `run_artifacts` row of type `pull_request` for a run of the same (agent, repository)) is still
  **unresolved**. v1 "resolved" = a `schedules.pr_block_cleared_at` marker set by the operator's
  manual clear (G5-c) OR a later **manual** run of the same (agent, repository) created after the
  blocking run (G5-a). Set `state='blocked'`, `block_reason='open_pr'`.
  - **SD-G5a (phasing).** v1 does NOT query GitHub for PR state. The block stays until manually
    cleared or superseded. FR-FF1 (fast-follow) adds a GitHub-poll tick that auto-clears on
    merge/close; its hook is `pr_block_cleared_at` being settable by that future tick as well.
    A small `schedules.pr_block_run_id` column records which run's PR is holding the block, so the
    future poller knows which PR to check.

**Unified reason surface (SD-G6, FR14).** All four reasons flow into
`block_reason`/`last_skipped_reason`, enumerated: `overlap`, `open_pr`, `concurrency_cap`,
`missed_tick`, `auto_paused:consecutive_failures`, `invalid_params`. The UI maps each to a human
string. `blocked` (sticky `state`) ⊂ {`overlap`, `open_pr`, `auto_paused:*`}; `skipped`
(transient) ⊂ {`concurrency_cap`, `missed_tick`}.

---

## 5. Auth & Boundary (SD-A*)

- **SD-A1 (route class, FR8/FR25).** `middleware.ts` adds an `internal` route class for
  `/api/internal/**`, classified in `lib/auth/route-policy.ts` (which today returns `ui`/`api`/`public`).
  The `internal` class **bypasses the session check** but requires the shared secret, verified
  INSIDE each `/api/internal/**` handler (not in middleware — the middleware only routes the class
  and must not short-circuit to 200). The handler does a **constant-time** compare
  (`crypto.timingSafeEqual` over equal-length buffers, length-guarded) and returns `401
  {"error":"UNAUTHORIZED"}` on any failure. Fail-closed: missing env, missing header, wrong length,
  or mismatch all → 401. The secret value is never logged (the existing invoke-log discipline).
- **SD-A2 (secret storage, FR8).** `SCHEDULER_TRIGGER_SECRET` lives in `fly secrets` (panel reads
  `process.env`) and Supabase Vault (the `pg_cron` job reads via `vault.read_secret`). Rotation:
  set both, no code change. Generated as a high-entropy random string.
- **SD-A3 (human CRUD, FR25).** All `/schedules` CRUD and `/notifications` routes are ordinary
  `ui`/`api` routes behind the existing login gate — unchanged middleware behavior (302 for UI,
  401 for API). Server Actions for create/edit/pause/resume/delete follow the existing
  `app/(panel)/repositories/actions.ts` pure-core-plus-thin-action shape; the `app/**/actions.ts`
  ESLint SD2 exemption already covers them.
- **SD-A4 (release-gate assertion, FR26).** `panel/scripts/panel-auth-check.mjs` gains a pure
  `checkInternalRejected(probe)` decision function and `verify-panel-auth.sh` gains a probe: an
  unauthenticated `POST /api/internal/schedules/<nonexistent>/fire` must return `401` (not 200/404/409
  — a 404/409 would mean the handler ran past the secret check). This asserts the scheduler path is
  not an open invoke hole, exactly as the SSE-401 check does.

---

## 6. Notifications (SD-N*)

- **SD-N1 (recording sources, FR15/FR17).** Notification rows are written from two places, both
  idempotent via `uq_notifications_run_kind`:
  - the **fire endpoint** (SD-T9) for events it observes synchronously: `pr_opened` (when the invoke
    result / a later run step produces a `pull_request` artifact — see SD-N4), `run_succeeded`
    (opt-in), `schedule_auto_paused`;
  - a **notify-sweep `pg_cron` tick** (`sweep_schedule_notifications()`, `* * * * *`) for events the
    panel did not observe: scheduled runs that newly reached a terminal **failure**
    (`failed`/`failed_to_start`/`timed_out`) — including reaper-materialized ones (FR17/AC10) — and
    PR-opened for runs whose artifact appeared after the fire response. The sweep also updates
    `consecutive_failures` for reaper-materialized failures (SD-G3) and applies G3 auto-pause if the
    threshold is crossed.
- **SD-N2 (exactly-once).** `insert … on conflict (run_id, kind) do nothing`. The sweep is naturally
  idempotent and safe to run every minute.
- **SD-N3 (PR-opened detection, SD-N4).** A `pull_request` artifact is written by the agent during the
  run, not at invoke time, so `pr_opened` is detected by the sweep (a scheduled run that now has a
  `pull_request` artifact and no `pr_opened` notification yet), not synchronously at the fire endpoint.
  This also sets `schedules.pr_block_run_id` + flips `state='blocked'`/`block_reason='open_pr'` (SD-G5).
- **SD-N5 (panel feed, FR18).** New `/notifications` route (and a top-bar bell with an unread badge).
  Server component reads `notifications` newest-first via a new `getNotifications`/`getUnreadCount`
  query (SD2, service-role, RLS deny-all). Mark-as-read is a Server Action setting `read_at`
  (single or all). Inline route-segment config (dynamic/no-store), per §12.
- **SD-N6 (daily digest, FR19).** A daily `pg_cron` job (`select cron.schedule(
  'scheduler-daily-digest', '<minute> <hour> * * *', …)`) at the configured local hour calls
  `POST /api/internal/notifications/digest` via `pg_net` (same secret). The digest endpoint:
  selects `notifications where emailed_at is null`; if empty, returns `204` and **sends nothing**
  (FR19 empty-window); else renders a plain-text + minimal-HTML email grouping by kind, sends via SES
  (SD-N7), and on **confirmed** send sets `emailed_at = now()` for exactly those rows (SD-N8 — set only
  after SES accepts, so a send failure retries next day rather than dropping, R-S9).
  - **SD-N6a (digest schedule timezone).** The daily job's cron hour is stored in UTC (converted from
    the operator's configured local digest hour at config time); because the digest hour is a single
    operator setting (not per-schedule) and DST shifts it by at most an hour, a static UTC cron is
    acceptable here (unlike per-schedule firing, SD-T3) — documented trade-off, revisit if it matters.
- **SD-N7 (SES sender, FR19/FR21).** New `panel/lib/aws/ses.ts` reusing `lib/aws/credentials.ts`
  (the same Fly OIDC → STS provider, no static keys) and `@aws-sdk/client-ses` (`SendEmailCommand`).
  Sender = `NOTIFICATION_SENDER` (SES-verified identity), recipient = `NOTIFICATION_RECIPIENT`, both
  from `fly secrets`. Errors classified like `lib/aws/errors.ts` (`SES_SEND_FAILED`), never leaking
  content/credentials. IAM: the panel role gains `ses:SendEmail`/`ses:SendRawEmail` scoped to the
  verified sender ARN, never `*` (SD-X2).
- **SD-N8 (channel-agnostic, FR20).** Recording (the table + the sweep) knows nothing about email.
  The digest endpoint is one consumer; the panel feed is another; a future Slack consumer (FR-FF2)
  reads the same table with its own delivery marker column (added then), with zero change to recording.

---

## 7. UI (SD-UI-*) — FINAL, pinned to DESIGN.md

> **Locked to the delivered prototype** (`docs/prototype/Agent Scheduler.dc.html`,
> reviewed 2026-10-13) and the pixel-accurate screen specs added to `DESIGN.md`
> (**§5.7 Schedules** + §5.7.1 agent indicator + §5.7.2 new/edit dialog + §5.7.3 delete
> confirm, **§5.8 Notifications**, the §4.1 nav-state update, the §10 icons). Each UI
> story in Phase 3 MUST reference its DESIGN.md section as the pixel contract. No new
> visual token or component variant — every surface reuses existing primitives.

- **SD-UI-1 — `/schedules` list (FR22) → DESIGN.md §5.7.** Sidebar `Schedules`
  `DisabledNavItem` → live `NavItem` (`CalendarDots`). Semantic-table-on-grid, columns
  State / Agent / Repository / Cadence / Next run / Last run / Actions (grid
  `100px minmax(150px,1.1fr) minmax(170px,1.25fr) minmax(150px,1.1fr) 120px 136px 184px`,
  min-width 1080px). Unified blocked/skipped reason row (SD-G6) with the `open_pr`
  "PR handled · resume anyway" ghost clear (G5-c). Create/edit/pause/resume/delete via
  Server Actions (SD-A3). Server-read, SD2, RLS deny-all.
- **SD-UI-2 — New/Edit dialog (FR24) → DESIGN.md §5.7.2.** Reuses the §5.4 Invoke dialog
  shell + the schema-driven `fieldrow` form + `validateParams`, adds the cadence
  segmented control (kind → kind-specific fields), the timezone select (default
  `America/Santiago`), the live summary + next-3-runs **Preview** card (sourced from the
  SD-T6 authoritative DB RPC, not a TS reimpl), and the collapsible guardrails
  disclosure (auto_pause_threshold default 3, notify_on_success default off; G1/G5 shown
  as always-on read-only lines). Params validated against `params_schema` at save
  (AC13). Delete confirm = §5.7.3 `alertdialog`.
- **SD-UI-3 — Notifications feed + bell (FR18) → DESIGN.md §5.8.** Top-bar `Bell` + unread
  badge + popover (5 newest), and the full `/notifications` grouped feed (kind-colored
  dot, unread edge/weight treatment, untrusted detail as text only, run/schedule/PR
  links, relative time), mark-(all)-read Server Action, the daily-digest footer note.
  Server-read, SD2, RLS deny-all, inline route-segment config.
- **SD-UI-4 — Agent-page indicator (FR23) → DESIGN.md §5.7.1.** Read-only `N schedules`
  pointer on `/agents/[slug]` linking to `/schedules?agent=<slug>` (which renders the
  header filter chip). No CRUD on the agent page.
- **SD-UI-5 — DESIGN.md impact: DONE.** §5.7/§5.8 screen specs, §4.1 nav-state, §10 icons
  authored from the prototype (DESIGN.md v1.11). The prototype is committed at
  `docs/prototype/Agent Scheduler.dc.html` (same `_ds` bundle hash as every other
  screen — zero DS divergence).

---

## 8. Testing Strategy (SD-X3)

Mirrors the reaper's integration-test precedent (`panel/tests/integration/reaper.test.ts`) and the
project's layer taxonomy (`TESTING.md`).

- **Layer 1 (unit, pure):** `buildRunInsert` trigger descriptor (manual byte-identical + schedule
  shape); the cadence TS types/validators (cron grammar accept/reject, kind-field completeness); the
  auth constant-time compare decision (`panel-auth-check.mjs` `checkInternalRejected`); the SES error
  classifier; the notification title/detail builders (untrusted detail → text only).
- **Layer 2 (component):** the `/schedules` table, the cadence picker (kind switching, live summary,
  next-3 preview rendering), the notifications feed, the confirm-delete dialog, the bell/unread badge.
- **Layer 2.5 (integration, live local Supabase — Docker-gated, `REQUIRE_LOCAL_DB=1`):** the three
  `pg_cron` functions against a real DB —
  - `compute_next_run_at` across each kind **and across a DST boundary** (AC1) using a fixed clock;
  - `fire_due_schedules` guardrail matrix: overlap block (SD-G1), concurrency cap skip (SD-G4),
    missed-tick no-catch-up (SD-G2), open-PR block + manual clear (SD-G5);
  - G3 counter increment/reset + auto-pause transition writing exactly one notification;
  - `sweep_schedule_notifications` recording a reaper-materialized `timed_out` as exactly one
    `run_failed` notification (AC10) and incrementing `consecutive_failures`;
  - the digest selection + `emailed_at` exactly-once marking (SES mocked at the SDK boundary);
  - the unique-constraint idempotency of the sweep (re-run → no duplicate rows).
- **E2E (Playwright):** create a schedule through the dialog for each agent (schema-driven form,
  AC13); pause/resume/delete; the fire endpoint rejects an unauthenticated/wrong-secret call (AC3,
  mirrors the auth-gate E2E); the notifications feed renders + marks read (AC11). The actual `pg_cron`
  firing is exercised at Layer 2.5 (deterministic clock) rather than E2E (wall-clock minute waits are
  not E2E-friendly).
- **Release gate:** the `/api/internal/**`-rejects-unauthenticated assertion (SD-A4) added to
  `panel-auth-check.mjs` + `verify-panel-auth.sh`, run against the deployed host.

---

## 9. Migrations & Deploy Touchpoints (SD-X4)

- **New migrations** (timestamped, in `supabase/migrations/`): (a) `schedules` + `notifications`
  tables, enums, indexes, RLS; (b) `compute_next_run_at`, `fire_due_schedules`,
  `sweep_schedule_notifications` functions; (c) the three `cron.schedule(...)` registrations
  (`fire-due-schedules`, `scheduler-notify-sweep`, `scheduler-daily-digest`) + `create extension if
  not exists pg_net` + Vault secret bootstrap note.
- **Extensions:** enable `pg_net` and **Supabase Vault** in the dashboard (privileged, like `pg_cron`
  for the reaper) — documented in the runbook.
- **Secrets:** `SCHEDULER_TRIGGER_SECRET` (fly + Vault), `NOTIFICATION_SENDER`,
  `NOTIFICATION_RECIPIENT` (fly). DB settings: `app.panel_base_url`, `app.scheduler_max_inflight`.
- **IAM:** panel role gains `ses:SendEmail`/`ses:SendRawEmail` on the verified sender identity.
- **Dependency:** `@aws-sdk/client-ses` pinned in `panel/package.json`, audit-clean, `@smithy/core`
  dedup preserved.
- **Runbook (required same-PR, AGENTS.md FR-49a):** enabling `pg_net`+Vault, SES sender verification,
  setting secrets/settings, and the scheduler/digest live-verification procedure (mirrors
  `issue-94-reaper-verification.md`).

---

## 10. Open Questions (carried from PRD / new HOW-level)

- **OQ-S1 (from PRD OQ1).** G4 cap (default 3) and G3 threshold (default 3) — DB setting /
  per-schedule column respectively; tune after real volume.
- **OQ-S2 (SD-T5 cron timezone).** `advanced` cron is interpreted in the schedule timezone via a
  plpgsql matcher. Confirm this is desired over UTC-cron (the preset kinds are unambiguously local;
  making advanced-cron also local is the consistent choice, but a power user pasting a cron may expect
  UTC). **Flagged for confirmation during stories/implementation.**
- **OQ-S3 (SD-T6 cadence-math location).** The cadence math is authoritative in plpgsql, called from
  the panel via RPC for the preview — avoiding a TS/SQL double-implementation that could drift. Confirm
  the RPC round-trip for the live preview is acceptable (vs. a TS mirror pinned by a parity test, the
  `effectiveStatus`/`v_runs` precedent). Recommended: RPC (single source of truth).
- **OQ-S4 (notifications retention, PRD OQ4).** Unbounded growth like `run_events` (R3); no v1 policy.
- **OQ-UI (prototype lock-in).** §7 UI specifics finalize after the Claude Design prototype → DESIGN.md.

---

## 11. Requirement → Decision Traceability

| PRD FR | Spec decision(s) |
| --- | --- |
| FR1 schedules table | SD-S1 |
| FR2 structured cadence | SD-S1 (cadence_*), SD-T1/T3 |
| FR3 timezone + DST | SD-S1 (timezone), SD-T3, SD-T5 |
| FR4 `* * * * *` due-tick | SD-T2 |
| FR5 pg_net → internal endpoint | SD-T2/T4 |
| FR6 reuse invoke path | SD-T9, SD-X1 |
| FR7 trigger_type/triggered_by | SD-X1 |
| FR8 shared-secret internal class | SD-A1/A2 |
| FR9 G1 overlap | SD-G1 |
| FR10 G2 missed-tick | SD-G2 |
| FR11 G3 circuit breaker | SD-G3, SD-N1 |
| FR12 G4 concurrency cap | SD-G4 |
| FR13 G5 open-PR backoff | SD-G5/G5a, SD-N3 |
| FR14 unified blocked/skipped | SD-G6, SD-S1 |
| FR15 notifications table | SD-N1 |
| FR16 notable event set | SD-N1, SD-S (notify_on_success) |
| FR17 durable + exactly-once | SD-N1/N2, sweep |
| FR18 panel feed | SD-N5, SD-UI-3 |
| FR19 daily digest | SD-N6/N6a/N7/N8 |
| FR20 channel-agnostic | SD-N8 |
| FR21 sender/recipient config | SD-N7 |
| FR22 /schedules CRUD | SD-UI-1, SD-A3 |
| FR23 agent indicator | SD-UI-4 |
| FR24 schema-driven form | SD-UI-2 |
| FR25 auth split | SD-A1/A3 |
| FR26 release-gate assertion | SD-A4 |
