/**
 * The panel authorization chokepoint (Story S-117, spec §7.2).
 *
 * issue 217 (ADR-008): this file was renamed `middleware.ts` → `proxy.ts` for Next
 * 16, which deprecates `middleware` in favor of `proxy`. The one material
 * behavioral consequence is that `proxy` runs on the **Node.js runtime** (the
 * former `middleware.ts` declared no `runtime` and therefore ran on Edge). Every
 * other behavior is preserved verbatim — this file is the panel's security
 * boundary (ADR-007), so any behavior difference other than the runtime move and
 * the D-15 timeout below is a regression, not a change.
 *
 * Every request that is not a static asset passes through here. This is the
 * SINGLE place authorization is decided, so a future page or route handler
 * cannot forget to add a check — the same "one enforceable control" posture the
 * codebase uses for the SD2 `server-only` guard and the ADR-001 mandate backstop.
 *
 * Flow (normative ordering, spec §7.2):
 *   1. `classifyRoute(pathname)` — pure (S-116). `public` short-circuits BEFORE
 *      any auth work (`/login` must be reachable with no session).
 *   2. The `internal` class (`/api/internal/**`, S-153) declines the session gate
 *      and lets the request reach the handler, which enforces its own fail-closed
 *      shared-secret check. The gate MUST NOT authorize here — it only skips the
 *      session check; it never returns a 200/success body for this class.
 *   3. Build the cookie-threading client (`createMiddlewareClient`) so a token
 *      refresh lands on the single response object we return.
 *   4. Verify identity with `getClaims()` — NEVER `getSession()` (AC8). The
 *      `getSession()` user object is not re-validated against the Auth server and
 *      is spoofable; it must not drive any authorization decision.
 *   5. On denial: `ui` → 302 to `/login?redirect=<encoded original path+query>`;
 *      `api` (incl. the SSE path) → 401 JSON with `content-type: application/json`.
 *   6. On success: return the COOKIE-HANDLER response object, never a fresh
 *      `NextResponse.next()` — a fresh response discards the refresh and causes
 *      intermittent logouts (AC7, spec §7.2 requirement 2).
 *
 * Fail-closed: any error from the auth call is treated as unauthenticated, and
 * an unknown route class already defaults to `ui` via `classifyRoute`.
 *
 * OQ1 / D-15: `getClaims()` is awaited (async / network-agnostic) so the gate is
 * correct whether the project's signing keys are asymmetric (local JWKS
 * verification) or symmetric (a network call to the Auth server). The project
 * uses ES256/EC keys today (spec OQ1 resolved), so verification is local. The
 * Edge → Node move removes the platform's implicit per-request time budget, so a
 * hung `getClaims()` is now raced against a bounded timeout (default 5s): on
 * timeout the gate fails CLOSED exactly like an auth error (UI → 302, API/SSE →
 * 401). The timer is always cleared on settle so no handle is left open.
 */

import { NextResponse, type NextRequest } from "next/server";

import { classifyRoute } from "@/lib/auth/route-policy";
import {
  createMiddlewareClient,
  type MiddlewareClientFactory,
} from "@/lib/supabase/auth-middleware";

/**
 * Default fail-closed bound for the identity check (D-15). Injectable via
 * `createMiddleware` so tests can shrink it; production uses this value.
 */
export const DEFAULT_GETCLAIMS_TIMEOUT_MS = 5000;

/**
 * Build the login redirect URL for a denied UI request, carrying the original
 * path + query as an encoded `redirect` param so the operator lands back where
 * they were after signing in.
 *
 * Uses `request.nextUrl.clone()` rather than a bare relative string: a Next.js
 * proxy redirect goes through `NextResponse.redirect`, which re-parses the
 * `Location` as an absolute `URL` — a relative `Location` throws
 * `TypeError: Invalid URL` in the proxy pipeline. `nextUrl` is Next's
 * proxy-normalized request URL (it reflects the forwarded host, unlike the raw
 * `request.url` that binds to the internal `0.0.0.0:8080` listener on Fly), so
 * cloning it and only replacing the path + query yields a same-origin redirect
 * that is correct both locally and behind the proxy. (This remains true on the
 * Node runtime: the redirect is built from `nextUrl`, never raw `request.url`.)
 *
 * The `redirect` value is sanitized on the way OUT (S-119 login action, via
 * `safeRedirectTarget`); here we only capture it.
 */
