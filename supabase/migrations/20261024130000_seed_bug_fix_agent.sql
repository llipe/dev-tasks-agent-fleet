-- =====================================================================
-- S-184 (issue #366) -- seed the `bug-fix` agent (issue mode)
--
-- Registers the bug-fix agent so the panel's manual invoke and the `/bug-fix`
-- webhook rule can start it for one issue (spec §5.1, §5.2 v2.0).
--
--   runtime_arn           S-181 deploy (infra/changes/20261023-bug-fix-runtime,
--                         agents/bug-fix/agentcore/.cli/deployed-state.json).
--   max_runtime_seconds   3600: MUST equal maxLifetime in agentcore.json.
--   grace_seconds         120.
--   start_timeout_seconds 300: queue clock (D9), not idleRuntimeSessionTimeout.
--   params_schema         spec §5.2 v2.0. `issue_number` is the only required
--                         key, and additionalProperties is false (D-93, D-102).
--   default_params        only the budgets, caps and status names, equal to the
--                         schema defaults. No label, assignee or project
--                         default (D-93). The agent applies the same defaults
--                         itself (params.py, D-82), because a webhook fire
--                         sends no defaults (Ajv useDefaults: false).
--
-- Idempotent: an upsert with the siblings' `on conflict (slug) do update`
-- shape. Re-applying it keeps one row and restores every field.
-- supabase/seed.sql mirrors this row, so `db reset` and the cloud converge.
--
-- Apply: needs explicit user confirmation for any shared or cloud project.
-- Verify:
--   select slug, requires_repository, params_schema->'required'
--     from agents where slug = 'bug-fix';
--   -- expect: bug-fix | t | ["issue_number"]
--
-- Rollback (no run may reference the row: runs.agent_id is ON DELETE RESTRICT):
--   delete from agents where slug = 'bug-fix';
-- Warning: the delete CASCADES to the agent's webhook_rules and schedules
-- rows, so it would silently remove the `/bug-fix` rule (S-197). Export them
-- first (docs/runbooks/bug-fix-agent.md, "Seed row").
-- =====================================================================

insert into agents (
  slug, name, description, version,
  runtime_arn, runtime_qualifier,
  requires_repository, max_runtime_seconds, grace_seconds, start_timeout_seconds,
  default_params, params_schema
)
values (
  'bug-fix',
  'Bug Fix',
  'Fixes one GitHub issue on request: runs headless Claude Code in a sandbox, keeps the repository''s gates green, and opens a Draft PR or explains why it could not.',
  '0.1.0',
  -- runtime_arn: reported by `agentcore status` after the S-181 deploy.
  'arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/bugfix_bug_fix-BiuPsdGSPK',
  'DEFAULT',
  true,
  3600,  -- max_runtime_seconds: MUST equal maxLifetime in agentcore.json
  120,   -- grace_seconds
  300,   -- start_timeout_seconds: queue clock (D9), NOT idleRuntimeSessionTimeout
  '{"status_in_progress":"In progress","status_in_review":"In review","status_ready":"Ready","max_turns":40,"cli_timeout_minutes":30,"run_budget_minutes":55,"max_code_files":10,"max_code_lines":400}'::jsonb,
  $json${
    "type": "object",
    "additionalProperties": false,
    "required": ["issue_number"],
    "properties": {
      "issue_number":        { "type": "integer", "minimum": 1, "title": "Issue number" },
      "trigger_comment_id":  { "type": "integer", "minimum": 1, "title": "Triggering comment id (for reactions)" },
      "project":             { "type": "string", "pattern": "^[A-Za-z0-9-]{1,39}/[1-9][0-9]{0,6}$", "title": "Projects v2 board override (owner/number)" },
      "status_in_progress":  { "type": "string", "minLength": 1, "maxLength": 100, "default": "In progress" },
      "status_in_review":    { "type": "string", "minLength": 1, "maxLength": 100, "default": "In review" },
      "status_ready":        { "type": "string", "minLength": 1, "maxLength": 100, "default": "Ready" },
      "max_turns":           { "type": "integer", "minimum": 5, "maximum": 100, "default": 40 },
      "cli_timeout_minutes": { "type": "integer", "minimum": 5, "maximum": 45, "default": 30 },
      "run_budget_minutes":  { "type": "integer", "minimum": 10, "maximum": 55, "default": 55 },
      "max_code_files":      { "type": "integer", "minimum": 1, "maximum": 50, "default": 10 },
      "max_code_lines":      { "type": "integer", "minimum": 10, "maximum": 2000, "default": 400 }
    }
  }$json$::jsonb
)
on conflict (slug) do update
  set name                  = excluded.name,
      description           = excluded.description,
      version               = excluded.version,
      runtime_arn           = excluded.runtime_arn,
      runtime_qualifier     = excluded.runtime_qualifier,
      requires_repository   = excluded.requires_repository,
      max_runtime_seconds   = excluded.max_runtime_seconds,
      grace_seconds         = excluded.grace_seconds,
      start_timeout_seconds = excluded.start_timeout_seconds,
      default_params        = excluded.default_params,
      params_schema         = excluded.params_schema;
