import { NextRequest } from "next/server";
import { describe, expect, it, vi } from "vitest";

import { createMiddleware, config } from "@/middleware";
import type { MiddlewareAuthClient, MiddlewareClientFactory } from "@/lib/supabase/auth-middleware";

/**
 * S-117 middleware gate — Layer 2 behavior with an INJECTED fake auth client
 * (spec §7.2, §14.2). No live Supabase: the gate accepts an injectable client
 * factory (the same dependency-injection posture as `lib/sse/relay.ts`), so the
 * 302-vs-401 split, cookie preservation, and fail-closed behavior are all
 * exercised deterministically.
 *
 * The fake models `getClaims()` only — the one call the authorization decision
 * is allowed to make (AC8). A fake whose factory also writes a refreshed cookie
 * onto the response lets us prove the success path returns the cookie-carrying
 * response (AC7).
 */

type ClaimsResult = {
  data: { claims: Record<string, unknown> | null } | null;
  error: { message: string } | null;
};

/** Build a fake client factory returning the given getClaims() result. */
function fakeFactory(
  result: ClaimsResult | (() => Promise<ClaimsResult>),
  opts: { refreshCookie?: { name: string; value: string } } = {},
): MiddlewareClientFactory {
  return (_request, response) => {
    // Simulate a token refresh writing a cookie onto the threaded response.
    if (opts.refreshCookie) {
      response.cookies.set(opts.refreshCookie.name, opts.refreshCookie.value);
    }
    const getClaims = typeof result === "function" ? result : () => Promise.resolve(result);
    const client: Pick<MiddlewareAuthClient, "auth"> = {
      // Only getClaims is modeled — the gate must never call anything else.
      auth: { getClaims } as unknown as MiddlewareAuthClient["auth"],
    };
    return client as MiddlewareAuthClient;
  };
}

const NO_SESSION: ClaimsResult = { data: { claims: null }, error: null };
const VALID_SESSION: ClaimsResult = {
  data: { claims: { sub: "user-1", role: "authenticated" } },
  error: null,
};
const AUTH_ERROR: ClaimsResult = { data: null, error: { message: "boom" } };

function req(path: string): NextRequest {
  return new NextRequest(new URL(path, "https://panel.example.com"));
}

/**
 * Parse a redirect `Location` header. The gate emits a RELATIVE location
 * The gate redirects with `NextResponse.redirect(request.nextUrl.clone())`, so
 * the `Location` is an ABSOLUTE same-origin URL. (A middleware redirect is
 * re-parsed by Next as an absolute URL, so a bare relative Location throws
 * `Invalid URL` — the relative-Location form is only correct in the logout
 * *route handler*, not here.) `nextUrl` is Next's proxy-normalized request URL,
 * so it carries the real forwarded host rather than the internal 0.0.0.0
 * listener. Parsing with a dummy base tolerates either shape.
 */
function parseLocation(res: Response): URL {
  const loc = res.headers.get("location");
  if (loc === null) throw new Error("no Location header");
  return new URL(loc, "http://relative.invalid");
}

