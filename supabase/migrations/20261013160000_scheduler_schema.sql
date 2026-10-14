-- =====================================================================
-- Agent Fleet -- Phase 4 Agent Scheduler: schedules + notifications
-- Story S-149 (#261). Schema foundation only -- no functions, no cron,
-- no app wiring (those land in S-152/S-154/S-158). The scheduler is inert
-- until the pg_cron jobs are registered.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------
create type schedule_state as enum ('active', 'paused', 'blocked');

create type cadence_kind as enum (
  'hourly', 'daily', 'weekly', 'every_n_hours', 'advanced'
);

create type notification_kind as enum (
  'run_failed', 'schedule_auto_paused', 'pr_opened', 'run_succeeded'
);

-- ---------------------------------------------------------------------
-- schedules
--   A schedule binds an agent + repository + validated params to a
--   recurring cadence. The structured cadence columns are the source of
--   truth (SD-T1); cron is a derived artifact except for the 'advanced'
--   escape hatch. next_run_at is the materialized due cursor (SD-T3),
--   computed by compute_next_run_at() (S-152) -- not populated here.
-- ---------------------------------------------------------------------
create table schedules (
  id                      uuid primary key default gen_random_uuid(),
  agent_id                uuid not null references agents(id) on delete cascade,
  repository_id           uuid references repositories(id) on delete cascade,
  installation_id         uuid references github_installations(id) on delete set null,

  name                    text,
  params                  jsonb not null default '{}'::jsonb,   -- validated vs params_schema at write

  -- cadence (structured source of truth, SD-T1)
  cadence_kind            cadence_kind not null,
  cadence_minute          smallint,                              -- 0..59
  cadence_hour            smallint,                              -- 0..23
  cadence_weekday         smallint,                              -- 0..6, 0 = Sunday
  cadence_interval_hours  smallint,                              -- 1..168
  cadence_cron            text,                                  -- 5-field (advanced only)
  timezone                text not null default 'America/Santiago',

  state                   schedule_state not null default 'active',
  is_enabled              boolean not null default true,         -- operator on/off, distinct from state

  -- guardrail bookkeeping
  consecutive_failures    integer not null default 0,
  auto_pause_threshold    integer not null default 3,            -- G3 (FR11), per-schedule
  block_reason            text,                                  -- unified blocked/skipped reason (FR14 / SD-G6)
  blocked_at              timestamptz,
  last_skipped_reason     text,
  last_skipped_at         timestamptz,

  -- G5 open-PR backoff hooks (set/cleared in S-156; the future auto-poll seam, FR-FF1)
  pr_block_run_id         uuid references runs(id) on delete set null,
  pr_block_cleared_at     timestamptz,

  -- notification opt-in
  notify_on_success       boolean not null default false,       -- FR16

  -- firing bookkeeping
  last_fired_at           timestamptz,
  last_run_id             uuid references runs(id) on delete set null,
  next_run_at             timestamptz,                           -- the due cursor (SD-T3)
  last_fire_error         text,                                  -- pg_net/endpoint failure (R-S2)

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
  ),
  constraint chk_schedule_auto_pause_threshold check (auto_pause_threshold >= 1)
);

-- The hot path for the due-tick (S-154): enabled, active schedules ordered by cursor.
create index idx_schedules_due    on schedules (next_run_at)
  where is_enabled and state = 'active';
create index idx_schedules_agent  on schedules (agent_id);
create index idx_schedules_repo   on schedules (repository_id);

create trigger trg_schedules_updated
  before update on schedules
  for each row execute function set_updated_at();

-- ---------------------------------------------------------------------
-- notifications
--   Channel-agnostic system of record for notable scheduled-run events
--   (SD-N1). The panel feed (S-163) and the daily SES digest (S-159) are
--   two consumers; a future Slack consumer reads the same table (FR20).
--   read_at = panel feed; emailed_at = digest delivery marker (set only on
--   a confirmed send, SD-N8).
-- ---------------------------------------------------------------------
create table notifications (
  id             uuid primary key default gen_random_uuid(),
  kind           notification_kind not null,
  schedule_id    uuid references schedules(id) on delete set null,
  agent_id       uuid references agents(id) on delete set null,
  repository_id  uuid references repositories(id) on delete set null,
  run_id         uuid references runs(id) on delete set null,

  title          text not null,
  detail         text,                                   -- reason / error_code / PR url (untrusted -> text only)
  data           jsonb not null default '{}'::jsonb,

  read_at        timestamptz,
  emailed_at     timestamptz,

  created_at     timestamptz not null default now(),

  -- Exactly-once per (run_id, kind) for run-tied events (SD-N2 / AC9). A
  -- unique index (not a table constraint) so the partial semantics are clear:
  -- rows with a null run_id (e.g. schedule_auto_paused) are NOT constrained
  -- here -- that transition is single-shot by construction (S-157).
  constraint uq_notifications_run_kind unique (run_id, kind)
);

create index idx_notifications_created     on notifications (created_at desc);
create index idx_notifications_unread      on notifications (created_at desc) where read_at is null;
create index idx_notifications_undelivered on notifications (created_at)      where emailed_at is null;

-- ---------------------------------------------------------------------
-- RLS: deny-all from creation (D11), consistent with every other table.
-- Only service_role (which bypasses RLS) reads/writes; the panel reads
-- server-side with the service-role key (SD2). The anon deny-all is proven
-- by the schema-enumerated rls-deny-all.test.ts (these tables are picked up
-- automatically).
-- ---------------------------------------------------------------------
alter table schedules     enable row level security;
alter table notifications enable row level security;
