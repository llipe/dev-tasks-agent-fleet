/**
 * Row types for the six read objects the panel consumes.
 *
 * **Hand-written, not CLI-generated.** `supabase gen types` needs a live
 * database connection (or a running local stack) and emits one monolithic
 * `Database` type covering every table, function, and enum. For a read-only
 * boundary that touches six objects, a hand-written set is more reviewable,
 * has no generation step in CI, and does not couple the panel's type surface
 * to a transient local stack. The canonical source these mirror is
 * `supabase/migrations/20260902200101_initial_schema.sql`; when that schema
 * changes, these types and the Layer 2.5 shape test
 * (`tests/integration/queries.test.ts`) are updated together.
 *
 * PostgREST serializes `timestamptz` as ISO-8601 strings and `jsonb` as parsed
 * JSON. Numeric columns come back as JS numbers. `bigint` columns
 * (`installation_id`, `run_events.id`) exceed `Number.MAX_SAFE_INTEGER` only
 * beyond 2^53; PostgREST returns them as numbers, and none of the panel's read
 * paths do arithmetic on them, so `number` is accurate for display use.
 */

import type { RunStatus } from "@/lib/domain/status";

export type RunOutcome =
  | "fixed"
  | "partial"
  | "no_vulnerabilities"
  | "needs_review"
  | "not_applicable";

export type TriggerType = "manual" | "schedule" | "webhook";
export type StepStatus = "pending" | "running" | "succeeded" | "failed" | "skipped";
export type LogLevel = "debug" | "info" | "warn" | "error";
export type ArtifactType = "pull_request" | "audit_report" | "diff" | "file";

/** A parsed JSON value as returned by PostgREST for a `jsonb` column. */
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

/** `agents` — catalog of configured agents (SD2 read path). */
export interface AgentRow {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  version: string;
  runtime_arn: string;
  runtime_qualifier: string;
  params_schema: Json;
  default_params: Json;
  requires_repository: boolean;
  max_runtime_seconds: number;
  grace_seconds: number;
  start_timeout_seconds: number;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

/** `github_installations` — the single GitHub App installation row (S-147). */
export interface GithubInstallationRow {
  id: string;
  github_org_slug: string;
  installation_id: number;
  app_id: number;
  private_key_secret_arn: string | null;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

/** `repositories` — repos enabled to run agents. */
export interface RepositoryRow {
  id: string;
  installation_id: string;
  github_repo_id: number | null;
  full_name: string;
  default_branch: string;
  is_enabled: boolean;
  metadata: Json;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * `v_runs` — the runs view. It is `runs.*` plus three joined/derived columns
 * (`agent_slug`, `agent_name`, `repository_full_name`, `effective_status`).
 * The panel reads runs through this view, never the raw `runs` table, so the
 * read-time `effective_status` (SD4) is always present.
 */
export interface VRunRow {
  id: string;
  agent_id: string;
  agent_version: string;
  repository_id: string | null;
  installation_id: string | null;

  trigger_type: TriggerType;
  triggered_by: string | null;
  params: Json;
  idempotency_key: string | null;

  session_id: string | null;
  runtime_invocation_id: string | null;

  status: RunStatus;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  last_heartbeat_at: string | null;

  max_runtime_seconds: number;
  grace_seconds: number;
  start_timeout_seconds: number;

  outcome: RunOutcome | null;
  error_code: string | null;
  error_message: string | null;
  result: Json;
  metrics: Json;

  created_at: string;
  updated_at: string;

  // View-only columns:
  agent_slug: string;
  agent_name: string;
  repository_full_name: string | null;
  effective_status: RunStatus;
}

/** `run_steps` — named phases within an execution. */
export interface RunStepRow {
  id: string;
  run_id: string;
  seq: number;
  key: string;
  title: string | null;
  status: StepStatus;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  data: Json;
  created_at: string;
}

/** `run_events` — the structured log (D4). */
export interface RunEventRow {
  id: number;
  run_id: string;
  step_id: string | null;
  seq: number;
  ts: string;
  level: LogLevel;
  message: string;
  data: Json;
}

/** `run_artifacts` — execution artifacts (PR, audit report, diff, file). */
export interface RunArtifactRow {
  id: string;
  run_id: string;
  type: ArtifactType;
  title: string | null;
  url: string | null;
  storage_path: string | null;
  metadata: Json;
  created_at: string;
}

// ---------------------------------------------------------------------
// Phase 4 — Agent Scheduler (S-149). Mirrors
// `supabase/migrations/20261013160000_scheduler_schema.sql`.
// ---------------------------------------------------------------------

export type ScheduleState = "active" | "paused" | "blocked";
export type CadenceKind = "hourly" | "daily" | "weekly" | "every_n_hours" | "advanced";
export type NotificationKind =
  | "run_failed"
  | "schedule_auto_paused"
  | "pr_opened"
  | "run_succeeded";

/** `schedules` — a recurring agent invocation (SD-S1). */
export interface ScheduleRow {
  id: string;
  agent_id: string;
  repository_id: string | null;
  installation_id: string | null;

