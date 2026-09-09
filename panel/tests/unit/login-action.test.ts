import { describe, expect, it, vi } from "vitest";

/**
 * S-119 — sign-in action decision logic (Layer 1, spec §8.2 / §8.3).
 *
 * Tests the PURE core `resolveSignIn`, which takes an injected sign-in function
 * so no live Supabase or Next request context is needed. `actions.ts` is a
 * `"use server"` module whose top-level imports pull in `next/headers` and
 * `next/navigation`; those are mocked here only so the module resolves under
 * the node test environment — the tests never exercise the cookie/redirect
 * wrapper, only the testable decision core.
 *
 * The security-critical assertions:
 *   - missing fields → `AUTH_MISSING_FIELDS` (no sign-in attempt made)
 *   - a thrown/5xx service error → `AUTH_SERVICE_UNAVAILABLE`
 *   - unknown-email and wrong-password are INDISTINGUISHABLE (identical code +
 *     message) — the anti-enumeration invariant (AC5)
 *   - the redirect is sanitized via `safeRedirectTarget` BEFORE use (AC4), on
 *     both success and every failure branch
 *   - the password is never returned in the result
 */

vi.mock("next/headers", () => ({ cookies: vi.fn() }));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));

import { resolveSignIn, type PasswordSignIn } from "@/app/login/actions";
import { INVALID_CREDENTIALS_MESSAGE } from "@/lib/auth/errors";

/** A sign-in stub that always succeeds. */
const ok: PasswordSignIn = async () => ({ error: null });

/** A sign-in stub that returns a Supabase-shaped error with the given status. */
function withStatus(status: number): PasswordSignIn {
  return async () => ({ error: { status, message: "raw supabase text — must not leak" } });
}

describe("resolveSignIn — field validation (AUTH_MISSING_FIELDS)", () => {
  it("returns AUTH_MISSING_FIELDS when email is empty, without attempting sign-in", async () => {
    const signIn = vi.fn<PasswordSignIn>(async () => ({ error: null }));
    const r = await resolveSignIn({ email: "", password: "pw", redirect: "/" }, signIn);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe("AUTH_MISSING_FIELDS");
    expect(signIn).not.toHaveBeenCalled();
  });

  it("returns AUTH_MISSING_FIELDS when password is empty", async () => {
    const signIn = vi.fn<PasswordSignIn>(async () => ({ error: null }));
    const r = await resolveSignIn({ email: "a@b.co", password: "", redirect: "/" }, signIn);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe("AUTH_MISSING_FIELDS");
    expect(signIn).not.toHaveBeenCalled();
  });

  it("treats a whitespace-only email as missing (trimmed)", async () => {
    const signIn = vi.fn<PasswordSignIn>(async () => ({ error: null }));
    const r = await resolveSignIn({ email: "   ", password: "pw", redirect: "/" }, signIn);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe("AUTH_MISSING_FIELDS");
    expect(signIn).not.toHaveBeenCalled();
  });

  it("treats non-string fields as missing", async () => {
    const r = await resolveSignIn(
      { email: undefined, password: null, redirect: undefined },
      ok,
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe("AUTH_MISSING_FIELDS");
  });
});

describe("resolveSignIn — service errors (AUTH_SERVICE_UNAVAILABLE)", () => {
  it("maps a thrown transport error to AUTH_SERVICE_UNAVAILABLE", async () => {
    const signIn: PasswordSignIn = async () => {
      throw new Error("ECONNREFUSED");
    };
    const r = await resolveSignIn({ email: "a@b.co", password: "pw", redirect: "/" }, signIn);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe("AUTH_SERVICE_UNAVAILABLE");
  });

  it("maps a 500 error to AUTH_SERVICE_UNAVAILABLE", async () => {
    const r = await resolveSignIn(
      { email: "a@b.co", password: "pw", redirect: "/" },
      withStatus(500),
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe("AUTH_SERVICE_UNAVAILABLE");
  });

  it("maps a 429 error to AUTH_SERVICE_UNAVAILABLE", async () => {
    const r = await resolveSignIn(
      { email: "a@b.co", password: "pw", redirect: "/" },
      withStatus(429),
    );
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe("AUTH_SERVICE_UNAVAILABLE");
  });
});

describe("resolveSignIn — anti-enumeration (AC5)", () => {
  it("collapses a 400 (wrong password) and a 400 (unknown email) to the identical result", async () => {
    const wrongPassword = await resolveSignIn(
      { email: "known@b.co", password: "bad", redirect: "/" },
      withStatus(400),
    );
    const unknownEmail = await resolveSignIn(
      { email: "nobody@b.co", password: "whatever", redirect: "/" },
      withStatus(400),
    );
    expect(wrongPassword.ok).toBe(false);
    expect(unknownEmail.ok).toBe(false);
    if (!wrongPassword.ok && !unknownEmail.ok) {
      expect(wrongPassword.code).toBe("AUTH_INVALID_CREDENTIALS");
      expect(unknownEmail.code).toBe("AUTH_INVALID_CREDENTIALS");
      expect(wrongPassword.message).toBe(unknownEmail.message);
      expect(wrongPassword.message).toBe(INVALID_CREDENTIALS_MESSAGE);
    }
  });

  it("maps a 404 (user not found) to the SAME generic credential message", async () => {
    const r = await resolveSignIn(
      { email: "nobody@b.co", password: "pw", redirect: "/" },
      withStatus(404),
    );
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.code).toBe("AUTH_INVALID_CREDENTIALS");
      expect(r.message).toBe(INVALID_CREDENTIALS_MESSAGE);
    }
  });

  it("never leaks raw Supabase error text in the message", async () => {
    const r = await resolveSignIn(
      { email: "a@b.co", password: "pw", redirect: "/" },
      withStatus(400),
    );
    if (!r.ok) expect(r.message).not.toContain("raw supabase text");
  });
});

