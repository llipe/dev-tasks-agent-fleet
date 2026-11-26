-- =====================================================================
-- PRD v1.7 / spec v1.8 (code-review agent on Claude Sonnet 5.5, S-217,
-- issue #481) -- re-seed the `code-review` agents row with the v1.8 params
-- contract (spec §5.1).
--
-- Data only: one idempotent upsert, no schema change. Two bounds move:
--   max_diff_lines      maximum 10000 -> 20000 (default stays 2000; D-77)
--   max_context_tokens  maximum 400000 -> 900000 and default
--                       150000 -> 900000 (D-90: the model's window holds
--                       B = 900000 plus the 64000 output tokens)
-- and the description names the model. Same statement as
-- 20261103120000_seed_code_review_agent.sql (left as applied history, never
-- edited), with the new params_schema, default_params and description.
-- Mirrors section 4a of supabase/seed.sql (local).
--
-- The row is live, so on conflict only the contract columns are refreshed:
-- runtime_arn, runtime_qualifier and is_enabled are NOT in the `do update`
-- list, so the deployed ARN and the operator's enable survive. A disabled
-- placeholder row is inserted only where no code-review row exists (a fresh
-- database), exactly as the earlier seed migrations do.
--
-- Deploy order (D-89): (1) the v1.8 runtime first, (2) then this migration,
-- (3) then the riel `/review` rule's max_diff_lines 20000. The runtime live
-- before v1.8 (version 5) validates params against its own schema and
-- rejects max_context_tokens 900000 (the new default the panel fills in), so
-- this migration must never reach prod before the runtime that accepts it.
--
-- Apply: local `supabase db reset`; prod only as a user-confirmed
-- infra-engineer step (S-218, issue #482, step 3.5) after the runtime deploy.
-- Never applied by S-217.
--
-- Verify:
--   select params_schema->'properties'->'max_context_tokens',
--          params_schema->'properties'->'max_diff_lines',
--          default_params
--     from agents where slug = 'code-review';
--   -- expect maximum 900000 / default 900000, maximum 20000, and
--   -- default_params.max_context_tokens = 900000. The panel's params form
--   -- accepts max_context_tokens 900000 and rejects 900001.
--
-- Rollback: re-apply 20261103120000_seed_code_review_agent.sql's statement
-- (restores the v1.4 params_schema, default_params and description;
-- runtime_arn and is_enabled are untouched either way).
-- Roll it back before the runtime: first set any webhook rule with
-- max_diff_lines over 10000 or
-- max_context_tokens over 400000 back within the old bounds (the riel
-- `/review` rule to 2000), then re-apply the old seed, then roll the
-- runtime back. Runtime version 5 with this migration still applied rejects the
-- 900000 default, so the migration rollback always comes first.
-- =====================================================================

insert into agents (
  slug, name, description, version,
  runtime_arn, runtime_qualifier,
  is_enabled,
  requires_repository, max_runtime_seconds, grace_seconds, start_timeout_seconds,
  default_params, params_schema
)
values (
  'code-review',
  'Code Review',
  'Reviews one pull request against its linked issues, spec, and verifier report with Claude Sonnet 5.5 on the Anthropic API, and posts one PR comment.',
  '0.1.0',
  'pending-deploy:code-review',  -- placeholder; set by S-214 after the first deploy
  'DEFAULT',
  false,  -- is_enabled: disabled until S-214 deploys the runtime (D-39)
  true,   -- requires_repository
  1800,  -- 30 min: MUST equal maxLifetime in agentcore.json
  120,   -- grace_seconds
  300,   -- start_timeout_seconds: queue clock (D9), NOT idleRuntimeSessionTimeout
  '{"max_diff_lines":2000,"max_context_tokens":900000,"max_suggestions":5,"run_timeout_seconds":900,"reasoning_effort":"high","context_folders":"docs,workstream","context_selection":"llm"}'::jsonb,
  $json${
    "type": "object",
    "additionalProperties": false,
    "required": [
      "pr_number"
    ],
    "properties": {
      "pr_number": {
        "type": "integer",
        "minimum": 1,
        "title": "Pull request number"
      },
      "max_diff_lines": {
        "type": "integer",
        "minimum": 100,
        "maximum": 20000,
        "default": 2000
      },
      "max_context_tokens": {
        "type": "integer",
        "minimum": 20000,
        "maximum": 900000,
        "default": 900000
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
        "enum": [
          "low",
          "medium",
          "high"
        ],
        "default": "high"
      },
      "context_folders": {
        "type": "string",
        "maxLength": 1000,
        "pattern": "^(?:(?!\\.\\.?(?:[/, ]|$))[A-Za-z0-9._-]+(?:/(?!\\.\\.?(?:[/, ]|$))[A-Za-z0-9._-]+)*(?: *, *(?!\\.\\.?(?:[/, ]|$))[A-Za-z0-9._-]+(?:/(?!\\.\\.?(?:[/, ]|$))[A-Za-z0-9._-]+)*){0,9})?$",
        "default": "docs,workstream"
      },
      "context_selection": {
        "type": "string",
        "enum": [
          "llm",
          "rules"
        ],
        "default": "llm"
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
