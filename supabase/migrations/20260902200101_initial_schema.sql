-- =====================================================================
-- Agent Fleet — esquema base
-- Ejecutar completo en el SQL Editor de Supabase.
-- =====================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------
create type run_status as enum (
  'queued', 'running', 'succeeded', 'failed',
  'timed_out', 'failed_to_start', 'canceled'
);

create type run_outcome as enum (
  'fixed', 'partial', 'no_vulnerabilities', 'needs_review', 'not_applicable'
);

create type trigger_type as enum ('manual', 'schedule', 'webhook');
create type step_status  as enum ('pending', 'running', 'succeeded', 'failed', 'skipped');
create type log_level    as enum ('debug', 'info', 'warn', 'error');
create type artifact_type as enum ('pull_request', 'audit_report', 'diff', 'file');

-- ---------------------------------------------------------------------
-- updated_at automático
-- ---------------------------------------------------------------------
create or replace function set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

-- ---------------------------------------------------------------------
-- github_installations
-- ---------------------------------------------------------------------
create table github_installations (
  id                      uuid primary key default gen_random_uuid(),
  github_org_slug         text        not null unique,
  installation_id         bigint      not null unique,
  app_id                  bigint      not null,
  private_key_secret_arn  text,
  is_enabled              boolean     not null default true,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

create trigger trg_github_installations_updated
  before update on github_installations
  for each row execute function set_updated_at();

-- ---------------------------------------------------------------------
-- repositories
-- ---------------------------------------------------------------------
create table repositories (
  id               uuid primary key default gen_random_uuid(),
  installation_id  uuid not null references github_installations(id) on delete cascade,
  github_repo_id   bigint,
  full_name        text not null,
  default_branch   text not null default 'main',
  is_enabled       boolean not null default true,
  metadata         jsonb   not null default '{}'::jsonb,
  archived_at      timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  constraint uq_repositories_full_name unique (installation_id, full_name)
);

create index idx_repositories_enabled
  on repositories (installation_id)
  where is_enabled and archived_at is null;

create trigger trg_repositories_updated
  before update on repositories
  for each row execute function set_updated_at();

-- ---------------------------------------------------------------------
-- agents
-- ---------------------------------------------------------------------
create table agents (
  id                    uuid primary key default gen_random_uuid(),
  slug                  text not null unique,
  name                  text not null,
  description           text,
  version               text not null default '0.1.0',
  runtime_arn           text not null,
  runtime_qualifier     text not null default 'DEFAULT',
  params_schema         jsonb not null default '{"type":"object","properties":{}}'::jsonb,
  default_params        jsonb not null default '{}'::jsonb,
  requires_repository   boolean not null default true,
  -- Debe reflejar el timeout configurado en AgentCore
  max_runtime_seconds   integer not null default 900,
  grace_seconds         integer not null default 60,
  start_timeout_seconds integer not null default 300,
  is_enabled            boolean not null default true,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create trigger trg_agents_updated
  before update on agents
  for each row execute function set_updated_at();

-- ---------------------------------------------------------------------
-- runs
-- ---------------------------------------------------------------------
create table runs (
  id                     uuid primary key,          -- lo genera el front (D1)
  agent_id               uuid not null references agents(id) on delete restrict,
  agent_version          text not null,             -- snapshot
  repository_id          uuid references repositories(id) on delete set null,
  installation_id        uuid references github_installations(id) on delete set null,

  trigger_type           trigger_type not null default 'manual',
  triggered_by           text,                      -- nullable hasta que exista auth
  params                 jsonb not null default '{}'::jsonb,
  idempotency_key        text,

  session_id             text,
  runtime_invocation_id  text,

  status                 run_status not null default 'queued',
  queued_at              timestamptz not null default now(),
  started_at             timestamptz,
  finished_at            timestamptz,
  duration_ms            integer,
  last_heartbeat_at      timestamptz,

  -- snapshot de umbrales (D8)
  max_runtime_seconds    integer not null,
  grace_seconds          integer not null default 60,
  start_timeout_seconds  integer not null default 300,

  outcome                run_outcome,
  error_code             text,
  error_message          text,
  result                 jsonb not null default '{}'::jsonb,
  metrics                jsonb not null default '{}'::jsonb,

  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),

  constraint chk_runs_terminal_outcome check (
    status not in ('succeeded') or outcome is not null
  )
);

create index idx_runs_agent    on runs (agent_id, created_at desc);
create index idx_runs_repo     on runs (repository_id, created_at desc);
create index idx_runs_created  on runs (created_at desc);
create index idx_runs_active   on runs (status) where status in ('queued', 'running');
create unique index uq_runs_idempotency on runs (idempotency_key) where idempotency_key is not null;

create trigger trg_runs_updated
  before update on runs
  for each row execute function set_updated_at();

-- duration_ms derivado
create or replace function set_run_duration() returns trigger
language plpgsql as $$
begin
  if new.finished_at is not null and new.started_at is not null then
    new.duration_ms = (extract(epoch from (new.finished_at - new.started_at)) * 1000)::int;
  end if;
  return new;
end $$;

create trigger trg_runs_duration
  before insert or update on runs
  for each row execute function set_run_duration();

-- ---------------------------------------------------------------------
-- run_steps
-- ---------------------------------------------------------------------
create table run_steps (
  id            uuid primary key default gen_random_uuid(),
  run_id        uuid not null references runs(id) on delete cascade,
  seq           integer not null,
  key           text    not null,     -- checkout | npm_audit | llm_fix | test | open_pr
  title         text,
  status        step_status not null default 'pending',
  started_at    timestamptz,
  finished_at   timestamptz,
  error_message text,
  data          jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now(),
  constraint uq_run_steps_seq unique (run_id, seq)
);

create index idx_run_steps_run on run_steps (run_id, seq);

-- ---------------------------------------------------------------------
-- run_events  (el log)
-- ---------------------------------------------------------------------
create table run_events (
  id       bigint generated always as identity primary key,
  run_id   uuid not null references runs(id) on delete cascade,
  step_id  uuid references run_steps(id) on delete set null,
  seq      integer not null,           -- monótono, lo asigna el agente (D5)
  ts       timestamptz not null default now(),
  level    log_level not null default 'info',
  message  text not null,
  data     jsonb not null default '{}'::jsonb,
  constraint uq_run_events_seq unique (run_id, seq)
);

create index idx_run_events_run   on run_events (run_id, seq);
create index idx_run_events_level on run_events (run_id, level) where level in ('warn', 'error');

-- Realtime para el tail en vivo
alter publication supabase_realtime add table run_events;
alter publication supabase_realtime add table runs;

-- ---------------------------------------------------------------------
-- run_artifacts
-- ---------------------------------------------------------------------
create table run_artifacts (
  id           uuid primary key default gen_random_uuid(),
  run_id       uuid not null references runs(id) on delete cascade,
  type         artifact_type not null,
  title        text,
  url          text,
  storage_path text,
  metadata     jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now()
);

create index idx_run_artifacts_run on run_artifacts (run_id);

-- ---------------------------------------------------------------------
-- Vista con effective_status  (§6, capa 2)
-- ---------------------------------------------------------------------
create or replace view v_runs as
select
  r.*,
  a.slug  as agent_slug,
  a.name  as agent_name,
  rp.full_name as repository_full_name,
  case
    when r.status = 'running'
     and now() > r.started_at + make_interval(secs => r.max_runtime_seconds + r.grace_seconds)
      then 'timed_out'::run_status
    when r.status = 'queued'
     and now() > r.queued_at + make_interval(secs => r.start_timeout_seconds)
      then 'failed_to_start'::run_status
    else r.status
  end as effective_status
from runs r
join agents a on a.id = r.agent_id
left join repositories rp on rp.id = r.repository_id;

-- ---------------------------------------------------------------------
-- Reaper  (§6, capa 1)
-- ---------------------------------------------------------------------
create or replace function reap_stale_runs() returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_count integer := 0;
  v_run   record;
begin
  -- 1. running que superó max_runtime + grace
  for v_run in
    select id, max_runtime_seconds, grace_seconds
    from runs
    where status = 'running'
      and started_at is not null
      and now() > started_at + make_interval(secs => max_runtime_seconds + grace_seconds)
    for update skip locked
  loop
    update runs
       set status = 'timed_out',
           finished_at = now(),
           error_code = 'RUNTIME_TIMEOUT',
           error_message = format(
             'Sin reporte de término tras %s s (max_runtime %s + grace %s).',
             v_run.max_runtime_seconds + v_run.grace_seconds,
             v_run.max_runtime_seconds, v_run.grace_seconds)
     where id = v_run.id;

    insert into run_events (run_id, seq, level, message, data)
    select v_run.id,
           coalesce((select max(seq) from run_events where run_id = v_run.id), 0) + 1,
           'error',
           'El sistema marcó esta ejecución como timed_out: el agente nunca reportó término.',
           jsonb_build_object('reaped_by', 'reap_stale_runs', 'reason', 'RUNTIME_TIMEOUT');

    -- Cerrar los steps que quedaron abiertos, en simetría con la ruta de
    -- fallo del propio agente (technical-guidelines §8). No asume que existan.
    update run_steps
       set status = 'failed',
           finished_at = now(),
           error_message = 'Cerrado por reap_stale_runs: la ejecución fue marcada timed_out (RUNTIME_TIMEOUT).'
     where run_id = v_run.id
       and status in ('running', 'pending');

    v_count := v_count + 1;
  end loop;

  -- 2. queued que nunca arrancó
  for v_run in
    select id, start_timeout_seconds
    from runs
    where status = 'queued'
      and now() > queued_at + make_interval(secs => start_timeout_seconds)
    for update skip locked
  loop
    update runs
       set status = 'failed_to_start',
           finished_at = now(),
           error_code = 'START_TIMEOUT',
           error_message = format('El agente no reportó inicio tras %s s.', v_run.start_timeout_seconds)
     where id = v_run.id;

    insert into run_events (run_id, seq, level, message, data)
    select v_run.id,
           coalesce((select max(seq) from run_events where run_id = v_run.id), 0) + 1,
           'error',
           'La invocación nunca reportó inicio. Revisar el runtime en AgentCore.',
           jsonb_build_object('reaped_by', 'reap_stale_runs', 'reason', 'START_TIMEOUT');

    -- Un failed_to_start normalmente no tiene steps, pero no lo asumimos:
    -- el update es un no-op seguro (0 filas) cuando no hay steps abiertos.
    update run_steps
       set status = 'failed',
           finished_at = now(),
           error_message = 'Cerrado por reap_stale_runs: la invocación fue marcada failed_to_start (START_TIMEOUT).'
     where run_id = v_run.id
       and status in ('running', 'pending');

    v_count := v_count + 1;
  end loop;

  return v_count;
end $$;

-- Programar cada minuto.
-- Requiere habilitar pg_cron en Database > Extensions del dashboard de Supabase
-- (o ejecutar el `create extension` de abajo con privilegios suficientes).
create extension if not exists pg_cron;
select cron.schedule('reap-stale-runs', '* * * * *', $$select reap_stale_runs()$$);

-- ---------------------------------------------------------------------
-- RLS: deny-all desde el día uno (D11).
-- Sin policies, nadie lee ni escribe salvo service_role, que hace bypass.
-- Cuando entre Supabase Auth, se agregan policies acá.
-- ---------------------------------------------------------------------
alter table github_installations enable row level security;
alter table repositories         enable row level security;
alter table agents               enable row level security;
alter table runs                 enable row level security;
alter table run_steps            enable row level security;
alter table run_events           enable row level security;
alter table run_artifacts        enable row level security;
