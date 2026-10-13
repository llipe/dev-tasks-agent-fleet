-- =====================================================================
-- Agent Fleet -- Phase 4 Agent Scheduler: daily digest cron (S-159, #271)
--
-- A once-a-day pg_cron job (`scheduler-daily-digest`) that POSTs
-- /api/internal/notifications/digest via pg_net (same shared secret as the fire
-- endpoint). The endpoint selects notifications where emailed_at is null, 204s
-- on an empty window (sends nothing, SD-N7), else renders + sends via SES and
-- marks emailed_at only on a confirmed send (SD-N8).
--
-- SD-N6a (digest schedule timezone): the digest hour is a SINGLE operator
-- setting (not per-schedule), and DST shifts it by at most an hour, so a STATIC
-- UTC cron is acceptable here (unlike per-schedule firing, SD-T3). The job's UTC
-- hour is computed ONCE from the configured local hour + timezone at migration
-- time; the operator re-runs scheduler.schedule_daily_digest(...) if they change
-- the hour or want to correct for a DST boundary (documented in the runbook).
-- =====================================================================

-- Default digest config: 08:00 in the scheduler's default timezone. The
-- operator overrides via scheduler.config + a re-run of the register helper.
insert into scheduler.config (key, value) values
  ('digest_local_hour',   '8'),
  ('digest_local_minute', '0'),
  ('digest_timezone',     'America/Santiago')
on conflict (key) do nothing;

-- ---------------------------------------------------------------------
-- scheduler.schedule_daily_digest()
--   (Re)registers the scheduler-daily-digest cron job at the UTC time that
--   corresponds to the configured local digest hour TODAY. Converts via
--   `at time zone` against a concrete date so DST is applied correctly at
--   register time (SD-N6a static-UTC trade-off). Idempotent.
-- ---------------------------------------------------------------------
create or replace function scheduler.schedule_daily_digest()
returns text
language plpgsql
security definer
set search_path = public, scheduler
as $$
declare
  v_hour   integer := coalesce(nullif(scheduler.get_setting('digest_local_hour'), ''), '8')::integer;
  v_minute integer := coalesce(nullif(scheduler.get_setting('digest_local_minute'), ''), '0')::integer;
  v_tz     text    := coalesce(nullif(scheduler.get_setting('digest_timezone'), ''), 'America/Santiago');
  v_local  timestamptz;
  v_utc    timestamptz;
  v_cron   text;
begin
  -- Build "today at HH:MM local" in the configured zone, then read its UTC
  -- wall-clock parts. `make_timestamp ... at time zone <tz>` interprets the
  -- naive timestamp AS being in v_tz and yields the correct timestamptz.
  v_local := (make_timestamp(
                extract(year  from now() at time zone v_tz)::int,
                extract(month from now() at time zone v_tz)::int,
                extract(day   from now() at time zone v_tz)::int,
                v_hour, v_minute, 0) at time zone v_tz);
  v_utc := v_local;

  v_cron := format('%s %s * * *',
                   extract(minute from v_utc at time zone 'UTC')::int,
                   extract(hour   from v_utc at time zone 'UTC')::int);

  if exists (select 1 from cron.job where jobname = 'scheduler-daily-digest') then
    perform cron.unschedule('scheduler-daily-digest');
  end if;

  perform cron.schedule(
    'scheduler-daily-digest',
    v_cron,
    $job$
      select net.http_post(
        url     := scheduler.get_setting('panel_base_url') || '/api/internal/notifications/digest',
        headers := jsonb_build_object('Content-Type', 'application/json',
                                      'X-Scheduler-Secret', scheduler.read_secret('scheduler_trigger_secret')),
        body    := '{}'::jsonb,
        timeout_milliseconds := 10000
      );
    $job$
  );

  return v_cron;
end $$;

comment on function scheduler.schedule_daily_digest() is
  'Phase 4 (S-159): (re)registers scheduler-daily-digest at the UTC time for the '
  'configured local digest hour (SD-N6a static-UTC). Operator re-runs it to '
  'change the hour or correct a DST boundary.';

-- Register the job now (local hour -> static UTC).
select scheduler.schedule_daily_digest();
