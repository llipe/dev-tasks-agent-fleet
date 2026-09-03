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
