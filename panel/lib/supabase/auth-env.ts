/**
 * Auth-client environment configuration (S-116; publishable-key migration #172).
 *
 * The auth clients (`auth-server.ts`, `browser.ts`) use the **publishable**
 * client key over a cookie-backed session — a different credential family from
 * the service-role data client in `server.ts` (SA1, D15). Because the browser
 * client needs these values, they are the `NEXT_PUBLIC_`-prefixed, publishable
 * pair:
 *
 *   - `NEXT_PUBLIC_SUPABASE_URL`
 *   - `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`  (preferred, `sb_publishable_…`)
 *   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`         (legacy fallback, deprecated)
 *
 * Supabase now treats the classic `anon` JWT as the *legacy* client credential
 * and recommends the new publishable API key. This module resolves the
 * publishable name first and falls back to the legacy anon name for one release
 * (emitting a one-time deprecation warning) so local/CI/deploy environments can
 * cut over independently without a flag day. Once every environment carries the
 * publishable key, the anon fallback is removed in a follow-up.
 *
 * The service-role key MUST NOT be exposed through any `NEXT_PUBLIC_` variable;
 * it is read only by `server.ts` from server-only vars. This module deliberately
 * reads only the publishable/anon pair.
 *
 * Follows the fail-fast posture of `readSupabaseEnv` in `server.ts`: a missing,
 * blank, or malformed value throws a named `AuthConfigError` at read time rather
 * than yielding an `undefined` that null-dereferences later on an unrelated line.
 */

/**
 * Thrown when a required `NEXT_PUBLIC_SUPABASE_*` variable is missing, blank, or
 * malformed. Named so callers can distinguish an auth-config failure from a data
 * client (`SupabaseConfigError`) failure.
 */
export class AuthConfigError extends Error {
  readonly code = "AUTH_CONFIG_ERROR";
  constructor(message: string) {
    super(message);
    this.name = "AuthConfigError";
  }
}

export interface AuthEnv {
  url: string;
  /** The resolved publishable client key (publishable name preferred, legacy anon as fallback). */
  publishableKey: string;
  /**
   * Backwards-compatible alias for `publishableKey`. Existing callers that
   * destructure `anonKey` keep working; both fields hold the same resolved key.
   * @deprecated Prefer `publishableKey`.
   */
  anonKey: string;
}

/** Module-level guard so the legacy-fallback deprecation warning is emitted once. */
let legacyFallbackWarned = false;

function nonBlank(value: string | undefined): string | undefined {
  return value && value.trim() !== "" ? value : undefined;
}

/**
 * Reads and validates the publishable-key Supabase configuration used by the
 * auth clients. Exported so a process can assert its configuration eagerly.
 * Resolves `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` first, falls back to the legacy
 * `NEXT_PUBLIC_SUPABASE_ANON_KEY` with a one-time deprecation warning, and throws
 * `AuthConfigError` only when neither is present (or the URL is missing/malformed).
 */
export function readAuthEnv(env: NodeJS.ProcessEnv = process.env): AuthEnv {
  const url = env.NEXT_PUBLIC_SUPABASE_URL;

  if (!url || url.trim() === "") {
    throw new AuthConfigError(
      "NEXT_PUBLIC_SUPABASE_URL is not set. The auth Supabase client cannot be created without it.",
    );
  }
  try {
    // Reject a present-but-unparseable value here rather than as an opaque
    // fetch error on the first auth call.
    new URL(url);
  } catch {
    throw new AuthConfigError(`NEXT_PUBLIC_SUPABASE_URL is not a valid URL: received "${url}".`);
  }

  const publishable = nonBlank(env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY);
  const legacyAnon = nonBlank(env.NEXT_PUBLIC_SUPABASE_ANON_KEY);

  if (publishable) {
    return { url, publishableKey: publishable, anonKey: publishable };
  }

  if (legacyAnon) {
    if (!legacyFallbackWarned) {
      legacyFallbackWarned = true;
      // eslint-disable-next-line no-console
      console.warn(
        "[auth-env] NEXT_PUBLIC_SUPABASE_ANON_KEY is deprecated. Supabase treats the classic anon " +
          "JWT as a legacy client credential; set NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY (sb_publishable_…) " +
          "instead. The anon fallback will be removed in a follow-up release.",
      );
    }
    return { url, publishableKey: legacyAnon, anonKey: legacyAnon };
  }

  throw new AuthConfigError(
    "Neither NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY nor the legacy NEXT_PUBLIC_SUPABASE_ANON_KEY is set. " +
      "The auth client requires the publishable client key.",
  );
}
