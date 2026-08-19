/**
 * Status derivation logic.
 *
 * A run with `last_status = "running"` that has exceeded maxLifetime + grace
 * is derived as `incomplete` at read time, without mutating DynamoDB.
 */

/** Default agent maxLifetime in milliseconds (8 hours) */
export const DEFAULT_MAX_LIFETIME_MS = 28_800_000;

/** Grace period after maxLifetime before marking as incomplete (5 minutes) */
export const TERMINATION_GRACE_MS = 300_000;

/**
 * Derive the effective status of a run.
 *
 * @param lastStatus - The stored status from DynamoDB
 * @param lastRunAt - ISO 8601 timestamp of when the run started
 * @param maxLifetimeMs - The agent's configured maxLifetime in ms (undefined → default)
 * @param now - Current time as Unix epoch ms
 * @returns The derived status string
 */
export function deriveStatus(
  lastStatus: string,
  lastRunAt: string | undefined,
  maxLifetimeMs: number | undefined,
  now: number,
): string {
  if (lastStatus !== "running") {
    return lastStatus;
  }

  // Cannot derive timeout if lastRunAt is missing or unparseable
  if (!lastRunAt) {
    return lastStatus;
  }

  const runStartMs = new Date(lastRunAt).getTime();
  if (Number.isNaN(runStartMs)) {
    return lastStatus;
  }

  const effectiveMaxLifetime = maxLifetimeMs ?? DEFAULT_MAX_LIFETIME_MS;
  const elapsed = now - runStartMs;
  const threshold = effectiveMaxLifetime + TERMINATION_GRACE_MS;

  if (elapsed >= threshold) {
    return "incomplete";
  }

  return "running";
}
