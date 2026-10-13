-- =====================================================================
-- Agent Fleet -- Phase 4 Agent Scheduler: compute_next_run_at + cron matcher
-- Story S-152 (#264). The authoritative cadence math (SD-T1/T3/T5/T6). All
-- computation is done in the schedule's timezone and returned as a UTC
-- timestamptz, so wall-clock presets fire correctly across DST (AC1). Advanced
-- cron is interpreted in the schedule timezone too (OQ-S2 resolved:
-- schedule-tz, consistent with the presets). Pure/read-only -- no firing.
-- =====================================================================

-- ---------------------------------------------------------------------
-- scheduler.cron_field_matches(spec, value, lo, hi)
--   A closed cron-field grammar matcher: `*`, a number, a comma-list, a range
--   `a-b`, and a step `*/n` or `a-b/n`. Returns null on an UNPARSEABLE field so
--   the caller can distinguish "no match" from "invalid expression". Any token
--   outside the grammar or outside [lo,hi] yields null.
-- ---------------------------------------------------------------------
create or replace function scheduler.cron_field_matches(
  p_spec text, p_value integer, p_lo integer, p_hi integer
) returns boolean
language plpgsql
immutable
as $$
declare
  v_part   text;
  v_lo     integer;
  v_hi     integer;
  v_step   integer;
  v_m      text[];
begin
  if p_spec is null then
    return null;
  end if;

  foreach v_part in array string_to_array(p_spec, ',')
  loop
    v_part := btrim(v_part);
    -- forms: *            | */n
    --        a            | a/n
    --        a-b          | a-b/n
    v_m := regexp_match(v_part, '^(\*|\d+(?:-\d+)?)(?:/(\d+))?$');
    if v_m is null then
      return null; -- unparseable field
    end if;

    v_step := coalesce(nullif(v_m[2], '')::integer, 1);
    if v_step < 1 then
      return null;
    end if;

    if v_m[1] = '*' then
      v_lo := p_lo;
      v_hi := p_hi;
    elsif position('-' in v_m[1]) > 0 then
      v_lo := split_part(v_m[1], '-', 1)::integer;
      v_hi := split_part(v_m[1], '-', 2)::integer;
    else
      v_lo := v_m[1]::integer;
      -- a bare number with a step means "from a to hi step n"; without a step it is exact
      v_hi := case when nullif(v_m[2], '') is not null then p_hi else v_lo end;
    end if;

    if v_lo < p_lo or v_hi > p_hi or v_lo > v_hi then
      return null; -- out of range / inverted
    end if;

    if p_value >= v_lo and p_value <= v_hi and ((p_value - v_lo) % v_step) = 0 then
      return true;
    end if;
  end loop;

  return false;
end $$;

-- ---------------------------------------------------------------------
-- scheduler.cron_matches(cron, local_ts)
--   Standard 5-field semantics (minute hour day-of-month month day-of-week),
--   dow 0 and 7 both = Sunday, and the day-of-month/day-of-week OR rule when
--   both are restricted. Returns null if any field is unparseable (invalid
--   expression). local_ts is a naive local timestamp (already in the schedule's
--   tz).
-- ---------------------------------------------------------------------
create or replace function scheduler.cron_matches(p_cron text, p_local timestamp)
returns boolean
language plpgsql
immutable
as $$
declare
  f        text[];
  m_min    boolean;
  m_hour   boolean;
  m_dom    boolean;
  m_mon    boolean;
  m_dow    boolean;
  dom_star boolean;
  dow_star boolean;
  dow_val  integer;
begin
  f := regexp_split_to_array(btrim(p_cron), '\s+');
  if array_length(f, 1) is distinct from 5 then
    return null;
  end if;

  dom_star := btrim(f[3]) = '*';
  dow_star := btrim(f[5]) = '*';
  dow_val  := extract(dow from p_local)::integer; -- 0=Sun..6=Sat

  m_min  := scheduler.cron_field_matches(f[1], extract(minute from p_local)::integer, 0, 59);
  m_hour := scheduler.cron_field_matches(f[2], extract(hour   from p_local)::integer, 0, 23);
  m_dom  := scheduler.cron_field_matches(f[3], extract(day    from p_local)::integer, 1, 31);
  m_mon  := scheduler.cron_field_matches(f[4], extract(month  from p_local)::integer, 1, 12);
  -- dow: accept 0 and 7 as Sunday by matching against both when 7 is in-spec.
  m_dow  := scheduler.cron_field_matches(f[5], dow_val, 0, 7)
            or (dow_val = 0 and scheduler.cron_field_matches(f[5], 7, 0, 7));

  if m_min is null or m_hour is null or m_dom is null or m_mon is null or m_dow is null then
    return null; -- invalid expression
  end if;

  if not (m_min and m_hour and m_mon) then
    return false;
  end if;

  -- day-of-month / day-of-week OR rule (cron standard)
  if dom_star and dow_star then
    return true;
  elsif dom_star then
    return m_dow;
  elsif dow_star then
    return m_dom;
  else
    return m_dom or m_dow;
  end if;
end $$;

-- ---------------------------------------------------------------------
-- scheduler.compute_next_run_at(schedule_row, from_ts)
--   The next firing instant strictly AFTER from_ts, as a UTC timestamptz.
--   Evaluated in the schedule's timezone so a "daily 07:00" fires at 07:00
--   local on both sides of a DST change (the UTC instant shifts -- AC1).
--   Returns null when a cadence cannot produce a future time within a bounded
--   lookahead (e.g. an impossible/empty advanced cron) -- the caller treats a
--   null next_run_at as "do not fire" and surfaces it.
--
--   Overloaded on the concrete column set it needs (kept narrow so it can be
--   called with a schedules row OR with explicit args from a test/RPC).
-- ---------------------------------------------------------------------
create or replace function scheduler.compute_next_run_at(
  p_kind            cadence_kind,
  p_minute          integer,
  p_hour            integer,
  p_weekday         integer,
  p_interval_hours  integer,
  p_cron            text,
  p_timezone        text,
  p_from            timestamptz,
  p_last_fired_at   timestamptz default null
) returns timestamptz
language plpgsql
stable
as $$
declare
  v_local    timestamp;        -- naive local time of the from_ts
  v_cand     timestamp;        -- candidate naive local firing time
  v_i        integer;
begin
  -- from_ts expressed in the schedule's local wall clock
  v_local := p_from at time zone p_timezone;

  if p_kind = 'hourly' then
    -- next time minute = p_minute, strictly after from
    v_cand := date_trunc('hour', v_local) + make_interval(mins => p_minute);
    if v_cand <= v_local then
      v_cand := v_cand + interval '1 hour';
    end if;
    return v_cand at time zone p_timezone;

  elsif p_kind = 'daily' then
    v_cand := date_trunc('day', v_local) + make_interval(hours => p_hour, mins => p_minute);
    if v_cand <= v_local then
      v_cand := v_cand + interval '1 day';
    end if;
    return v_cand at time zone p_timezone;

  elsif p_kind = 'weekly' then
    -- advance day-by-day up to 7 days to the target weekday at the target time
    for v_i in 0..7 loop
      v_cand := date_trunc('day', v_local) + make_interval(days => v_i, hours => p_hour, mins => p_minute);
      if extract(dow from v_cand)::integer = p_weekday and v_cand > v_local then
        return v_cand at time zone p_timezone;
      end if;
    end loop;
    return null; -- unreachable for a valid weekday

  elsif p_kind = 'every_n_hours' then
    -- chain from last_fired_at when present, else from the from_ts; align to the
    -- next interval boundary strictly after from.
    v_cand := coalesce(p_last_fired_at, p_from) at time zone p_timezone;
    while v_cand <= v_local loop
      v_cand := v_cand + make_interval(hours => p_interval_hours);
    end loop;
    return v_cand at time zone p_timezone;

  elsif p_kind = 'advanced' then
    -- Walk forward in LOCAL time to the next cron match. To stay fast for
    -- sparse expressions (e.g. '0 0 29 2 *' -- next match up to ~2 years away),
    -- fast-forward by the coarsest non-matching unit instead of pure
    -- minute-stepping: skip whole months when the month field cannot match,
    -- whole days when the day fields cannot match, whole hours when the hour
    -- cannot match, and only then step minutes. Bounded to ~5 years of lookahead.
    declare
      f          text[];
      v_deadline timestamp;
      v_mon_ok   boolean;
      v_day_ok   boolean;
      v_hour_ok  boolean;
      v_min_ok   boolean;
      dom_star   boolean;
      dow_star   boolean;
      v_dow      integer;
    begin
      f := regexp_split_to_array(btrim(p_cron), '\s+');
      if array_length(f, 1) is distinct from 5 then
        return null; -- invalid: wrong arity
      end if;
      -- Validate every field once up front against a probe value so an invalid
      -- expression returns null immediately rather than after a full scan.
      if scheduler.cron_field_matches(f[1], 0, 0, 59) is null
         or scheduler.cron_field_matches(f[2], 0, 0, 23) is null
         or scheduler.cron_field_matches(f[3], 1, 1, 31) is null
         or scheduler.cron_field_matches(f[4], 1, 1, 12) is null
         or scheduler.cron_field_matches(f[5], 0, 0, 7) is null then
        return null;
      end if;

      dom_star := btrim(f[3]) = '*';
      dow_star := btrim(f[5]) = '*';
      v_cand := date_trunc('minute', v_local) + interval '1 minute';
      v_deadline := v_local + interval '5 years';

      while v_cand <= v_deadline loop
        v_mon_ok := scheduler.cron_field_matches(f[4], extract(month from v_cand)::integer, 1, 12);
        if not v_mon_ok then
          -- jump to the first day of next month at 00:00
          v_cand := date_trunc('month', v_cand) + interval '1 month';
          continue;
        end if;

        -- day-of-month / day-of-week OR rule
        v_dow := extract(dow from v_cand)::integer;
        v_day_ok := case
          when dom_star and dow_star then true
          when dom_star then (scheduler.cron_field_matches(f[5], v_dow, 0, 7)
                              or (v_dow = 0 and scheduler.cron_field_matches(f[5], 7, 0, 7)))
          when dow_star then scheduler.cron_field_matches(f[3], extract(day from v_cand)::integer, 1, 31)
          else (scheduler.cron_field_matches(f[3], extract(day from v_cand)::integer, 1, 31)
                or scheduler.cron_field_matches(f[5], v_dow, 0, 7)
                or (v_dow = 0 and scheduler.cron_field_matches(f[5], 7, 0, 7)))
        end;
        if not v_day_ok then
          v_cand := date_trunc('day', v_cand) + interval '1 day';
          continue;
        end if;

        v_hour_ok := scheduler.cron_field_matches(f[2], extract(hour from v_cand)::integer, 0, 23);
        if not v_hour_ok then
          v_cand := date_trunc('hour', v_cand) + interval '1 hour';
          continue;
        end if;

        v_min_ok := scheduler.cron_field_matches(f[1], extract(minute from v_cand)::integer, 0, 59);
        if v_min_ok then
          return v_cand at time zone p_timezone;
        end if;
        v_cand := v_cand + interval '1 minute';
      end loop;
      return null; -- no match within the lookahead window
    end;
  end if;

  return null;
end $$;

-- Convenience overload taking a schedules row id (used by the fire path /
-- cursor advance in S-154). Reads the row and delegates.
create or replace function scheduler.compute_next_run_at(p_schedule_id uuid, p_from timestamptz)
returns timestamptz
language sql
stable
as $$
  select scheduler.compute_next_run_at(
           s.cadence_kind, s.cadence_minute, s.cadence_hour, s.cadence_weekday,
           s.cadence_interval_hours, s.cadence_cron, s.timezone, p_from, s.last_fired_at)
    from schedules s
   where s.id = p_schedule_id
$$;

-- ---------------------------------------------------------------------
-- RPC: next N firing instants from a cadence spec (SD-T6). The panel dialog
-- calls this for the live summary + "next 3 runs" preview, so there is ONE
-- implementation of the cadence math (no TS reimplementation that can drift).
-- Returns an ordered set of UTC timestamptz; empty when the cadence yields no
-- future time (invalid cron / impossible spec).
-- ---------------------------------------------------------------------
create or replace function scheduler.preview_next_runs(
  p_kind            cadence_kind,
  p_minute          integer,
  p_hour            integer,
  p_weekday         integer,
  p_interval_hours  integer,
  p_cron            text,
  p_timezone        text,
  p_count           integer default 3,
  p_from            timestamptz default now()
) returns setof timestamptz
language plpgsql
stable
as $$
declare
  v_from  timestamptz := p_from;
  v_next  timestamptz;
  v_i     integer;
begin
  for v_i in 1..greatest(p_count, 0) loop
    v_next := scheduler.compute_next_run_at(
                p_kind, p_minute, p_hour, p_weekday, p_interval_hours,
                p_cron, p_timezone, v_from, v_from);
    exit when v_next is null;
    return next v_next;
    v_from := v_next; -- chain
  end loop;
  return;
end $$;
