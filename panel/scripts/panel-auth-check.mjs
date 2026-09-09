#!/usr/bin/env node
/**
 * Auth-check parser for the panel release gate (Story S-122, SR2 inversion / PRD AC17).
 *
 * This REPLACES the S-115 privacy gate (`fly-privacy-check.mjs`). That gate
 * mechanized "privacy is the only boundary" (SR2/D16) and FAILED the release if
 * the app was public. This feature REVERSES that decision — the app gains a
 * login and will (in the separate Phase B / S-123) go public — so the mechanical
 * check must be REPLACED, never merely deleted: a release must never run with no
 * boundary check at all. The new boundary is asserted BY OBSERVATION on the
 * deployed app rather than by trusting configuration:
 *
 *   1. The auth env-var NAMES are present on the app (never their values).
 *   2. An unauthenticated request to a protected UI path is redirected (302) to
 *      /login — NOT served 200.
 *   3. An unauthenticated request to the SSE path returns 401 — NOT 200.
 *   4. An attempted signUp against the project's Auth endpoint is REJECTED.
 *      A SUCCESSFUL signup FAILS the release (PRD AC17 / R9): public signups on
 *      an internet-reachable panel let anyone self-register into the invoke
 *      surface. This is the single most important check.
 *
 * The parsing/decision logic lives here (PURE, no I/O) so it is unit-testable
 * from fixtures; `scripts/verify-panel-auth.sh` supplies the live probe results
 * and acts on the verdict. Keeping the parser separate is what lets the test
 * suite OBSERVE the gate failing on each violation fixture and passing on a
 * correct-deployment fixture — the "gate observed failing" evidence required by
 * the story.
 *
 * FAIL-CLOSED BY CONSTRUCTION: any input that cannot be positively confirmed as
 * the required outcome — a missing field, an unexpected status code, a network
 * error/timeout, a malformed or empty probe result, an unrecognized signup
 * outcome — counts as a FAILURE. Nothing is assumed to pass.
 */

/** The auth env-var names that MUST be present on the app (names only, never values). */
export const REQUIRED_AUTH_ENV_NAMES = [
  "NEXT_PUBLIC_SUPABASE_URL",
  "NEXT_PUBLIC_SUPABASE_ANON_KEY",
];

/** Coerce anything to a trimmed lower-cased string ("" for non-strings). */
function s(v) {
  return typeof v === "string" ? v.trim().toLowerCase() : "";
}

/** A finite integer status code, or null for anything else. */
function statusOf(probe) {
  if (!probe || typeof probe !== "object") return null;
  const raw = probe.status ?? probe.statusCode ?? probe.code;
  const n = typeof raw === "number" ? raw : Number.parseInt(String(raw ?? ""), 10);
  return Number.isInteger(n) ? n : null;
}

/**
 * CHECK 1 — the required auth env-var NAMES are present on the app.
 *
 * `presentNames` is the list of secret/config NAMES reported by
 * `fly secrets list` / `fly config show` (NAMES ONLY — the wrapper never
 * collects or passes values). Every name in REQUIRED_AUTH_ENV_NAMES must be
 * present. Missing/garbage input → fail (fail-closed).
 */
export function checkEnvNames(presentNames) {
  const present = new Set((Array.isArray(presentNames) ? presentNames : []).map((n) => s(n)));
  const missing = REQUIRED_AUTH_ENV_NAMES.filter((name) => !present.has(name.toLowerCase()));
  return {
    ok: missing.length === 0,
    missing,
    reason:
      missing.length === 0
        ? null
        : `Missing required auth env var name(s) on the app: ${missing.join(", ")}`,
  };
}

/**
 * CHECK 2 — an unauthenticated request to a protected UI path is redirected to
 * /login. It MUST return 302 AND its Location must point at /login. A 200
 * (page served to an anonymous user) is a hard failure; any other outcome
 * (network error, unexpected code, redirect to a NON-/login location) also
 * fails (fail-closed).
 */