function loginUrlFor(request: NextRequest): URL {
  const originalTarget = request.nextUrl.pathname + request.nextUrl.search;
  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/login";
  loginUrl.search = "";
  loginUrl.searchParams.set("redirect", originalTarget);
  return loginUrl;
}

/** The `401` body for denied API/SSE requests (spec §6.2). */
function unauthorizedJson(): NextResponse {
  // `NextResponse.json` sets `content-type: application/json` — never an HTML
  // redirect, so `fetch`/`EventSource` see a clean failure (AC2).
  return NextResponse.json({ error: "UNAUTHORIZED" }, { status: 401 });
}

/** A sentinel the timeout branch resolves to so a hung call fails closed. */
const TIMED_OUT = Symbol("getClaims-timeout");

/**
 * Race `getClaims()` against a bounded timeout (D-15). Returns `true` only on a
 * resolved, error-free result that carries claims; a thrown error, a resolved
 * error, missing claims, OR a timeout all return `false` (fail-closed). The
 * timer is ALWAYS cleared on settle (resolve, reject, or timeout) so no open
 * handle is left behind — critical on the Node runtime.
 */
async function isAuthenticatedWithin(
  getClaims: () => Promise<{
    data: { claims: Record<string, unknown> | null } | null;
    error: { message: string } | null;
  }>,
  timeoutMs: number,
): Promise<boolean> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<typeof TIMED_OUT>((resolve) => {
    timer = setTimeout(() => resolve(TIMED_OUT), timeoutMs);
  });
  try {
    const result = await Promise.race([getClaims(), timeout]);
    if (result === TIMED_OUT) {
      return false; // hung auth server → deny (fail-closed)
    }
    const { data, error } = result;
    return !error && data?.claims != null;
  } catch {
    return false; // thrown error → deny (fail-closed)
  } finally {
    if (timer !== undefined) {
      clearTimeout(timer);
    }
  }
}

/**
 * The gate. Exported factory `createMiddleware` lets tests inject a fake auth
 * client and a shorter timeout; the default export (and the named `proxy`
 * export Next 16 recognizes) bind the production client factory and the 5s
 * default bound.
 *
 * @param makeClient injectable Supabase client factory (DI, spec §7.2).
 * @param timeoutMs  injectable fail-closed `getClaims()` bound (D-15).
 */
export function createMiddleware(
  makeClient?: MiddlewareClientFactory,
  timeoutMs: number = DEFAULT_GETCLAIMS_TIMEOUT_MS,
) {
  return async function proxy(request: NextRequest): Promise<NextResponse> {
    const policy = classifyRoute(request.nextUrl.pathname);

    // Public routes short-circuit before any auth work (spec §7.2 step 1).
    if (policy === "public") {
      return NextResponse.next();
    }

    // Internal scheduler routes (S-153) are NOT session-gated — the caller is
    // pg_cron via pg_net, which holds no session cookie. The gate lets the
    // request reach the handler, which enforces a fail-closed, constant-time
    // shared-secret check itself (SD-A1). Critically, the gate does NOT
    // authorize the request here — it only declines to apply the session gate;
    // authorization is the handler's secret check, never an open pass. We MUST
    // NOT return a 200 or any success body here.
    if (policy === "internal") {
      return NextResponse.next();
    }

    // A single response object threads refreshed cookies to request + browser.
    const { supabase, response } = createMiddlewareClient(request, makeClient);

    // Authorization uses getClaims(), never getSession() (AC8). Fail-closed:
    // any thrown error, resolved error, or TIMEOUT (D-15) denies below.
    const authenticated = await isAuthenticatedWithin(() => supabase.auth.getClaims(), timeoutMs);

    if (!authenticated) {
      return policy === "api"
        ? unauthorizedJson()
        : NextResponse.redirect(loginUrlFor(request), { status: 302 });
    }

    // Success: return the cookie-handler response so a refreshed token reaches
    // the browser (AC7). MUST NOT be a fresh NextResponse.next() here.
    return response;
  };
}

/**
 * Production gate — bound to the default (real Supabase) client factory and the
 * 5s fail-closed timeout. Next 16 accepts a `proxy.ts` file that exports either
 * a default function or a named `proxy` function; we provide both so the
 * convention is explicit and the default-export form keeps working verbatim.
 */
const proxy = createMiddleware();
export { proxy };
export default proxy;

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
