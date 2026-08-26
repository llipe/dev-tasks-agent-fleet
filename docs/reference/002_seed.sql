-- =====================================================================
-- Agent Fleet — seed manual
-- Idempotente: se puede volver a correr sin duplicar nada.
-- EDITAR SOLO EL BLOQUE 1 Y LA LISTA DE REPOS DEL BLOQUE 2.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. GitHub App installation   <<< EDITAR
-- ---------------------------------------------------------------------
insert into github_installations (github_org_slug, installation_id, app_id, private_key_secret_arn)
values (
  'mi-org',                                                   -- slug de la organización
  12345678,                                                   -- installation_id de GitHub
  987654,                                                     -- app_id de GitHub
  'arn:aws:secretsmanager:us-east-1:000000000000:secret:github-app-key'
)
on conflict (github_org_slug) do update
  set installation_id        = excluded.installation_id,
      app_id                 = excluded.app_id,
      private_key_secret_arn = excluded.private_key_secret_arn;

-- ---------------------------------------------------------------------
-- 2. Repositorios              <<< EDITAR LA LISTA
--    Agregar una línea por repo. Formato: (full_name, default_branch)
-- ---------------------------------------------------------------------
with inst as (
  select id from github_installations where github_org_slug = 'mi-org'
),
repos(full_name, default_branch) as (
  values
    ('mi-org/checkout-api',      'main'),
    ('mi-org/catalog-service',   'main'),
    ('mi-org/orders-worker',     'main'),
    ('mi-org/payments-gateway',  'master'),
    ('mi-org/notifications-svc', 'main')
)
insert into repositories (installation_id, full_name, default_branch)
select inst.id, repos.full_name, repos.default_branch
from inst, repos
on conflict (installation_id, full_name) do update
  set default_branch = excluded.default_branch,
      is_enabled     = true,
      archived_at    = null;

-- ---------------------------------------------------------------------
-- 3. Agente dependency-update  <<< EDITAR runtime_arn y max_runtime_seconds
--    max_runtime_seconds DEBE coincidir con el timeout real en AgentCore.
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
  'Corre npm audit sobre un repositorio y, opcionalmente, corrige las vulnerabilidades con un LLM y abre un PR.',
  '0.1.0',
  'arn:aws:bedrock-agentcore:us-east-1:000000000000:runtime/dependency-update',
  'DEFAULT',
  true,
  900,   -- 15 min: igualar al timeout de AgentCore
  60,
  300,
  '{"fix_mode":"audit_only","fail_on_findings":true}'::jsonb,
  $json${
    "type": "object",
    "additionalProperties": false,
    "required": ["fix_mode"],
    "properties": {
      "fix_mode": {
        "type": "string",
        "title": "Modo de corrección",
        "description": "audit_only reporta hallazgos. llm_fix intenta corregir y abrir un PR.",
        "enum": ["audit_only", "llm_fix"],
        "default": "audit_only"
      },
      "fail_on_findings": {
        "type": "boolean",
        "title": "Fallar si hay hallazgos",
        "description": "Solo aplica en modo audit_only.",
        "default": true
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
-- 4. Verificación
-- ---------------------------------------------------------------------
select 'installations' as tabla, count(*) from github_installations
union all select 'repositories', count(*) from repositories
union all select 'agents',       count(*) from agents;