export function checkProtectedRedirect(probe) {
  if (probe && probe.error) {
    return { ok: false, reason: `Protected-path probe failed to complete: ${String(probe.error)}` };
  }
  const status = statusOf(probe);
  if (status === null) {
    return { ok: false, reason: "Protected-path probe returned no usable status code." };
  }
  if (status === 200) {
    return {
      ok: false,
      reason: "Protected UI path returned 200 to an unauthenticated request (gate NOT enforcing).",
    };
  }
  if (status !== 302 && status !== 307) {
    return {
      ok: false,
      reason: `Protected UI path returned ${status}; expected a 302 redirect to /login.`,
    };
  }
  // A redirect — confirm it lands on /login, not somewhere else.
  const location = s(probe.location ?? probe.Location ?? "");
  const points =
    location === "/login" ||
    location.startsWith("/login?") ||
    location.startsWith("/login#") ||
    location.includes("/login?") ||
    location.endsWith("/login") ||
    /\/login(\?|#|$)/.test(location);
  if (!points) {
    return {
      ok: false,
      reason: `Protected UI path redirected to "${probe.location ?? probe.Location ?? "(none)"}", not /login.`,
    };
  }
  return { ok: true, reason: null };
}

/**
 * CHECK 3 — an unauthenticated request to the SSE path returns 401. A 200 is a
 * hard failure (the stream is reachable anonymously). Anything else, including
 * a 401 whose body happens to be HTML (still a 401 — status is authoritative),
 * is judged on the STATUS CODE only; a non-401/non-200 or an error fails
 * (fail-closed).
 */
export function checkSseUnauthorized(probe) {
  if (probe && probe.error) {
    return { ok: false, reason: `SSE probe failed to complete: ${String(probe.error)}` };
  }
  const status = statusOf(probe);
  if (status === null) {
    return { ok: false, reason: "SSE probe returned no usable status code." };
  }
  if (status === 200) {
    return {
      ok: false,
      reason: "SSE path returned 200 to an unauthenticated request (stream reachable anonymously).",
    };
  }
  if (status !== 401) {
    return { ok: false, reason: `SSE path returned ${status}; expected 401.` };
  }
  return { ok: true, reason: null };
}

/**
 * CHECK 4 — the signup-disabled release blocker (PRD AC17 / R9).
 *
 * The wrapper POSTs a `signUp` for a clearly-marked disposable address to the
 * project's Auth endpoint with the anon key. Supabase returns an ERROR when
 * public signups are disabled — that error is the PASS condition. A SUCCESSFUL
 * signup FAILS the release. Fail-closed on an unrecognized/missing outcome.
 *
 * `probe` shape (all optional; the parser is total):
 *   { rejected: boolean, error, message, createdUserId? }
 * `rejected: true`  → signups are off (PASS).
 * `rejected: false` (a user was created / no error) → signups are ON (FAIL).
 * anything else / missing → cannot confirm rejection → FAIL (fail-closed).
 */
export function checkSignupRejected(probe) {
  if (!probe || typeof probe !== "object") {
    return {
      ok: false,
      reason: "Signup probe produced no result — cannot confirm signups are off.",
    };
  }
  if (probe.rejected === true) {
    return { ok: true, reason: null };
  }
  if (probe.rejected === false || probe.createdUserId || probe.userId) {
    return {
      ok: false,
      reason:
        "A signUp SUCCEEDED — public signups are ENABLED. Release BLOCKED (anyone could self-register). Delete the created account.",
    };
  }
  // Unrecognized shape: an unexpected Supabase error object, a partial result,
  // etc. We cannot POSITIVELY confirm the signup was rejected, so fail closed.
  return {
    ok: false,
    reason: "Signup probe outcome could not be confirmed as a rejection (fail-closed).",
  };
}

/**
 * The gate verdict. Runs all four checks over the collected inputs and returns
 * `{ pass: boolean, checks: {...}, reasons: string[] }`. `pass` is true only
 * when EVERY check is ok.
 *
 * `input` shape (each field is optional; every missing/garbage field fails its
 * check, which is exactly the fail-closed behavior):
 *   {
 *     envNames:       string[]          // names from `fly secrets list` (names only)
 *     protectedProbe: { status, location } | { error }
 *     sseProbe:       { status }         | { error }
 *     signupProbe:    { rejected, ... }
 *   }
 */
export function evaluateAuthGate(input) {
  const src = input && typeof input === "object" ? input : {};
  const checks = {
    envNames: checkEnvNames(src.envNames),
    protectedRedirect: checkProtectedRedirect(src.protectedProbe),
    sseUnauthorized: checkSseUnauthorized(src.sseProbe),
    signupRejected: checkSignupRejected(src.signupProbe),
  };
  const reasons = [];
  for (const [, result] of Object.entries(checks)) {
    if (!result.ok && result.reason) reasons.push(result.reason);
  }
  return {
    pass: reasons.length === 0,
    checks,
    reasons,
  };
}

// --- CLI ------------------------------------------------------------------
// Usage: node panel-auth-check.mjs <gate-input.json>
// Exits 0 if the auth boundary holds, 1 if any check fails or the input cannot
// be read/parsed. The shell wrapper (verify-panel-auth.sh) collects the live
// probe results into the JSON file and acts on this exit code.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

function readJsonOrNull(path) {
  if (!path) return null;
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}

function mainCli() {
  const [, , inputPath] = process.argv;
  const parsed = readJsonOrNull(inputPath);
  if (parsed === null) {
    // Unreadable/unparseable input is itself a fail-closed failure.
    console.error(
      "[panel-auth] FAIL — could not read/parse the gate input JSON (fail-closed). The release is BLOCKED.",
    );
    process.exit(1);
  }
  const verdict = evaluateAuthGate(parsed);
  if (verdict.pass) {
    console.log(
      "[panel-auth] OK — auth boundary holds: env names present, protected UI → /login, SSE → 401, signups rejected.",
    );
    process.exit(0);
  }
  console.error("[panel-auth] FAIL — the auth boundary is NOT proven. The release is BLOCKED.");
  for (const r of verdict.reasons) console.error(`  - ${r}`);
  process.exit(1);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  mainCli();
}
