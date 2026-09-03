/**
 * SD2 — server-only Supabase client factory.
 *
 * This module holds the service role key, which bypasses RLS (D15). It MUST
 * never enter a client bundle. Two guards enforce that:
 *
 *  1. **`import "server-only"` (hard, build-time).** If this module is ever
 *     pulled into a client component's bundle, `next build` fails with a
 *     precise React Server Components error that no `eslint-disable` can
 *     suppress. This is the real guarantee.
 *  2. **SD2 ESLint rule (fast, lint-time hint).** `no-restricted-imports` in
 *     `panel/eslint.config.mjs` flags an import of this module from a client
 *     component (`components/**`); `tests/unit/eslint-server-import.test.ts`
 *     proves it fires. It is scoped to the client component tree, not the
 *     server contexts (Server Components / route handlers) that import this
 *     module on purpose — those are guarded by `server-only` instead.
 *
 * There is no `NEXT_PUBLIC_SUPABASE_*` variable anywhere — the URL and key are
 * read from server-only environment variables.
 *
 * A fresh client is created per request rather than module-scoped: run routes
 * are `force-dynamic` (no request should share a client instance across the
 * server), and a per-request factory keeps the boundary explicit.
 */

import "server-only";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

/**
 * Thrown at startup/first-use when a required Supabase env var is missing or
 * malformed. Failing fast with a named error beats yielding an `undefined`
 * client that null-dereferences later on an unrelated line (EC-12).
 */
export class SupabaseConfigError extends Error {
  readonly code = "SUPABASE_CONFIG_ERROR";
  constructor(message: string) {
    super(message);
    this.name = "SupabaseConfigError";
  }
}

interface SupabaseEnv {
  url: string;
  serviceRoleKey: string;
}

/**
 * Reads and validates the server-only Supabase configuration. Exported so a
 * process can assert its configuration eagerly (e.g. a health check) rather
 * than discovering a missing variable on the first query.
 */
export function readSupabaseEnv(env: NodeJS.ProcessEnv = process.env): SupabaseEnv {
  const url = env.SUPABASE_URL;
  const serviceRoleKey = env.SUPABASE_SERVICE_ROLE_KEY;

  if (!url || url.trim() === "") {
    throw new SupabaseConfigError(
      "SUPABASE_URL is not set. The server-side Supabase client cannot be created without it.",
    );
  }
  // Reject a value that is present but not a parseable URL, so a typo fails
  // here rather than as an opaque fetch error on the first query.
  try {
    new URL(url);
  } catch {
    throw new SupabaseConfigError(`SUPABASE_URL is not a valid URL: received "${url}".`);
  }

  if (!serviceRoleKey || serviceRoleKey.trim() === "") {
    throw new SupabaseConfigError(
      "SUPABASE_SERVICE_ROLE_KEY is not set. The server-side client requires the service role key (server-only, never exposed to the browser).",
    );
  }

  return { url, serviceRoleKey };
}

/**
 * Creates a per-request server-side Supabase client using the service role
 * key. Never call this from a client component (see the module note). Throws
 * `SupabaseConfigError` if the environment is not correctly configured.
 */
export function createServerClient(env: NodeJS.ProcessEnv = process.env): SupabaseClient {
  const { url, serviceRoleKey } = readSupabaseEnv(env);
  return createClient(url, serviceRoleKey, {
    auth: {
      // No user sessions in v1 (D16). The service role key is a static
      // credential; disable all client-side session/token behavior.
      autoRefreshToken: false,
      persistSession: false,
    },
  });
}
