/**
 * `safeRedirectTarget` — open-redirect prevention for the post-login redirect
 * (S-116, spec §8.1, FR11/AC4).
 *
 * A total, never-throwing security guard: whatever the input, the return value
 * is always a same-origin **relative** path. Mirrors the posture of
 * `isSafeArtifactUrl` (S-109) — an attacker-controlled `?redirect=` value can
 * never send the operator to an off-origin URL, and can never throw.
 *
 * Rules, in order (spec §8.1):
 *   1. Missing/empty → `/`.
 *   2. MUST start with a single `/`, and MUST NOT start with `//` (protocol-relative).
 *   3. MUST NOT contain `://`, and MUST NOT parse as an absolute URL.
 *   4. MUST NOT be `/login` (avoids a redirect loop back to the form).
 *   5. Control characters / newlines (header-injection shapes) → `/`.
 *   6. Otherwise return the path (preserving query + hash).
 */

const DEFAULT_TARGET = "/";

/**
 * Coerces a raw, possibly attacker-controlled redirect value into a safe
 * same-origin relative path. Never throws; always returns a local path.
 *
 * @param raw the untrusted `redirect` value (query param, form field, etc.).
 */
export function safeRedirectTarget(raw: unknown): string {
  // Rule 1 — only a non-empty string is considered.
  if (typeof raw !== "string") {
    return DEFAULT_TARGET;
  }
  const value = raw;
  if (value.length === 0) {
    return DEFAULT_TARGET;
  }

  // Rule 5 — reject control chars / newlines (CR, LF, tab, NUL, and the rest of
  // the C0 range plus DEL). These are header-injection and path-smuggling shapes.
  if (/[\u0000-\u001f\u007f]/.test(value)) {
    return DEFAULT_TARGET;
  }

  // Rule 2 — must be a rooted path, and must not be protocol-relative (`//host`).
  // Also reject the backslash variant `/\` that some browsers treat as `//`.
  if (!value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) {
    return DEFAULT_TARGET;
  }

  // Rule 3 — must not smuggle a scheme, and must not parse as an absolute URL.
  if (value.includes("://")) {
    return DEFAULT_TARGET;
  }
  // A rooted path is not a valid absolute URL on its own, so if `new URL(value)`
  // succeeds without a base, the value carried an absolute form — reject it.
  try {
    new URL(value);
    return DEFAULT_TARGET;
  } catch {
    // Expected for a legitimate relative path — continue.
  }

  // Rule 4 — never redirect back to the login form itself (loop). Compare the
  // path portion only, so `/login?x=1` is also rejected.
  const pathOnly = value.split(/[?#]/, 1)[0];
  if (pathOnly === "/login") {
    return DEFAULT_TARGET;
  }

  // Rule 6 — safe relative path; preserve query + hash.
  return value;
}
