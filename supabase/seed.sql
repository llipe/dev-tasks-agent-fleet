-- =====================================================================
-- Agent Fleet — manual seed
-- Idempotent: safe to re-run without duplicating anything.
-- EDIT ONLY BLOCK 1 AND THE REPO LIST IN BLOCK 2.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. GitHub App installation   <<< EDIT
-- ---------------------------------------------------------------------
insert into github_installations (github_org_slug, installation_id, app_id, private_key_secret_arn)
values (
  'llipe',                                                    -- organization slug
  156226839,                                                  -- GitHub installation_id
  4687256,                                                    -- GitHub app_id
  'arn:aws:secretsmanager:us-east-1:755641879575:secret:agent-fleet/prod/GITHUB_APP_PRIVATE_KEY-t4sXT2'
)
on conflict (github_org_slug) do update
  set installation_id        = excluded.installation_id,
      app_id                 = excluded.app_id,
      private_key_secret_arn = excluded.private_key_secret_arn;

-- ---------------------------------------------------------------------
-- 2. Repositories              <<< EDIT THE LIST
--    Add one line per repo. Format: (full_name, default_branch)
-- ---------------------------------------------------------------------
with inst as (
  select id from github_installations where github_org_slug = 'llipe'
),
repos(full_name, default_branch) as (
  values
    ('llipe/memo-cli',           'main'),
    ('llipe/tf-ecommerce-mgmt',  'main')
)
insert into repositories (installation_id, full_name, default_branch)
select inst.id, repos.full_name, repos.default_branch
from inst, repos
on conflict (installation_id, full_name) do update
  set default_branch = excluded.default_branch,
      is_enabled     = true,
      archived_at    = null;

-- ---------------------------------------------------------------------
-- 3. dependency-update agent
--    runtime_arn already reflects the deployed runtime (issue #77). Update it
--    only if you redeploy under a different runtime name.
--    max_runtime_seconds (3600) MUST match maxLifetime in agentcore.json.
--    start_timeout_seconds (300) is the queue clock (queued_at-based, D9): how
--    long an accepted invocation may sit before the agent reports a start. It
--    is NOT the same as idleRuntimeSessionTimeout (an output-idle clock, raised
--    to 900 in issue #98) and must not be equated with it. See S-103 / issue
--    #116 and technical-guidelines.md §8.
-- ---------------------------------------------------------------------
insert into agents (
  slug, name, description, version,
  runtime_arn, runtime_qualifier,
  requires_repository, max_runtime_seconds, grace_seconds, start_timeout_seconds,
  default_params, params_schema
)
values (
  'dependency-update',
  'Dependency Update',
  'Runs npm audit against a repository and, optionally, fixes the vulnerabilities with an LLM and opens a PR.',
  '0.1.0',
  -- runtime_arn: reported by `agentcore status` after the deploy (issue #77).
  'arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/dependencyupdate_dependency_update-UsQc5U5Yz0',
  'DEFAULT',
  true,
  3600,  -- 60 min: MUST equal maxLifetime in agentcore.json
  120,   -- grace_seconds
  300,   -- start_timeout_seconds: queue clock (D9), NOT idleRuntimeSessionTimeout
  '{"fix_mode":"audit_only","fail_on_findings":true,"max_fix_attempts":3}'::jsonb,
  $json${
    "type": "object",
    "additionalProperties": false,
    "required": ["fix_mode"],
    "properties": {
      "fix_mode": {
        "type": "string",
        "title": "Fix mode",
        "description": "audit_only reports findings. llm_fix attempts a fix and opens a PR.",
        "enum": ["audit_only", "llm_fix"],
        "default": "audit_only"
      },
      "fail_on_findings": {
        "type": "boolean",
        "title": "Fail if findings exist",
        "description": "Only applies in audit_only mode.",
        "default": true
      },
      "max_fix_attempts": {
        "type": "integer",
        "title": "Max LLM agent attempts",
        "description": "Only applies in llm_fix mode. 0 disables the LLM agent. Range 0..5.",
        "minimum": 0,
        "maximum": 5,
        "default": 3
      },
      "base_branch": {
        "type": "string",
        "title": "PR base branch",
        "description": "Branch the PR is opened against. Defaults to the repo default branch (main).",
        "default": "main"
      }
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

-- ---------------------------------------------------------------------
-- 4. Verification
-- ---------------------------------------------------------------------
select 'installations' as table_name, count(*) from github_installations
union all select 'repositories', count(*) from repositories
union all select 'agents',       count(*) from agents;