  name: string | null;
  params: Json;

  cadence_kind: CadenceKind;
  cadence_minute: number | null;
  cadence_hour: number | null;
  cadence_weekday: number | null;
  cadence_interval_hours: number | null;
  cadence_cron: string | null;
  timezone: string;

  state: ScheduleState;
  is_enabled: boolean;

  consecutive_failures: number;
  auto_pause_threshold: number;
  block_reason: string | null;
  blocked_at: string | null;
  last_skipped_reason: string | null;
  last_skipped_at: string | null;

  pr_block_run_id: string | null;
  pr_block_cleared_at: string | null;

  notify_on_success: boolean;

  last_fired_at: string | null;
  last_run_id: string | null;
  next_run_at: string | null;
  last_fire_error: string | null;

  created_at: string;
  updated_at: string;
}

/** `notifications` — channel-agnostic notable-event record (SD-N1). */
export interface NotificationRow {
  id: string;
  kind: NotificationKind;
  schedule_id: string | null;
  agent_id: string | null;
  repository_id: string | null;
  run_id: string | null;
  title: string;
  detail: string | null;
  data: Json;
  read_at: string | null;
  emailed_at: string | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Webhook Triggers Phase 1 (S-165, #309). Hand-written to match
// `supabase/migrations/20261019180000_webhook_schema.sql`. The endpoint signing
// secret is deliberately absent: it lives only in Vault (S-166, D-W4) and must
// never appear in a row type the panel can pass to the client.
// ---------------------------------------------------------------------------

export type WebhookSource = "github" | "generic";
export type WebhookOutcome =
  | "received"
  | "unauthorized"
  | "duplicate"
  | "ignored"
  | "no_match"
  | "route_rejected"
  | "skipped"
  | "fired";
export type WebhookRepoMode = "fixed" | "payload_field";

/** Condition operators of the bounded routing language (D-W7, S-170). */
export type WebhookConditionOp =
  | "equals"
  | "not_equals"
  | "contains"
  | "prefix"
  | "suffix"
  | "in"
  | "exists"
  | "matches_event";

/** One `{field, op, value}` predicate; a rule's conditions are ANDed. */
export interface WebhookCondition {
  field: string;
  op: WebhookConditionOp;
  value?: string | string[];
}

/** `webhook_rules.params`: static values plus declared-key payload interpolation (D-W9). */
export interface WebhookRuleParams {
  static?: Record<string, Json>;
  from_payload?: Record<string, string>;
}

export interface WebhookEndpointRow {
  id: string;
  name: string;
  url_token: string;
  source: WebhookSource;
  signature_header: string;
  delivery_id_header: string;
  event_allowlist: string[];
  ignore_bot_author: boolean;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface WebhookRuleRow {
  id: string;
  endpoint_id: string;
  position: number;
  name: string;
  event_types: string[];
  conditions: WebhookCondition[];
  is_default: boolean;
  agent_id: string;
  repo_mode: WebhookRepoMode;
  repository_id: string | null;
  repo_payload_field: string | null;
  params: WebhookRuleParams;
  consecutive_failures: number;
  auto_disable_threshold: number;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * One inbound attempt. `delivery_id` is the presented header value (kept on every
 * row for grouping); `dedup_key` is set only once the signature verified (D-W16).
 */
export interface WebhookDeliveryRow {
  id: string;
  endpoint_id: string;
  delivery_id: string | null;
  dedup_key: string | null;
  event_type: string | null;
  outcome: WebhookOutcome;
  matched_rule_id: string | null;
  run_id: string | null;
  reason: string | null;
  received_at: string;
  created_at: string;
  updated_at: string;
}

/**
 * `v_schedules` — the schedules list view (S-161). `schedules.*` plus joined
 * agent/repository display columns and the last produced run's reaper-correct
 * status/outcome/finish time. The panel reads the list through this view, never
 * the raw `schedules` table (SD4 read path).
 */
export interface VScheduleRow extends ScheduleRow {
  agent_name: string;
  agent_slug: string;
  agent_is_enabled: boolean;
  repository_full_name: string | null;
  repository_default_branch: string | null;
  last_run_status: RunStatus | null;
  last_run_outcome: RunOutcome | null;
  last_run_finished_at: string | null;
}
