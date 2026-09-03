/**
 * SD4 — read-time status derivation.
 *
 * `effectiveStatus` is the TypeScript mirror of the `v_runs.effective_status`
 * `case` expression in the canonical migration
 * (`supabase/migrations/20260902200101_initial_schema.sql`). The two MUST stay
 * in lock-step; the Layer 2.5 parity test
 * (`tests/integration/status-parity.test.ts`) pins them to each other over a
 * fixture matrix, including exact-boundary rows.
 *
 * The SQL, verbatim:
 *
 *   case
 *     when r.status = 'running'
 *      and now() > r.started_at + make_interval(secs => r.max_runtime_seconds + r.grace_seconds)
 *       then 'timed_out'
 *     when r.status = 'queued'
 *      and now() > r.queued_at + make_interval(secs => r.start_timeout_seconds)
 *       then 'failed_to_start'
 *     else r.status
 *   end
 *
 * Three properties of the SQL that this mirror preserves exactly:
 *  1. **Strict `>`**. At the exact threshold instant the run passes through
 *     unchanged; only strictly past it does it flip (CT-2).
 *  2. **Null guard on `started_at`**. In SQL `now() > NULL` is `NULL` (falsy in
 *     a `case`), so a `running` row with no `started_at` never derives
 *     `timed_out` (CT-3). The TS guard reproduces this.
 *  3. **Null-safe threshold arithmetic**. In SQL adding a `NULL`
 *     `max_runtime_seconds` yields a `NULL` interval, so the comparison is
 *     `NULL` and the row passes through — it is never coerced to `0` and
 *     reaped (CT-4). The TS guard reproduces this even though the column is
 *     `not null` in the live schema (defensive against a shape the DB forbids).
 */

// The seven lifecycle values of the `run_status` Postgres enum. A future
// migration may add an eighth (API-versioning edge, EC-20); `effectiveStatus`
// passes any unknown value through unchanged rather than throwing, so a schema
// that runs ahead of a panel deploy degrades gracefully.
export type RunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "timed_out"
  | "failed_to_start"
  | "canceled";

/**
 * The minimal projection of a run needed to derive its effective status. This
 * is deliberately a structural subset of the `v_runs` row so both the raw
 * `runs` shape and the `v_runs` shape satisfy it. Timestamps are epoch
 * milliseconds (what `Date.parse` / `Date.getTime` produce); the caller is
 * responsible for parsing `timestamptz` strings once, at the read boundary.
 */
export interface StatusInput {
  status: RunStatus | (string & {});
  /** epoch ms, or null when the run has not started (queued) */
  startedAtMs: number | null;
  /** epoch ms; always present (`queued_at` is `not null` in the schema) */
  queuedAtMs: number | null;
  /** seconds; `not null` in the live schema, nullable here for defensiveness */
  maxRuntimeSeconds: number | null;
  /** seconds; `not null` in the live schema */
  graceSeconds: number | null;
  /** seconds; `not null` in the live schema */
  startTimeoutSeconds: number | null;
}

/**
 * Returns the effective status of a run at the injected instant `nowMs`
 * (epoch ms). Pure and deterministic: it reads no ambient clock and mutates
 * nothing, so it is testable at exact boundaries (EC-8). Inject
 * `Date.now()` at the call site.
 */
export function effectiveStatus(run: StatusInput, nowMs: number): RunStatus | (string & {}) {
  if (run.status === "running") {
    // Guard 2 + 3: both operands must be present, mirroring the SQL where a
    // NULL on either side makes the comparison NULL (pass-through).
    if (run.startedAtMs !== null && run.maxRuntimeSeconds !== null && run.graceSeconds !== null) {
      const thresholdMs = run.startedAtMs + (run.maxRuntimeSeconds + run.graceSeconds) * 1000;
      // Guard 1: strict greater-than.
      if (nowMs > thresholdMs) {
        return "timed_out";
      }
    }
    return run.status;
  }

  if (run.status === "queued") {
    if (run.queuedAtMs !== null && run.startTimeoutSeconds !== null) {
      const thresholdMs = run.queuedAtMs + run.startTimeoutSeconds * 1000;
      if (nowMs > thresholdMs) {
        return "failed_to_start";
      }
    }
    return run.status;
  }

  // Every terminal status (succeeded, failed, canceled, timed_out,
  // failed_to_start) and any unknown future value passes through unchanged.
  return run.status;
}
