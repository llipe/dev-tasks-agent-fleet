/**
 * Browser (client-side) Supabase auth client (S-116, spec §7.1; publishable-key
 * migration #172).
 *
 * Uses the **publishable** client key only — never the service-role key. This
 * client is safe to run in the browser: the publishable key is RLS-bound and RLS
 * stays deny-all (D11), so authenticating a user grants no row access. It exists
 * so client components can observe/refresh the user session; all data reads still
 * go through the server-only service-role client in `server.ts` (SA1).
 *
 * No `import "server-only"` here — this module is meant for the browser bundle.
 * It reads only the `NEXT_PUBLIC_SUPABASE_*` pair via `readAuthEnv` (publishable
 * key preferred, legacy anon key as a deprecated fallback); it holds no reference
 * to `SUPABASE_SERVICE_ROLE_KEY` or `lib/supabase/server`.
 */

import { createBrowserClient } from "@supabase/ssr";
import { type SupabaseClient } from "@supabase/supabase-js";
import { readAuthEnv } from "./auth-env";

/**
 * Creates a cookie-backed browser Supabase client using the publishable key.
 * `@supabase/ssr` manages session cookies so the browser and server agree on
 * auth state. Throws `AuthConfigError` if the public env vars are missing.
 */
export function createBrowserAuthClient(): SupabaseClient {
  const { url, publishableKey } = readAuthEnv();
  return createBrowserClient(url, publishableKey);
}
