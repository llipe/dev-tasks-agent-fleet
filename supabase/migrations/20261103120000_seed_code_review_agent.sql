-- =====================================================================
-- PRD v1.4 (code-review agent context selection) -- re-seed the
-- `code-review` agents row with the v1.4 params contract (spec §5.1).
--
-- Data only: one idempotent upsert, no schema change. Adds two params:
--   context_folders   string, default "docs,workstream" (FR-1, FR-36, D-60):
--                     comma-separated repository folders the selection call
--                     may pick documents from; the pattern is FR-36's rule.
--   context_selection "llm" (default) | "rules" (FR-32, D-59).
-- Same statement as 20261022120000_seed_code_review_agent.sql (left as
-- applied history, never edited) with the new params_schema and
-- default_params. Mirrors section 4a of supabase/seed.sql (local).
--
-- The row is live, so on conflict only the contract columns are refreshed:
-- runtime_arn, runtime_qualifier and is_enabled are NOT in the `do update`
-- list, so the deployed ARN and the operator's enable survive. A disabled
-- placeholder row is inserted only where no code-review row exists (a fresh
-- database), exactly as the original seed migration does.
--
-- Apply: local `supabase db reset`; prod only as a user-confirmed
-- infra-engineer step after the runtime that reads these params is deployed
-- (an older runtime rejects the new keys as unknown params).
--
-- Verify:
--   select params_schema->'properties'->'context_folders',
--          default_params
--     from agents where slug = 'code-review';
--
-- Rollback: re-apply 20261022120000_seed_code_review_agent.sql's statement
-- (restores the v1.0 params_schema and default_params; runtime_arn and
-- is_enabled are untouched either way). Webhook rules that set the new
-- params would then fail validation, so remove those first.
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
  'Reviews one pull request against its linked issues, spec, and verifier report with one Bedrock call, and posts one PR comment.',
  '0.1.0',
  'pending-deploy:code-review',  -- placeholder; set by S-214 after the first deploy
  'DEFAULT',
  false,  -- is_enabled: disabled until S-214 deploys the runtime (D-39)
  true,   -- requires_repository
  1800,  -- 30 min: MUST equal maxLifetime in agentcore.json
  120,   -- grace_seconds
  300,   -- start_timeout_seconds: queue clock (D9), NOT idleRuntimeSessionTimeout
  '{"max_diff_lines":2000,"max_context_tokens":150000,"max_suggestions":5,"run_timeout_seconds":900,"reasoning_effort":"high","context_folders":"docs,workstream","context_selection":"llm"}'::jsonb,
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
