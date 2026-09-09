/**
 * Middleware cookie-threading Supabase auth client (S-117, spec §7.2).
 *
 * The middleware (`middleware.ts`) is the only place the panel can refresh the
 * auth token, because Next.js Server Components cannot write cookies. To make a
 * refresh actually reach the browser, the refreshed `Set-Cookie` must land on a
 * SINGLE `NextResponse` object that the middleware then returns — while the same
 * cookies are mirrored onto the request so any downstream Server Component in the
 * same pass reads the refreshed session.
 *
 * The subtle failure this design prevents (spec §7.2 requirement 2): constructing
 * a fresh `NextResponse.next()` AFTER the auth call discards the refresh and
 * causes intermittent, random logouts. `createMiddlewareClient` returns the one
 * response that carries the cookies, and the middleware MUST return exactly that
 * object on the success path.
 *
 * The Supabase client factory is INJECTABLE (same dependency-injection posture as
 * `lib/sse/relay.ts`), so the gate can be unit-tested with a fake auth client and
 * no live Supabase. Production callers use the default factory, which builds an
 * anon-key `@supabase/ssr` server client bound to this request/response cookie
 * pair. Auth uses the anon key only — never the service-role data client (SA1).
 */

import { createServerClient } from "@supabase/ssr";
import { type SupabaseClient } from "@supabase/supabase-js";
import { NextResponse, type NextRequest } from "next/server";
import { readAuthEnv } from "./auth-env";

/**
 * The slice of `@supabase/ssr` cookie-adapter behavior this factory needs. The
 * production client is a full `SupabaseClient`; tests inject a fake exposing only
 * `auth.getClaims`, so the factory is typed against that minimal surface.
 */
export type MiddlewareAuthClient = Pick<SupabaseClient, "auth"> | SupabaseClient;

/**
 * A factory that, given the request and the mutable response, produces the auth
 * client used for the authorization decision. Injecting this is what makes the
 * gate testable without a live Supabase (spec §7.2, testing requirement).
 */
export type MiddlewareClientFactory = (
  request: NextRequest,
  response: NextResponse,
) => MiddlewareAuthClient;

/** What `createMiddlewareClient` returns: the client plus the response to return. */
export interface MiddlewareClientBundle {
  supabase: MiddlewareAuthClient;
  response: NextResponse;
}

/**
 * The default, production Supabase client factory. Builds an anon-key server
 * client whose cookie adapter writes refreshed cookies onto BOTH the request
 * (for downstream) and the passed-in response (for the browser). Never touches
 * the service-role client.
 */
export const defaultMiddlewareClientFactory: MiddlewareClientFactory = (request, response) => {
  const { url, anonKey } = readAuthEnv();
  return createServerClient(url, anonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        // Mirror onto the request so a downstream Server Component in this same
        // pass reads the refreshed session...
        for (const { name, value } of cookiesToSet) {
          request.cookies.set(name, value);
        }
        // ...and onto the response so the refreshed Set-Cookie reaches the
        // browser. This is the single response the middleware returns.
        for (const { name, value, options } of cookiesToSet) {
          response.cookies.set(name, value, options);
        }
      },
    },
  });
};

/**
 * Create the middleware auth client and the single response that carries any
 * refreshed cookies.
 *
 * The response starts as `NextResponse.next({ request })` — a pass-through that
 * forwards the (possibly cookie-mutated) request downstream. The middleware
 * returns this object verbatim on the success path so the token refresh is not
 * discarded (spec §7.2 requirement 2).
 *
 * @param request the incoming request.
 * @param makeClient injectable client factory; defaults to the production one.
 */
export function createMiddlewareClient(
  request: NextRequest,
  makeClient: MiddlewareClientFactory = defaultMiddlewareClientFactory,
): MiddlewareClientBundle {
  const response = NextResponse.next({ request });
  const supabase = makeClient(request, response);
  return { supabase, response };
}
