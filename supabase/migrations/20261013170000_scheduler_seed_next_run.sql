-- =====================================================================
-- Agent Fleet -- Phase 4 Agent Scheduler: seed next_run_at (fix)
--
-- BUG (found in live step-6 verification): a newly created schedule has
-- next_run_at = NULL, and fire_due_schedules() only selects rows where
-- `next_run_at is not null and next_run_at <= now()`. So the tick never fires a
-- null-cursor row AND never advances it -- a brand-new schedule never fires.
-- The create path (insertSchedule) never seeded the cursor, and updateSchedule
-- deliberately nulls it "for the tick to recompute" -- but the tick cannot
-- bootstrap a null.
--
-- FIX: a BEFORE INSERT OR UPDATE trigger seeds next_run_at from the cadence
-- fields whenever it is NULL on an enabled, active schedule. Correct regardless
-- of the write path (panel create/edit, direct insert, resume). The tick still
-- OWNS the cursor after firing; this only bootstraps the initial value (and
-- re-seeds after an edit nulls it). pause/resume: a paused row is left null
-- (not due); resuming to 'active' re-seeds on the UPDATE.
-- =====================================================================

create or replace function scheduler.seed_next_run_at()
returns trigger
language plpgsql
security definer
set search_path = public, scheduler
as $$
begin
  -- Only seed when there is no cursor and the schedule is eligible to fire.
  -- Guard the cadence domain FIRST: a BEFORE trigger runs ahead of the
  -- chk_schedule_cadence CHECK, so an invalid row (e.g. every_n_hours with
  -- interval < 1) would otherwise reach compute_next_run_at and loop forever.
  -- When the cadence is out of domain we leave next_run_at null and let the
  -- CHECK reject the row (R-S: never hang on bad input).
  if new.next_run_at is null and new.is_enabled and new.state = 'active'
     and (
          (new.cadence_kind = 'hourly'
             and new.cadence_minute between 0 and 59)
       or (new.cadence_kind = 'daily'
             and new.cadence_minute between 0 and 59
             and new.cadence_hour between 0 and 23)
       or (new.cadence_kind = 'weekly'
             and new.cadence_minute between 0 and 59
             and new.cadence_hour between 0 and 23
             and new.cadence_weekday between 0 and 6)
       or (new.cadence_kind = 'every_n_hours'
             and coalesce(new.cadence_interval_hours, 0) >= 1)
       or (new.cadence_kind = 'advanced'
             and new.cadence_cron is not null
             and length(trim(new.cadence_cron)) > 0)
     )
  then
    new.next_run_at := scheduler.compute_next_run_at(
      new.cadence_kind,
      new.cadence_minute,
      new.cadence_hour,
      new.cadence_weekday,
      new.cadence_interval_hours,
      new.cadence_cron,
      new.timezone,
      now(),
      new.last_fired_at
    );
  end if;
  return new;
end $$;

drop trigger if exists trg_schedules_seed_next_run on schedules;
create trigger trg_schedules_seed_next_run
  before insert or update on schedules
  for each row execute function scheduler.seed_next_run_at();

-- One-time backfill for rows created before this trigger existed (the live
-- step-6 schedules). A no-op touch fires the trigger, which seeds the cursor.
update schedules
   set updated_at = now()
 where next_run_at is null and is_enabled and state = 'active';
