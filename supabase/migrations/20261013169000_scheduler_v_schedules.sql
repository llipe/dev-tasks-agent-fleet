-- =====================================================================
-- Agent Fleet -- Phase 4 Agent Scheduler: v_schedules read view (S-161, #273)
--
-- The panel's /schedules list reads through this view (never the raw table),
-- mirroring the v_runs posture (SD4): the joined display columns the table needs
-- (agent name/slug, repository full_name/default_branch, and the last produced
-- run's effective_status + outcome + finished_at) are always present in one
-- read, so the server component does no N+1 follow-up queries.
--
-- last_run_* comes from the schedule's last_run_id (pinned by recordScheduleFired)
-- resolved through v_runs so effective_status is reaper-correct. A schedule with
-- no last run (never fired, or its run was deleted -> on delete set null) yields
-- nulls, which the UI renders as the em-dash / "no runs yet" state.
--
-- Read-only; RLS on the base tables still governs access (service-role only,
-- deny-all for anon -- the view inherits the base-table policy via
-- security_invoker).
-- =====================================================================

create or replace view v_schedules
with (security_invoker = true)
as
select
  s.*,
  a.name       as agent_name,
  a.slug       as agent_slug,
  a.is_enabled as agent_is_enabled,
  r.full_name      as repository_full_name,
  r.default_branch as repository_default_branch,
  lr.effective_status as last_run_status,
  lr.outcome          as last_run_outcome,
  lr.finished_at      as last_run_finished_at
from schedules s
join agents a on a.id = s.agent_id
left join repositories r on r.id = s.repository_id
left join v_runs lr on lr.id = s.last_run_id;

comment on view v_schedules is
  'Phase 4 (S-161): schedules + joined agent/repository display columns + the '
  'last produced run''s effective_status/outcome/finished_at, for the /schedules '
  'list read path (mirrors v_runs, SD4). security_invoker so base-table RLS applies.';
