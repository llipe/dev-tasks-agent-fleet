import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { createAuthServerClient } from "@/lib/supabase/auth-server";

/**
 * Logout route — `POST /api/auth/logout` (Story S-120, spec §8 / PRD AC6).
 *
 * POST-ONLY by construction. A GET logout is CSRF-triggerable and can be fired
 * by a prefetcher or link scanner, logging the operator out unexpectedly — so
 * this module deliberately exports `POST` and nothing else. There is no `GET`
 * export, so `GET /api/auth/logout` is a 405, not a logout.
 *
 * Route-segment config is declared **inline** (S-104 audit D4 / §12): a logout
 * response carries cleared `Set-Cookie` headers and must never be cached or
 * statically rendered.
 *
 * Reachability (the trap this route is built around): the auth gate (S-117)
 * classifies `/api/auth/logout` as `public` (S-116 route-policy) precisely so
 * this handler runs even when the session is expiring or already invalid. A
 * session-ENDING action must not require a perfectly-valid session — otherwise
 * the gate would 401 the POST before it could clear cookies, and logout would
 * be self-defeating.
 *
 * Flow:
 *   1. Build the cookie-backed anon auth client (S-116). In a route handler the
 *      cookie store is writable, so `signOut` clears the session cookies; Next
 *      merges those writes onto the response we return.
 *   2. `signOut` — best-effort. Idempotent: with no session it is a no-op, and
 *      any error (missing session, transient auth failure) is swallowed. Ending
 *      a session must never be blockable by an auth error, so we never 500.
 *   3. Redirect (302) to `/login`.
 */

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";
export const runtime = "nodejs";

export async function POST(): Promise<NextResponse> {
  try {
    const cookieStore = await cookies();
    const supabase = createAuthServerClient(cookieStore);
    // Clears the session cookies via the SSR cookie adapter. Idempotent — a
    // no-session call resolves without effect; we do not inspect the result.
    await supabase.auth.signOut();
  } catch {
    // A thrown/transient auth failure must not prevent the operator from
    // ending their session. Fall through to the redirect regardless.
  }

  // 302 to the public login screen via a RELATIVE Location (`/login`).
  //
  // A relative redirect is same-origin by definition, so it is immune to the
  // host the server binds to. Building an absolute URL from `request.url`
  // (`new URL("/login", request.url)`) is WRONG behind a reverse proxy like
  // Fly: `request.url` reflects the internal listener (`HOSTNAME=0.0.0.0:8080`
  // from fly.toml), not the public host the browser used, so the operator was
  // redirected to the unreachable `http://0.0.0.0:8080/login`. `request.url`
  // does not carry the forwarded host, and this route deliberately depends on
  // nothing from the request, so it no longer takes a `request` argument.
  return new NextResponse(null, { status: 302, headers: { Location: "/login" } });
}