describe("middleware auth gate — denial paths", () => {
  it("unauthenticated UI route → 302 to /login with the original path as redirect (AC1)", async () => {
    const mw = createMiddleware(fakeFactory(NO_SESSION));
    const res = await mw(req("/"));

    expect(res.status).toBe(302); // NextResponse.redirect with explicit 302 (spec §6.2)
    const location = res.headers.get("location");
    expect(location).not.toBeNull();
    // Regression: the redirect must be SAME-ORIGIN as the request and must never
    // leak the internal 0.0.0.0 bind address (built from nextUrl, not the raw
    // request.url). req() builds against https://panel.example.com.
    expect(location as string).not.toContain("0.0.0.0");
    const url = parseLocation(res);
    expect(url.origin).toBe("https://panel.example.com");
    expect(url.pathname).toBe("/login");
    expect(url.searchParams.get("redirect")).toBe("/");
    // Never an HTML/JSON body swap — it is a redirect, not a 401.
    expect(res.headers.get("content-type")).not.toBe("application/json");
  });

  it("unauthenticated deeply-nested UI route preserves the full path in redirect", async () => {
    const mw = createMiddleware(fakeFactory(NO_SESSION));
    const res = await mw(req("/agents/dependency-update/history"));
    const url = parseLocation(res);
    expect(url.searchParams.get("redirect")).toBe("/agents/dependency-update/history");
  });

  it("redirect param round-trips a UI path WITH query (AC1)", async () => {
    const mw = createMiddleware(fakeFactory(NO_SESSION));
    const res = await mw(req("/runs/abc?tab=logs&level=error"));
    const url = parseLocation(res);
    // The query is preserved on the captured original target.
    expect(url.searchParams.get("redirect")).toBe("/runs/abc?tab=logs&level=error");
  });

  it("unauthenticated /api route → 401 JSON with content-type application/json (AC2)", async () => {
    const mw = createMiddleware(fakeFactory(NO_SESSION));
    const res = await mw(req("/api/runs/x/events/stream"));

    expect(res.status).toBe(401);
    expect(res.headers.get("content-type")).toContain("application/json");
    expect(res.headers.get("location")).toBeNull(); // never an HTML redirect
    await expect(res.json()).resolves.toEqual({ error: "UNAUTHORIZED" });
  });

  it("unauthenticated SSE stream path is treated as api → 401 JSON (AC2)", async () => {
    const mw = createMiddleware(fakeFactory(NO_SESSION));
    const res = await mw(req("/api/runs/11111111-1111-1111-1111-111111111111/events/stream"));
    expect(res.status).toBe(401);
    expect(res.headers.get("content-type")).toContain("application/json");
  });

  it("`/api` exactly is classified api → 401 JSON", async () => {
    const mw = createMiddleware(fakeFactory(NO_SESSION));
    const res = await mw(req("/api"));
    expect(res.status).toBe(401);
    expect(res.headers.get("content-type")).toContain("application/json");
  });
});

describe("middleware auth gate — success path", () => {
  it("valid session on a UI route passes through (AC7)", async () => {
    const mw = createMiddleware(fakeFactory(VALID_SESSION));
    const res = await mw(req("/"));
    // Pass-through NextResponse.next() carries the x-middleware-next marker and
    // is neither a redirect nor a 401.
    expect(res.status).toBe(200);
    expect(res.headers.get("location")).toBeNull();
  });

  it("valid session preserves refreshed auth cookies on the returned response (AC7)", async () => {
    const mw = createMiddleware(
      fakeFactory(VALID_SESSION, { refreshCookie: { name: "sb-access-token", value: "fresh" } }),
    );
    const res = await mw(req("/runs/abc"));
    // The gate MUST return the cookie-handler response, so the refresh survives.
    const cookie = res.cookies.get("sb-access-token");
    expect(cookie?.value).toBe("fresh");
  });

  it("valid session on an API route passes through (no 401)", async () => {
    const mw = createMiddleware(fakeFactory(VALID_SESSION));
    const res = await mw(req("/api/runs/x/events/stream"));
    expect(res.status).toBe(200);
  });
});

describe("middleware auth gate — public short-circuit", () => {
  it("/login is public — passes through without calling getClaims", async () => {
    const getClaims = vi.fn();
    const factory: MiddlewareClientFactory = () =>
      ({ auth: { getClaims } }) as unknown as MiddlewareAuthClient;
    const mw = createMiddleware(factory);
    const res = await mw(req("/login"));
    expect(res.status).toBe(200);
    expect(getClaims).not.toHaveBeenCalled();
  });

  it("/login with a redirect query is still public", async () => {
    const getClaims = vi.fn();
    const factory: MiddlewareClientFactory = () =>
      ({ auth: { getClaims } }) as unknown as MiddlewareAuthClient;
    const mw = createMiddleware(factory);
    const res = await mw(req("/login?redirect=/"));
    expect(res.status).toBe(200);
    expect(getClaims).not.toHaveBeenCalled();
  });
});