describe("resolveSignIn — redirect sanitization applied before use (AC4)", () => {
  it("sanitizes an off-origin redirect to `/` on SUCCESS", async () => {
    const r = await resolveSignIn(
      { email: "a@b.co", password: "pw", redirect: "//evil.com" },
      ok,
    );
    expect(r.ok).toBe(true);
    expect(r.redirect).toBe("/");
  });

  it("sanitizes an absolute redirect to `/` on FAILURE too", async () => {
    const r = await resolveSignIn(
      { email: "a@b.co", password: "bad", redirect: "https://evil.com" },
      withStatus(400),
    );
    expect(r.redirect).toBe("/");
  });

  it("rejects a `/login` loop target, falling back to `/`", async () => {
    const r = await resolveSignIn(
      { email: "a@b.co", password: "pw", redirect: "/login" },
      ok,
    );
    expect(r.ok).toBe(true);
    expect(r.redirect).toBe("/");
  });

  it("preserves a valid same-origin path with query + hash", async () => {
    const r = await resolveSignIn(
      { email: "a@b.co", password: "pw", redirect: "/runs/abc?tab=log#tail" },
      ok,
    );
    expect(r.ok).toBe(true);
    expect(r.redirect).toBe("/runs/abc?tab=log#tail");
  });

  it("defaults an absent redirect to `/`", async () => {
    const r = await resolveSignIn({ email: "a@b.co", password: "pw", redirect: undefined }, ok);
    expect(r.ok).toBe(true);
    expect(r.redirect).toBe("/");
  });
});

describe("resolveSignIn — never returns the password", () => {
  it("does not include the submitted password anywhere in the result object", async () => {
    const secret = "sup3r-s3cret-p@ssw0rd";
    const r = await resolveSignIn(
      { email: "a@b.co", password: secret, redirect: "/" },
      withStatus(400),
    );
    expect(JSON.stringify(r)).not.toContain(secret);
  });
});
