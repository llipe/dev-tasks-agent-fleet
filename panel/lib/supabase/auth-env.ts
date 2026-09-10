/**
 * Auth-client environment configuration (S-116).
 *
 * The auth clients (`auth-server.ts`, `browser.ts`) use the **anon** key over a
 * cookie-backed session — a different credential family from the service-role
 * data client in `server.ts` (SA1, D15). Because the browser client needs these
 * values, they are the `NEXT_PUBLIC_`-prefixed, publishable-by-design pair:
 *
 *   - `NEXT_PUBLIC_SUPABASE_URL`
 *   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
 *
 * The service-role key MUST NOT be exposed through any `NEXT_PUBLIC_` variable;
 * it is read only by `server.ts` from server-only vars. This module deliberately
 * reads only the anon pair.
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
  anonKey: string;
}

/**
 * Reads and validates the anon-key Supabase configuration used by the auth
 * clients. Exported so a process can assert its configuration eagerly. Throws
 * `AuthConfigError` on any missing/blank/malformed value.
 */
export function readAuthEnv(env: NodeJS.ProcessEnv = process.env): AuthEnv {
  const url = env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

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

  if (!anonKey || anonKey.trim() === "") {
    throw new AuthConfigError(
      "NEXT_PUBLIC_SUPABASE_ANON_KEY is not set. The auth client requires the anon (publishable) key.",
    );
  }

  return { url, anonKey };
}