describe("middleware auth gate — fail-closed", () => {
  it("auth error on a UI route is treated as unauthenticated → 302", async () => {
    const mw = createMiddleware(fakeFactory(AUTH_ERROR));
    const res = await mw(req("/"));
    expect(res.status).toBe(302);
    expect(parseLocation(res).pathname).toBe("/login");
  });

  it("auth error on an API route is treated as unauthenticated → 401", async () => {
    const mw = createMiddleware(fakeFactory(AUTH_ERROR));
    const res = await mw(req("/api/anything"));
    expect(res.status).toBe(401);
  });

  it("a thrown error from getClaims is caught and treated as unauthenticated (fail-closed)", async () => {
    const factory: MiddlewareClientFactory = () =>
      ({
        auth: {
          getClaims: () => Promise.reject(new Error("network down")),
        },
      }) as unknown as MiddlewareAuthClient;
    const mw = createMiddleware(factory);
    const res = await mw(req("/"));
    expect(res.status).toBe(302);
    expect(parseLocation(res).pathname).toBe("/login");
  });
});

describe("middleware auth gate — expired / invalid session (AC14 consequence)", () => {
  // 12h inactivity is a Supabase project setting, not panel code. The testable
  // surface is the CONSEQUENCE: an expired/invalid cookie yields no claims, so
  // the request is denied exactly like no session at all.
  const EXPIRED: ClaimsResult = { data: { claims: null }, error: { message: "jwt expired" } };

  it("expired session on a UI route is denied → 302 (AC14)", async () => {
    const mw = createMiddleware(fakeFactory(EXPIRED));
    const res = await mw(req("/"));
    expect(res.status).toBe(302);
    expect(parseLocation(res).pathname).toBe("/login");
  });

  it("expired session on the SSE path is denied → 401 (AC14)", async () => {
    const mw = createMiddleware(fakeFactory(EXPIRED));
    const res = await mw(req("/api/runs/x/events/stream"));
    expect(res.status).toBe(401);
  });

  it("malformed / garbage cookie yielding no claims is denied", async () => {
    const garbage: ClaimsResult = { data: null, error: { message: "invalid JWT structure" } };
    const mw = createMiddleware(fakeFactory(garbage));
    const res = await mw(req("/"));
    expect(res.status).toBe(302);
  });
});

describe("middleware matcher — static assets are not gated (edge case)", () => {
  // The matcher decides whether the middleware runs AT ALL. A static asset must
  // be excluded so the gate never fires on it. We assert the exported matcher
  // regex directly (the runtime uses it to decide invocation).
  const pattern = config.matcher[0];
  const re = new RegExp(`^${pattern}$`);

  it("excludes _next/static, _next/image, favicon, and image assets", () => {
    expect(re.test("/_next/static/chunks/main.js")).toBe(false);
    expect(re.test("/_next/image")).toBe(false);
    expect(re.test("/favicon.ico")).toBe(false);
    expect(re.test("/logo.svg")).toBe(false);
    expect(re.test("/brand.png")).toBe(false);
    expect(re.test("/photo.jpeg")).toBe(false);
    expect(re.test("/icon.webp")).toBe(false);
  });

  it("still matches (gates) pages, api, and the SSE path", () => {
    expect(re.test("/")).toBe(true);
    expect(re.test("/agents/x")).toBe(true);
    expect(re.test("/runs/y")).toBe(true);
    expect(re.test("/api/runs/z/events/stream")).toBe(true);
    expect(re.test("/login")).toBe(true); // matched, then short-circuited as public
  });
});

describe("middleware auth gate — concurrent near-expiry refresh (no thrash)", () => {
  it("concurrent requests sharing a near-expiry token each get one getClaims call", async () => {
    let calls = 0;
    const factory: MiddlewareClientFactory = (_req, response) => {
      response.cookies.set("sb-access-token", `refreshed-${calls}`);
      return {
        auth: {
          getClaims: () => {
            calls += 1;
            return Promise.resolve(VALID_SESSION);
          },
        },
      } as unknown as MiddlewareAuthClient;
    };
    const mw = createMiddleware(factory);
    const results = await Promise.all([mw(req("/")), mw(req("/agents/x")), mw(req("/runs/y"))]);
    // Each request independently verifies once — no shared mutable retry loop
    // that could thrash. Three requests → three verifications, all succeed.
    expect(calls).toBe(3);
    for (const res of results) {
      expect(res.status).toBe(200);
      expect(res.cookies.get("sb-access-token")).toBeTruthy();
    }
  });
});
