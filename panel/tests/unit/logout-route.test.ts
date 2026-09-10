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
import type { NextRequest } from "next/server";

function req(): NextRequest {
  // The handler only reads `request.url`; a plain Request carries that. Cast to
  // NextRequest to satisfy the handler signature without a full Next stub.
  return new Request("https://panel.example.com/api/auth/logout", {
    method: "POST",
  }) as unknown as NextRequest;
}

/** The `Location` header path of a redirect response. */
function redirectPath(res: Response): string {
  const loc = res.headers.get("location");
  return loc ? new URL(loc).pathname : "";
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
    const res = await logoutRoute.POST(req());
    expect(signOut).toHaveBeenCalledTimes(1);
    expect(res.status).toBe(302);
    expect(redirectPath(res)).toBe("/login");
  });

  it("is idempotent: with no session it still redirects to /login without error", async () => {
    // A no-session signOut resolves with an AuthSessionMissingError-shaped error;
    // the handler must still redirect, never surface it.
    signOut.mockResolvedValue({
      error: { name: "AuthSessionMissingError", message: "no session" },
    });
    const res = await logoutRoute.POST(req());
    expect(res.status).toBe(302);
    expect(redirectPath(res)).toBe("/login");
  });

  it("still redirects to /login when signOut throws (never a 500)", async () => {
    signOut.mockRejectedValue(new Error("transient auth failure"));
    const res = await logoutRoute.POST(req());
    expect(res.status).toBe(302);
    expect(redirectPath(res)).toBe("/login");
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
