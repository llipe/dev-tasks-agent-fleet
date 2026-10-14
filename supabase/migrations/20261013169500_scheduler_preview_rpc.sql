-- =====================================================================
-- Agent Fleet -- Phase 4 Agent Scheduler: public preview wrapper (S-162, #274)
--
-- The new/edit schedule dialog's "Next 3 runs" preview must come from the
-- AUTHORITATIVE plpgsql next-run math (SD-T6), not a TS reimplementation. That
-- lives in scheduler.preview_next_runs(...), but PostgREST only exposes the
-- `public` schema -- so this thin public wrapper lets the dialog call it via
-- the service-role .rpc() the panel already uses. Prefixed name
-- (scheduler_preview_next_runs) to keep the public surface namespaced, same
-- posture as public.scheduler_record_fire_failure (S-157).
--
-- Returns the next p_count run instants (timestamptz[]) for a candidate cadence,
-- interpreted in p_timezone (DST-correct). Returns fewer than p_count (or empty)
-- when the cadence never fires again -- the dialog renders that as "no upcoming
-- runs", a valid-but-never-matching advanced cron being the usual cause.
-- =====================================================================

create or replace function public.scheduler_preview_next_runs(
  p_kind           cadence_kind,
  p_minute         integer default null,
  p_hour           integer default null,
  p_weekday        integer default null,
  p_interval_hours integer default null,
  p_cron           text    default null,
  p_timezone       text    default 'America/Santiago',
  p_count          integer default 3
) returns timestamptz[]
language sql
stable
security definer
set search_path = public, scheduler
as $$
  select coalesce(array_agg(t order by t), '{}')
    from scheduler.preview_next_runs(
           p_kind, p_minute, p_hour, p_weekday, p_interval_hours,
           p_cron, p_timezone, greatest(least(p_count, 10), 0), now()) as t;
$$;

comment on function public.scheduler_preview_next_runs is
  'Phase 4 (S-162): public PostgREST-exposed wrapper over '
  'scheduler.preview_next_runs for the new/edit dialog''s next-runs preview (SD-T6). '
  'Returns up to p_count (capped 10) next instants for a candidate cadence.';
