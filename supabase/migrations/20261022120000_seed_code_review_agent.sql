-- =====================================================================
-- S-204 (issue #406) -- seed the `code-review` agents row (spec §5.1)
--
-- Data only: one row in `agents`, no schema change. Mirrors section 4a of
-- supabase/seed.sql (local); this file is the prod path. The insert is
-- idempotent (`on conflict (slug) do update`), so re-applying it leaves one
-- row and refreshes the contract columns.
--
-- runtime_arn is a placeholder until Wave B (S-214) deploys the AgentCore
-- runtime and sets it with an explicit update. runtime_arn and
-- runtime_qualifier are deliberately NOT refreshed on conflict, so
-- re-applying this migration after the deploy cannot clobber the real ARN.
-- is_enabled is not touched either, so an operator's disable survives.
--
-- Apply: local `supabase db reset` only. Prod apply waits for S-214 and an
-- explicit user confirmation (infra-engineer).
--
-- Verify:
--   select slug, params_schema, default_params, max_runtime_seconds
--     from agents where slug = 'code-review';
--
-- Rollback / impact:
--   No runs reference it yet:
--     delete from agents where slug = 'code-review';
--   Runs reference it (runs.agent_id is `on delete restrict`):
--     update agents set is_enabled = false where slug = 'code-review';
-- =====================================================================

insert into agents (
  slug, name, description, version,
  runtime_arn, runtime_qualifier,
  requires_repository, max_runtime_seconds, grace_seconds, start_timeout_seconds,
  default_params, params_schema
)
values (
  'code-review',
  'Code Review',
  'Reviews one pull request against its linked issues, spec, and verifier report with one Bedrock call, and posts one PR comment.',
  '0.1.0',
  'pending-deploy:code-review',  -- placeholder; set by S-214 after the first deploy
  'DEFAULT',
  true,
  1800,  -- 30 min: MUST equal maxLifetime in agentcore.json
  120,   -- grace_seconds
  300,   -- start_timeout_seconds: queue clock (D9), NOT idleRuntimeSessionTimeout
  '{"max_diff_lines":2000,"max_context_tokens":150000,"max_suggestions":5,"run_timeout_seconds":900,"reasoning_effort":"high"}'::jsonb,
  $json${
    "type": "object",
    "additionalProperties": false,
    "required": ["pr_number"],
    "properties": {
      "pr_number": {
        "type": "integer",
        "minimum": 1,
        "title": "Pull request number"
      },
      "max_diff_lines": {
        "type": "integer",
        "minimum": 100,
        "maximum": 10000,
        "default": 2000
      },
      "max_context_tokens": {
        "type": "integer",
        "minimum": 20000,
        "maximum": 400000,
        "default": 150000
      },
      "max_suggestions": {
        "type": "integer",
        "minimum": 0,
        "maximum": 20,
        "default": 5
      },
      "run_timeout_seconds": {
        "type": "integer",
        "minimum": 120,
        "maximum": 900,
        "default": 900
      },
      "reasoning_effort": {
        "type": "string",
        "enum": ["low", "medium", "high"],
        "default": "high"
      }
    }
  }$json$::jsonb
)
on conflict (slug) do update
  set name                  = excluded.name,
      description           = excluded.description,
      version               = excluded.version,
      requires_repository   = excluded.requires_repository,
      max_runtime_seconds   = excluded.max_runtime_seconds,
      grace_seconds         = excluded.grace_seconds,
      start_timeout_seconds = excluded.start_timeout_seconds,
      default_params        = excluded.default_params,
      params_schema         = excluded.params_schema;
