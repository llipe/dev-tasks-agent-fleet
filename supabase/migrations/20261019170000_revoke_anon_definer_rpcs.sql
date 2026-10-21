-- =====================================================================
-- Agent Fleet -- issue #357: lock down public SECURITY DEFINER functions
--
-- Postgres grants EXECUTE to PUBLIC on every new function, and none of the
-- migrations that created these three revoked it. Supabase exposes `public`
-- functions through PostgREST (/rest/v1/rpc/<name>), and SECURITY DEFINER runs
-- as the owner (bypassing RLS), so anyone holding the publishable (anon) key
-- could:
--   - scheduler_record_fire_failure: count failures against a schedule and,
--     after auto_pause_threshold calls, auto-pause it (+ write a notification);
--   - reap_stale_runs: run the reaper on demand;
--   - scheduler_preview_next_runs: compute cadence previews (read-only).
--
-- Legitimate callers are unaffected:
--   - the panel calls scheduler_record_fire_failure / scheduler_preview_next_runs
--     server-side with the service-role key (SD2);
--   - pg_cron runs reap_stale_runs and the notify-sweep (which calls
--     scheduler_record_fire_failure) as `postgres`, the owner.
--
-- definer-grants.test.ts enumerates every SECURITY DEFINER function in
-- `public` from the catalog and fails if anon/authenticated can execute one,
-- so a future function added without these revokes is caught.
--
-- Dated before the (not yet pushed) webhook migrations so `supabase db push`
-- applies it in order.
--
-- Rollback (re-opens the hole -- don't):
--   grant execute on function <fn> to public;
-- =====================================================================

revoke execute on function public.reap_stale_runs() from public, anon, authenticated;
revoke execute on function public.scheduler_record_fire_failure(uuid, text) from public, anon, authenticated;
revoke execute on function public.scheduler_preview_next_runs(cadence_kind, integer, integer, integer, integer, text, text, integer)
  from public, anon, authenticated;

grant execute on function public.reap_stale_runs() to service_role;
grant execute on function public.scheduler_record_fire_failure(uuid, text) to service_role;
grant execute on function public.scheduler_preview_next_runs(cadence_kind, integer, integer, integer, integer, text, text, integer)
  to service_role;
