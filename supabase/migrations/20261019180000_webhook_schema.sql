-- =====================================================================
-- Agent Fleet -- Webhook Triggers Phase 1: webhook schema
-- Story S-165 (#309). Schema only: no functions, no cron, no routes.
-- The webhook mechanism is inert until the inbound route (S-169) lands.
--
-- Rollback (additive, safe -- nothing else references these objects):
--   drop table webhook_deliveries, webhook_rules, webhook_endpoints;
--   drop type webhook_outcome, webhook_source;
-- =====================================================================

-- ---------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------
create type webhook_source as enum ('github', 'generic');

create type webhook_outcome as enum (
  'received',        -- verified + recorded, routing not yet decided
  'unauthorized',    -- signature missing/invalid (401); never claims a dedup key (D-W16)
  'duplicate',       -- verified, but the dedup key was already claimed (200 no-op)
  'ignored',         -- event type not on the endpoint allowlist, or unparseable body (202)
  'no_match',        -- no rule matched and no default rule (202)
  'route_rejected',  -- matched, but agent/repo/params failed resolution (202)
  'skipped',         -- resolved, but a guardrail skipped the run (202)
  'fired'            -- a run was queued (202)
);

-- ---------------------------------------------------------------------
-- webhook_endpoints
--   A registered inbound target. url_token is the unguessable path
--   segment of POST /api/webhooks/<token> (FR1). The signing secret is
--   NOT stored here -- it lives in Vault (S-166, D-W4). The signature
--   scheme is fixed to HMAC-SHA256 `sha256=<hex>`; only the header
--   names are configurable (spec §9.1, D-W15).
-- ---------------------------------------------------------------------
create table webhook_endpoints (
  id                  uuid primary key default gen_random_uuid(),
  name                text not null default '',
  url_token           text not null,
  source              webhook_source not null default 'github',
  signature_header    text not null default 'x-hub-signature-256',
  delivery_id_header  text not null default 'x-github-delivery',
  event_allowlist     text[] not null default '{}',
  ignore_bot_author   boolean not null default true,     -- FR19 / D-W12
  is_enabled          boolean not null default true,

  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),

  constraint uq_webhook_endpoints_url_token unique (url_token),
  -- EC-8: a fixed URL-safe alphabet and bounded length, so path traversal or
  -- encoded separators can never be a valid token. Panel-generated tokens are
  -- 43-char base64url (32 random bytes).
  constraint chk_webhook_endpoints_url_token check (url_token ~ '^[A-Za-z0-9_-]{32,64}$'),
  constraint chk_webhook_endpoints_name_len check (char_length(name) <= 100),
  -- Header names: lowercase token characters only (HTTP header names are
  -- case-insensitive; the route lowercases before lookup).
  constraint chk_webhook_endpoints_signature_header check (signature_header ~ '^[a-z0-9-]{1,64}$'),
  constraint chk_webhook_endpoints_delivery_id_header check (delivery_id_header ~ '^[a-z0-9-]{1,64}$')
);

create trigger trg_webhook_endpoints_updated
  before update on webhook_endpoints
  for each row execute function set_updated_at();

-- ---------------------------------------------------------------------
-- webhook_rules
--   Ordered match -> route rows, first-match-wins by position (FR9).
--   conditions: a JSON array of {field, op, value}, ANDed; its shape is
--   validated by the panel at save (S-170/S-177) -- the DB only enforces
--   that it is an array. params: {static: {...}, from_payload: {key: path}}
--   (D-W9), validated against the agent's params_schema at save and at fire.
-- ---------------------------------------------------------------------
create table webhook_rules (
  id                      uuid primary key default gen_random_uuid(),
  endpoint_id             uuid not null references webhook_endpoints(id) on delete cascade,
  position                integer not null,
  name                    text not null default '',
  event_types             text[] not null default '{}',
  conditions              jsonb not null default '[]'::jsonb,
  is_default              boolean not null default false,

  agent_id                uuid not null references agents(id) on delete cascade,
  repo_mode               text not null default 'payload_field',
  repository_id           uuid references repositories(id) on delete cascade,
  repo_payload_field      text,
  params                  jsonb not null default '{}'::jsonb,

  -- G3 per rule (D-W10)
  consecutive_failures    integer not null default 0,
  auto_disable_threshold  integer not null default 3,

  is_enabled              boolean not null default true,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now(),

  -- Deferrable so the rule editor can renumber positions in one
  -- transaction (S-177 task 13.4) without a temporary collision.
  -- Consequence: it cannot be an ON CONFLICT arbiter (SQLSTATE 55000);
  -- inserts that need idempotency use `where not exists` instead.
  constraint uq_webhook_rules_endpoint_position unique (endpoint_id, position)
    deferrable initially immediate,
  constraint chk_webhook_rules_position check (position >= 0),
  constraint chk_webhook_rules_repo_mode check (repo_mode in ('fixed', 'payload_field')),
  constraint chk_webhook_rules_repo_target check (
    case repo_mode
      when 'fixed'         then repository_id is not null
      when 'payload_field' then repo_payload_field is not null and char_length(repo_payload_field) between 1 and 200
    end
  ),
  constraint chk_webhook_rules_conditions_array check (jsonb_typeof(conditions) = 'array'),
  constraint chk_webhook_rules_params_object check (jsonb_typeof(params) = 'object'),
  constraint chk_webhook_rules_threshold check (auto_disable_threshold >= 1),
  constraint chk_webhook_rules_failures check (consecutive_failures >= 0),
  constraint chk_webhook_rules_name_len check (char_length(name) <= 100)
);

