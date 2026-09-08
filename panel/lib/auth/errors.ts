/**
 * Auth error taxonomy + user-facing message mapping (S-116, spec §8.2).
 *
 * The security-critical property here is **anti-enumeration (AC5)**: an unknown
 * email and a wrong password MUST be indistinguishable to the client. Both
 * collapse to a single `AUTH_INVALID_CREDENTIALS` code and the identical
 * user-facing message. The distinct underlying Supabase error is only ever
 * logged server-side — never returned to the browser.
 *
 * This module is pure (no I/O) so the mapping is unit-testable in isolation.
 */

export type AuthErrorCode =
  | "AUTH_INVALID_CREDENTIALS"
  | "AUTH_MISSING_FIELDS"
  | "AUTH_SERVICE_UNAVAILABLE"
  | "AUTH_CONFIG_ERROR"
  | "UNAUTHORIZED";

/**
 * User-facing messages, keyed by code. Intentionally generic — none reveals
 * whether an email exists, and none echoes any raw Supabase text.
 */
const USER_MESSAGES: Record<AuthErrorCode, string> = {
  // Wrong password AND unknown email map here — identical message (AC5).
  AUTH_INVALID_CREDENTIALS: "Invalid email or password.",
  AUTH_MISSING_FIELDS: "Enter your email and password.",
  AUTH_SERVICE_UNAVAILABLE: "Sign-in is temporarily unavailable. Try again.",
  // A configuration failure is a server fault; the user sees a generic message
  // while the detail is logged loudly server-side.
  AUTH_CONFIG_ERROR: "Sign-in is temporarily unavailable. Try again.",
  UNAUTHORIZED: "Your session has expired. Sign in again.",
};

/**
 * The single generic credential message. Exported so callers and tests can
 * assert the anti-enumeration invariant against one constant.
 */
export const INVALID_CREDENTIALS_MESSAGE = USER_MESSAGES.AUTH_INVALID_CREDENTIALS;

/** Returns the generic, safe-to-display message for a given auth error code. */
export function userMessageFor(code: AuthErrorCode): string {
  return USER_MESSAGES[code];
}

/**
 * Shape of a Supabase auth error as far as we rely on it. `@supabase/supabase-js`
 * surfaces `AuthApiError` with a numeric `status`; we read only what we need and
 * never forward its `message` to the client.
 */
interface SupabaseAuthErrorLike {
  status?: number;
  code?: string;
  message?: string;
}

/**
 * Maps a raw Supabase sign-in error into an internal code. Both "invalid login
 * credentials" (wrong password) and "user not found" (unknown email) collapse
 * to `AUTH_INVALID_CREDENTIALS` so the two are indistinguishable (AC5). A 5xx /
 * network-shaped failure maps to `AUTH_SERVICE_UNAVAILABLE`.
 *
 * @param error the error thrown/returned by `signInWithPassword`.
 */
export function classifySignInError(
  error: SupabaseAuthErrorLike | null | undefined,
): AuthErrorCode {
  if (!error) {
    // No error object but the caller decided sign-in failed: treat as invalid
    // credentials rather than leaking an unexpected state.
    return "AUTH_INVALID_CREDENTIALS";
  }

  const status = typeof error.status === "number" ? error.status : undefined;

  // Service/transport failures: 5xx, 429, or no status at all (network error).
  if (status === undefined || status >= 500 || status === 429) {
    return "AUTH_SERVICE_UNAVAILABLE";
  }

  // Everything else in the 4xx credential range — 400 invalid credentials, 401,
  // 403, 404 user-not-found — is deliberately collapsed to the generic code.
  return "AUTH_INVALID_CREDENTIALS";
}
