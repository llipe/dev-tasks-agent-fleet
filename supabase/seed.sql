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
-- 5. Verification
-- ---------------------------------------------------------------------
select 'installations' as table_name, count(*) from github_installations
union all select 'repositories', count(*) from repositories
union all select 'agents',       count(*) from agents;
