-- =====================================================================
-- Agent Fleet -- manual seed
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
--    #116 and technical-guidelines.md section 8.
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
-- 4. security-analyst agent
--    runtime_arn set after first `agentcore deploy` (see agents/security-analyst/README.md).
--    max_runtime_seconds (5400) MUST match maxLifetime in agentcore.json (PRD §12.3 --
--    higher than dependency-update's 3600 because 5 scanners + a full rescan pass
--    run sequentially in the worst case).
--    start_timeout_seconds (300) is the queue clock (D9) -- unchanged from the
--    sibling agent, this is not a scanner-runtime concern.
-- ---------------------------------------------------------------------
insert into agents (
  slug, name, description, version,
  runtime_arn, runtime_qualifier,
  requires_repository, max_runtime_seconds, grace_seconds, start_timeout_seconds,
  default_params, params_schema
)
values (
  'security-analyst',
  'Security Analyst',
  'Runs Semgrep, Gitleaks, Trivy, Checkov, and CodeQL against a repository; optionally applies mechanical fixes, re-scans to verify, and opens a PR.',
  '0.1.0',
  -- runtime_arn: reported by `agentcore status` (deployed under S-125; see
  -- agents/security-analyst/README.md and agents/security-analyst/agentcore/.cli/deployed-state.json).
  'arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/securityanalyst_security_analyst-w6CpbYHRE0',
  'DEFAULT',
  true,
  5400,  -- 90 min: MUST equal maxLifetime in agentcore.json
  150,   -- grace_seconds (higher than sibling's 120 -- larger image, more cold-start)
  300,   -- start_timeout_seconds: queue clock (D9), unchanged from sibling
  '{"mode":"audit_only","fail_on_findings":true,"min_severity":"low","max_fix_attempts":3,"scanners":["semgrep","gitleaks","trivy","checkov","codeql"]}'::jsonb,
  $json${
    "type": "object",
    "additionalProperties": false,
    "required": ["mode"],
    "properties": {
      "mode": {
        "type": "string",
        "title": "Mode",
        "description": "audit_only reports findings. fix applies mechanical fixes, re-scans, and opens a PR.",
        "enum": ["audit_only", "fix"],
        "default": "audit_only"
      },
      "fail_on_findings": {
        "type": "boolean",
        "title": "Fail if findings exist",
        "description": "Only applies in audit_only mode.",
        "default": true
      },
      "min_severity": {
        "type": "string",
        "title": "Minimum severity to gate on",
        "description": "Findings below this severity are still scanned, fixed (in fix mode), and reported, but do not affect fail_on_findings or the needs_review/no_findings outcome.",
        "enum": ["low", "medium", "high", "critical"],
        "default": "low"
      },
      "max_fix_attempts": {
        "type": "integer",
        "title": "Max LLM agent attempts per finding",
        "description": "Only applies in fix mode. 0 disables the LLM escape hatch. Range 0..5. Budget applies per finding, not per run.",
        "minimum": 0,
        "maximum": 5,
        "default": 3
      },
      "scanners": {
        "type": "array",
        "title": "Scanners to run",
        "description": "Subset of the 5 supported scanners. Empty or unrecognized values fail INVALID_PARAMS.",
        "items": {
          "type": "string",
          "enum": ["semgrep", "gitleaks", "trivy", "checkov", "codeql"]
        },
        "default": ["semgrep", "gitleaks", "trivy", "checkov", "codeql"],
        "minItems": 1
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
-- 4a. bug-fix agent (S-184, issue #366) -- MIRRORS
--    supabase/migrations/20261024130000_seed_bug_fix_agent.sql; keep the two
--    identical (panel/tests/integration/bug-fix-seed.test.ts checks parity).
--    runtime_arn: the S-181 deploy (infra/changes/20261023-bug-fix-runtime).
--    max_runtime_seconds (3600) MUST match maxLifetime in agentcore.json.
--    params_schema is spec §5.2 v2.0: issue_number is the only required key.
--    default_params holds only budgets, caps and status names (D-93, D-102).
-- ---------------------------------------------------------------------
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

-- ---------------------------------------------------------------------
-- 4b. Webhook fixture (S-165)  -- LOCAL DEV / E2E ONLY
--    One DISABLED sample endpoint + one rule routing a PR review comment
--    "security review" to security-analyst on the payload's repository.
--    Disabled on purpose: the inbound route treats a disabled endpoint as
--    unknown (404), so this row can never receive traffic even if this seed
--    is applied to a non-local database. The token is a well-known local
--    value; production endpoints are created in the panel (S-176), which
--    generates a random token. No signing secret is seeded here.
-- ---------------------------------------------------------------------
insert into webhook_endpoints (name, url_token, source, event_allowlist, is_enabled)
values (
  'Local sample (disabled)',
  'local-dev-sample-endpoint-token-0000000',
  'github',
  array['pull_request', 'issue_comment', 'pull_request_review_comment', 'push'],
  false
)
on conflict (url_token) do nothing;

insert into webhook_rules (endpoint_id, position, name, event_types, conditions, agent_id, repo_mode, repo_payload_field, params)
select e.id, 0, 'Security review on request',
       array['pull_request_review_comment'],
       '[{"field": "comment.body", "op": "equals", "value": "security review"}]'::jsonb,
       a.id, 'payload_field', 'repository.full_name',
       '{"static": {"mode": "audit_only"}}'::jsonb
  from webhook_endpoints e, agents a
 where e.url_token = 'local-dev-sample-endpoint-token-0000000'
   and a.slug = 'security-analyst'
   -- Not `on conflict`: (endpoint_id, position) is deferrable (rule reorder,
   -- S-177), and Postgres cannot use a deferrable unique as an arbiter.
   and not exists (select 1 from webhook_rules r where r.endpoint_id = e.id and r.position = 0);

-- ---------------------------------------------------------------------
-- 5. Verification
-- ---------------------------------------------------------------------
select 'installations' as table_name, count(*) from github_installations
union all select 'repositories', count(*) from repositories
union all select 'agents',       count(*) from agents
union all select 'webhook_endpoints', count(*) from webhook_endpoints;
