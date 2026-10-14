/**
 * S-153 (#265) — shared-secret authentication for `/api/internal/**` (SD-A1).
 *
 * These endpoints are called by the `pg_cron` jobs via `pg_net`, not by a
 * logged-in human, so they are NOT session-gated (the middleware classifies
 * them `internal` and lets them through — see `lib/auth/route-policy.ts`).
 * Authorization is this check: a shared secret presented in the
 * `X-Scheduler-Secret` header, compared in CONSTANT TIME against
 * `SCHEDULER_TRIGGER_SECRET`, FAIL-CLOSED.
 *
 * Fail-closed means: a missing env secret, a missing/empty header, a
 * length-mismatched header, or a value mismatch all deny. The secret value is
 * never logged or echoed. This mirrors the project's "non-human callers
 * authenticate with a secret, never an open endpoint" posture (the agent's
 * service-role key, Fly OIDC) and keeps the login boundary (ADR-007) intact for
 * every human-facing route.
 *
 * The release gate (S-160) asserts externally that an unauthenticated call to
 * an `/api/internal/**` endpoint returns 401 — the mechanical proof that this
 * is not an open invoke hole.
 */

import { timingSafeEqual } from "node:crypto";

export const SCHEDULER_SECRET_HEADER = "x-scheduler-secret";

/**
 * Constant-time string equality. `crypto.timingSafeEqual` throws on
 * length-mismatched buffers (and would itself leak length via the throw), so we
 * length-guard first and ALWAYS compare equal-length buffers. A length mismatch
 * returns false without throwing. Both inputs are compared as UTF-8 bytes.
 *
 * The length-guard is not a timing leak worth worrying about here: the secret
 * is high-entropy and server-held; an attacker learning only its byte-length
 * gains nothing exploitable, and the value comparison itself stays constant-time.
 */
export function constantTimeEqual(a: string, b: string): boolean {
  const bufA = Buffer.from(a, "utf8");
  const bufB = Buffer.from(b, "utf8");
  if (bufA.length !== bufB.length) {
    return false;
  }
  return timingSafeEqual(bufA, bufB);
}

export interface InternalAuthResult {
  ok: boolean;
  /** A short, secret-free reason when denied (for logs), else null. */
  reason: string | null;
}

/**
 * Decide whether a request to an `/api/internal/**` endpoint is authorized.
 * Pure over its two inputs so it is exhaustively unit-testable without a server:
 *
 * @param presentedSecret the `X-Scheduler-Secret` header value (or null/undefined).
 * @param configuredSecret `process.env.SCHEDULER_TRIGGER_SECRET` (or undefined).
 *
 * Fail-closed on every negative case; never throws. The caller returns 401 on
 * `ok === false` and MUST NOT include the reason's content beyond the fixed
 * strings here (no secret material is ever placed in `reason`).
 */
export function checkSchedulerSecret(
  presentedSecret: string | null | undefined,
  configuredSecret: string | undefined,
): InternalAuthResult {
  if (!configuredSecret || configuredSecret.length === 0) {
    // Misconfiguration is a deny, not a bypass: without a configured secret the
    // endpoint must reject everything rather than accept anything.
    return { ok: false, reason: "secret_not_configured" };
  }
  if (!presentedSecret || presentedSecret.length === 0) {
    return { ok: false, reason: "header_missing" };
  }
  if (!constantTimeEqual(presentedSecret, configuredSecret)) {
    return { ok: false, reason: "secret_mismatch" };
  }
  return { ok: true, reason: null };
}

/** Read + check the secret from a `Request`'s headers against the environment. */
export function authorizeInternalRequest(
  request: Request,
  env: NodeJS.ProcessEnv = process.env,
): InternalAuthResult {
  return checkSchedulerSecret(
    request.headers.get(SCHEDULER_SECRET_HEADER),
    env.SCHEDULER_TRIGGER_SECRET,
  );
}
