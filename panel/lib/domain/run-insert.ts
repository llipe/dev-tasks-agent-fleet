/**
 * S-112 (#125) — the `queued`-row snapshot builder (D1, OQ3, SD7).
 *
 * The panel inserts the `runs` row in `queued` state *before* contacting
 * AgentCore (D1), so an invocation that never starts is a visible
 * `failed_to_start` row rather than an invisible nothing. This module builds
 * that insert payload as a pure function so its completeness is unit-testable
 * without a database.
 *
 * OQ3 correctness requirement (NOT a schema change): `runs.max_runtime_seconds`
 * is `not null` with **no default**, while `grace_seconds` and
 * `start_timeout_seconds` are `not null` with schema defaults (60 / 300). If the
 * insert omitted any of them, two would silently take the schema default and
 * `max_runtime_seconds` would fail the insert. So the snapshot copies **all
 * three** timeout columns explicitly from the agent row — the same
 * snapshot-over-live-reference rule the run history depends on.
 *
 * SD7: `triggered_by` is the constant `"panel"`, never a user identity (there
 * is no auth in v1, D16). `trigger_type` is `"manual"`.
 */

/** The columns the panel writes when inserting the `queued` run. */
export interface RunInsert {
  id: string;
  agent_id: string;
  agent_version: string;
  repository_id: string | null;
  installation_id: string | null;
  trigger_type: "manual";
  triggered_by: "panel";
  params: Record<string, unknown>;
  status: "queued";
  /** All three timeout snapshots are explicit (OQ3). */
  max_runtime_seconds: number;
  grace_seconds: number;
  start_timeout_seconds: number;
}

/** The subset of an `agents` row the snapshot needs. */
export interface AgentSnapshotSource {
  id: string;
  version: string;
  max_runtime_seconds: number;
  grace_seconds: number;
  start_timeout_seconds: number;
}

export interface BuildRunInsertInput {
  runId: string;
  agent: AgentSnapshotSource;
  /** `null` for an agent that does not require a repository. */
  repositoryId: string | null;
  /** The repository's installation id, or `null` when there is no repository. */
  installationId: string | null;
  /** The Ajv-validated params (schema-present keys only). */
  params: Record<string, unknown>;
}

/**
 * A timeout snapshot value that is missing or non-finite is a programming/data
 * error, not something to paper over with a default — the reaper relies on
 * these three being the real per-run thresholds. Fail loudly.
 */
class RunSnapshotError extends Error {
  readonly code = "RUN_SNAPSHOT_INVALID";
  constructor(field: string, value: unknown) {
    super(
      `Cannot snapshot run: agent.${field} is not a finite number (received ${String(value)}).`,
    );
    this.name = "RunSnapshotError";
  }
}

function requireFinite(field: string, value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new RunSnapshotError(field, value);
  }
  return value;
}

/**
 * Builds the `queued`-row insert payload. Copies all three timeout columns
 * explicitly from the agent snapshot (OQ3), sets `triggered_by = "panel"`
 * (SD7), and never relies on a schema default. Throws `RunSnapshotError` rather
 * than write a row the reaper cannot resolve.
 */
export function buildRunInsert(input: BuildRunInsertInput): RunInsert {
  return {
    id: input.runId,
    agent_id: input.agent.id,
    agent_version: input.agent.version,
    repository_id: input.repositoryId,
    installation_id: input.installationId,
    trigger_type: "manual",
    triggered_by: "panel",
    params: input.params,
    status: "queued",
    max_runtime_seconds: requireFinite("max_runtime_seconds", input.agent.max_runtime_seconds),
    grace_seconds: requireFinite("grace_seconds", input.agent.grace_seconds),
    start_timeout_seconds: requireFinite(
      "start_timeout_seconds",
      input.agent.start_timeout_seconds,
    ),
  };
}

export { RunSnapshotError };