-- At most one catch-all default rule per endpoint (FR15).
create unique index uq_webhook_rules_one_default
  on webhook_rules (endpoint_id) where is_default;
create index idx_webhook_rules_agent on webhook_rules (agent_id);

create trigger trg_webhook_rules_updated
  before update on webhook_rules
  for each row execute function set_updated_at();

-- ---------------------------------------------------------------------
-- webhook_deliveries
--   One row per inbound attempt that reached a known endpoint (G5 / FR23).
--   D-W16 (B-4): every attempt is recorded, including `unauthorized`, with
--   the presented delivery_id kept for grouping. Only a signature-verified
--   delivery sets dedup_key (delivery id, else a body hash); dedup_key is
--   unique per endpoint and Postgres treats nulls as distinct, so a forged
--   request reusing a real delivery id can never block the genuine one.
--   No request body or signature is stored (FR8). Text columns are length-
--   capped so an attacker holding the URL cannot inflate rows (test plan R-3).
--   run_id is set-null so the retention prune (S-167) never touches runs.
-- ---------------------------------------------------------------------
create table webhook_deliveries (
  id               uuid primary key default gen_random_uuid(),
  endpoint_id      uuid not null references webhook_endpoints(id) on delete cascade,
  delivery_id      text,
  dedup_key        text,
  event_type       text,
  outcome          webhook_outcome not null default 'received',
  matched_rule_id  uuid references webhook_rules(id) on delete set null,
  run_id           uuid references runs(id) on delete set null,
  reason           text,
  received_at      timestamptz not null default now(),

  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),

  constraint uq_webhook_deliveries_dedup unique (endpoint_id, dedup_key),
  constraint chk_webhook_deliveries_unauthorized_no_key check (
    outcome <> 'unauthorized' or dedup_key is null
  ),
  constraint chk_webhook_deliveries_delivery_id_len check (char_length(delivery_id) <= 200),
  constraint chk_webhook_deliveries_dedup_key_len check (char_length(dedup_key) <= 200),
  constraint chk_webhook_deliveries_event_type_len check (char_length(event_type) <= 100),
  constraint chk_webhook_deliveries_reason_len check (char_length(reason) <= 500)
);

-- Group every attempt that presented the same delivery id (D-W16, troubleshooting).
create index idx_webhook_deliveries_delivery_id on webhook_deliveries (endpoint_id, delivery_id);
-- The delivery-log feed, newest first (FR23).
create index idx_webhook_deliveries_endpoint_created on webhook_deliveries (endpoint_id, created_at desc);
-- The retention prune scans by age across endpoints (S-167).
create index idx_webhook_deliveries_created on webhook_deliveries (created_at);
create index idx_webhook_deliveries_run on webhook_deliveries (run_id) where run_id is not null;

create trigger trg_webhook_deliveries_updated
  before update on webhook_deliveries
  for each row execute function set_updated_at();

-- ---------------------------------------------------------------------
-- RLS: deny-all from creation (D11), consistent with every other table.
-- Only service_role (which bypasses RLS) reads/writes; the panel reads
-- server-side with the service-role key (SD2). Covered by the schema-
-- enumerated rls-deny-all.test.ts and webhook-schema.test.ts.
-- ---------------------------------------------------------------------
alter table webhook_endpoints  enable row level security;
alter table webhook_rules      enable row level security;
alter table webhook_deliveries enable row level security;
