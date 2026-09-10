/**
 * The panel authorization chokepoint (Story S-117, spec §7.2).
 *
 * Every request that is not a static asset passes through here. This is the
 * SINGLE place authorization is decided, so a future page or route handler
 * cannot forget to add a check — the same "one enforceable control" posture the
 * codebase uses for the SD2 `server-only` guard and the ADR-001 mandate backstop.
 *
 * Flow (normative ordering, spec §7.2):
 *   1. `classifyRoute(pathname)` — pure (S-116). `public` short-circuits BEFORE
 *      any auth work (`/login` must be reachable with no session).
 *   2. Build the cookie-threading client (`createMiddlewareClient`) so a token
 *      refresh lands on the single response object we return.
 *   3. Verify identity with `getClaims()` — NEVER `getSession()` (AC8). The
 *      `getSession()` user object is not re-validated against the Auth server and
 *      is spoofable; it must not drive any authorization decision.
 *   4. On denial: `ui` → 302 to `/login?redirect=<encoded original path+query>`;
 *      `api` (incl. the SSE path) → 401 JSON with `content-type: application/json`.
 *   5. On success: return the COOKIE-HANDLER response object, never a fresh
 *      `NextResponse.next()` — a fresh response discards the refresh and causes
 *      intermittent logouts (AC7, spec §7.2 requirement 2).
 *
 * Fail-closed: any error from the auth call is treated as unauthenticated, and
 * an unknown route class already defaults to `ui` via `classifyRoute`.
 *
 * OQ1: `getClaims()` is awaited (async / network-agnostic) so the gate is correct
 * whether the project's signing keys are asymmetric (local JWKS verification) or
 * symmetric (a network call to the Auth server). The project uses ES256/EC keys
 * today (spec OQ1 resolved), so verification is local, but awaiting keeps the gate
 * correct if that ever changes.
 */

import { NextResponse, type NextRequest } from "next/server";

import { classifyRoute } from "@/lib/auth/route-policy";
import {
  createMiddlewareClient,
  type MiddlewareClientFactory,
} from "@/lib/supabase/auth-middleware";

/**
 * Build the login redirect target for a denied UI request as a RELATIVE path
 * (`/login?redirect=<encoded original path+query>`), carrying the original
 * path + query so the operator lands back where they were after signing in.
 *
 * A relative target is same-origin by definition, so it is immune to the host
 * the server binds to. Behind a reverse proxy like Fly, `request.nextUrl.origin`
 * can be the internal listener (`0.0.0.0:8080`) rather than the public host, so
 * an absolute redirect built from it can send the browser to an unreachable
 * origin. We therefore emit only the path + query.
 *
 * The `redirect` value is sanitized on the way OUT (S-119 login action, via
 * `safeRedirectTarget`); here we only capture it.
 */
function loginTargetFor(request: NextRequest): string {
  const originalTarget = request.nextUrl.pathname + request.nextUrl.search;
  return `/login?redirect=${encodeURIComponent(originalTarget)}`;
}

/** The `401` body for denied API/SSE requests (spec §6.2). */
function unauthorizedJson(): NextResponse {
  // `NextResponse.json` sets `content-type: application/json` — never an HTML
  // redirect, so `fetch`/`EventSource` see a clean failure (AC2).
  return NextResponse.json({ error: "UNAUTHORIZED" }, { status: 401 });
}

/**
 * The gate. Exported factory `createMiddleware` lets tests inject a fake auth
 * client; the default export used by Next.js binds the production client factory.
 *
 * @param makeClient injectable Supabase client factory (DI, spec §7.2).
 */
export function createMiddleware(makeClient?: MiddlewareClientFactory) {
  return async function middleware(request: NextRequest): Promise<NextResponse> {
    const policy = classifyRoute(request.nextUrl.pathname);

    // Public routes short-circuit before any auth work (spec §7.2 step 1).
    if (policy === "public") {
      return NextResponse.next();
    }

    // A single response object threads refreshed cookies to request + browser.
    const { supabase, response } = createMiddlewareClient(request, makeClient);

    // Authorization uses getClaims(), never getSession() (AC8). Fail-closed:
    // any thrown error is caught and treated as unauthenticated below.
    let authenticated = false;
    try {
      const { data, error } = await supabase.auth.getClaims();
      authenticated = !error && data?.claims != null;
    } catch {
      authenticated = false;
    }

    if (!authenticated) {
      return policy === "api"
        ? unauthorizedJson()
        : new NextResponse(null, { status: 302, headers: { Location: loginTargetFor(request) } });
    }

    // Success: return the cookie-handler response so a refreshed token reaches
    // the browser (AC7). MUST NOT be a fresh NextResponse.next() here.
    return response;
  };
}

/** Production middleware — bound to the default (real Supabase) client factory. */
const middleware = createMiddleware();
export default middleware;

/**
 * Matcher (spec §7.2): run on everything EXCEPT Next internals, the favicon, and
 * image assets, so the gate never fires on static files. Everything else — pages,
 * `/api/**`, and the SSE stream — is gated.
 */
export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
