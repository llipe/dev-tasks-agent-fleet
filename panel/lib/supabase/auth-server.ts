/**
 * Cookie-backed server-side Supabase auth client (S-116, spec §7.1).
 *
 * Uses the **anon** (publishable) key with a Next.js cookie store, so Server
 * Components, route handlers, and server actions can read the current user
 * session and issue sign-in/out. This is a DIFFERENT client family from the
 * service-role data client in `server.ts` (SA1, D15): auth logic MUST NOT use
 * the service-role client, and data queries MUST NOT use this one.
 *
 * `import "server-only"` guards it out of any client bundle. The anon key is not
 * itself a secret (it is the publishable key), but binding the cookie adapter to
 * a Next.js server cookie store means this factory only makes sense server-side.
 *
 * Server Components cannot write cookies; when this client is used from a pure
 * Server Component render, cookie *writes* are swallowed (token refresh is owned
 * by the middleware, S-117). Route handlers and server actions CAN write, so
 * sign-in/out set cookies correctly there.
 */

import "server-only";
import { createServerClient } from "@supabase/ssr";
import { type SupabaseClient } from "@supabase/supabase-js";
import { readAuthEnv } from "./auth-env";

/**
 * The minimal cookie-store surface this factory needs. Matches the shape of the
 * object returned by `next/headers` `cookies()` (async in Next 15). Accepting an
 * interface rather than importing `next/headers` keeps the factory unit-testable
 * with a fake store.
 */
export interface CookieStore {
  getAll(): Array<{ name: string; value: string }>;
  set(name: string, value: string, options?: Record<string, unknown>): void;
}

/**
 * Creates a cookie-backed anon-key server client bound to the given cookie
 * store. Cookie writes that are illegal in the current context (a pure Server
 * Component render) are caught and ignored — middleware owns refresh — so a
 * read-only render never throws.
 *
 * @param cookieStore the request cookie store (e.g. from `await cookies()`).
 */
export function createAuthServerClient(cookieStore: CookieStore): SupabaseClient {
  const { url, anonKey } = readAuthEnv();
  return createServerClient(url, anonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          for (const { name, value, options } of cookiesToSet) {
            cookieStore.set(name, value, options);
          }
        } catch {
          // Called from a Server Component that cannot set cookies. Safe to
          // ignore: the middleware refreshes the session on the next request.
        }
      },
    },
  });
}
