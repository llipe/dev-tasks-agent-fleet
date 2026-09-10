import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Logout route handler (Story S-120, spec §8 / PRD AC6) — Layer 1 unit.
 *
 * The route is POST-only and lives at `app/api/auth/logout/route.ts`. It calls
 * `signOut` on the cookie-backed anon auth client (S-116), which clears the
 * session cookies on the response, then redirects (302) to `/login`.
 *
 * `next/headers` and the auth-server client are mocked so the handler resolves
 * and runs under the node environment without a live Supabase or request
 * context. The assertions that matter:
 *   - a 302 redirect to `/login` (AC6)
 *   - `signOut` is invoked (session cleared server-side; the SSR client writes
 *     the cleared cookies onto the response)
 *   - idempotent: with NO session, it STILL 302s to `/login` without throwing
 *   - a signOut that throws still yields a 302 to `/login` (never a 500 —
 *     ending a session must not be blockable by a transient auth error)
 *   - the module exports POST but NOT GET (a GET logout is CSRF-triggerable)
 */

const signOut = vi.hoisted(() => vi.fn());

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({
    getAll: () => [],
    set: () => {},
  })),
}));

vi.mock("@/lib/supabase/auth-server", () => ({
  createAuthServerClient: () => ({ auth: { signOut } }),
}));

import * as logoutRoute from "@/app/api/auth/logout/route";

/**
 * The `Location` header of a redirect response. The handler emits a RELATIVE
 * location (`/login`) so it is same-origin regardless of the host the server
 * binds to — see the regression note below.
 */
function locationHeader(res: Response): string {
  return res.headers.get("location") ?? "";
}

beforeEach(() => {
  signOut.mockReset();
  signOut.mockResolvedValue({ error: null });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("POST /api/auth/logout (AC6)", () => {
  it("calls signOut and redirects (302) to /login", async () => {
    const res = await logoutRoute.POST();
    expect(signOut).toHaveBeenCalledTimes(1);
    expect(res.status).toBe(302);
    expect(locationHeader(res)).toBe("/login");
  });

  it("is idempotent: with no session it still redirects to /login without error", async () => {
    // A no-session signOut resolves with an AuthSessionMissingError-shaped error;
    // the handler must still redirect, never surface it.
    signOut.mockResolvedValue({
      error: { name: "AuthSessionMissingError", message: "no session" },
    });
    const res = await logoutRoute.POST();
    expect(res.status).toBe(302);
    expect(locationHeader(res)).toBe("/login");
  });

  it("still redirects to /login when signOut throws (never a 500)", async () => {
    signOut.mockRejectedValue(new Error("transient auth failure"));
    const res = await logoutRoute.POST();
    expect(res.status).toBe(302);
    expect(locationHeader(res)).toBe("/login");
  });

  // Regression: behind a reverse proxy (Fly) the server binds to
  // HOSTNAME=0.0.0.0:8080, so an absolute redirect built from `request.url`
  // sent the browser to the unreachable `http://0.0.0.0:8080/login`. The
  // Location MUST be a same-origin RELATIVE path with no host component.
  it("uses a relative same-origin Location — never an absolute URL with a host", async () => {
    const res = await logoutRoute.POST();
    const loc = locationHeader(res);
    expect(loc).toBe("/login");
    expect(loc.startsWith("/")).toBe(true);
    expect(loc).not.toMatch(/^https?:\/\//);
    expect(loc).not.toContain("0.0.0.0");
  });
});

describe("logout route surface (AC: GET does not exist)", () => {
  it("exports POST", () => {
    expect(typeof logoutRoute.POST).toBe("function");
  });

  it("does NOT export GET (a GET logout is CSRF-triggerable)", () => {
    expect((logoutRoute as Record<string, unknown>).GET).toBeUndefined();
  });
});
