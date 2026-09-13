import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthConfigError, readAuthEnv } from "@/lib/supabase/auth-env";

// Layer 1 unit coverage for the client-auth env validation.
//
// Historically (S-116) this read only NEXT_PUBLIC_SUPABASE_ANON_KEY. Issue #172
// migrates the client credential to Supabase's new publishable API key: the
// preferred name is NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY, with the legacy anon
// name accepted as a deprecated fallback for one release. Neither present →
// a named AuthConfigError (fail-fast, mirroring readSupabaseEnv in server.ts).

const goodUrl = "http://127.0.0.1:54321";
const publishableKey = "sb_publishable_abc123";
const legacyAnonKey = "anon-publishable-key";

function env(fields: Record<string, string | undefined>): NodeJS.ProcessEnv {
  return fields as NodeJS.ProcessEnv;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("readAuthEnv — URL validation (fail-fast)", () => {
  it("throws AuthConfigError when the URL is unset", () => {
    const e = env({ NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: publishableKey });
    expect(() => readAuthEnv(e)).toThrow(AuthConfigError);
    expect(() => readAuthEnv(e)).toThrow(/NEXT_PUBLIC_SUPABASE_URL is not set/);
  });

  it("throws AuthConfigError when the URL is blank/whitespace", () => {
    const e = env({
      NEXT_PUBLIC_SUPABASE_URL: "   ",
      NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: publishableKey,
    });
    expect(() => readAuthEnv(e)).toThrow(AuthConfigError);
  });

  it("throws AuthConfigError when the URL is malformed", () => {
    const e = env({
      NEXT_PUBLIC_SUPABASE_URL: "not-a-url",
      NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: publishableKey,
    });
    expect(() => readAuthEnv(e)).toThrow(/not a valid URL/);
  });
});

describe("readAuthEnv — publishable-key resolution (#172)", () => {
  it("prefers the publishable key when NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY is set", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const e = env({
      NEXT_PUBLIC_SUPABASE_URL: goodUrl,
      NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: publishableKey,
    });
    const result = readAuthEnv(e);
    expect(result.url).toBe(goodUrl);
    expect(result.publishableKey).toBe(publishableKey);
    // The `anonKey` alias remains available for existing callers.
    expect(result.anonKey).toBe(publishableKey);
    // No deprecation warning when the preferred name is used.
    expect(warn).not.toHaveBeenCalled();
  });

  it("prefers the publishable key even when BOTH names are present", () => {
    const e = env({
      NEXT_PUBLIC_SUPABASE_URL: goodUrl,
      NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: publishableKey,
      NEXT_PUBLIC_SUPABASE_ANON_KEY: legacyAnonKey,
    });
    expect(readAuthEnv(e).publishableKey).toBe(publishableKey);
  });

  it("falls back to the legacy anon key with a one-time deprecation warning", async () => {
    vi.resetModules();
    const { readAuthEnv: freshReadAuthEnv } = await import("@/lib/supabase/auth-env");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const e = env({
      NEXT_PUBLIC_SUPABASE_URL: goodUrl,
      NEXT_PUBLIC_SUPABASE_ANON_KEY: legacyAnonKey,
    });
    const result = freshReadAuthEnv(e);
    expect(result.publishableKey).toBe(legacyAnonKey);
    expect(result.anonKey).toBe(legacyAnonKey);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn.mock.calls[0]?.[0]).toMatch(/NEXT_PUBLIC_SUPABASE_ANON_KEY.*deprecated/i);
    expect(warn.mock.calls[0]?.[0]).toMatch(/NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY/);
  });

  it("warns only once across repeated fallback reads (one-time deprecation)", async () => {
    // The one-time guard is module-level, so re-import a fresh module instance
    // to observe the very first warn (other tests in this file may have already
    // tripped the shared guard).
    vi.resetModules();
    const { readAuthEnv: freshReadAuthEnv } = await import("@/lib/supabase/auth-env");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const e = env({
      NEXT_PUBLIC_SUPABASE_URL: goodUrl,
      NEXT_PUBLIC_SUPABASE_ANON_KEY: legacyAnonKey,
    });
    freshReadAuthEnv(e);
    freshReadAuthEnv(e);
    freshReadAuthEnv(e);
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it("treats a blank publishable key as absent and falls back to the legacy anon key", () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const e = env({
      NEXT_PUBLIC_SUPABASE_URL: goodUrl,
      NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "   ",
      NEXT_PUBLIC_SUPABASE_ANON_KEY: legacyAnonKey,
    });
    expect(readAuthEnv(e).publishableKey).toBe(legacyAnonKey);
  });

  it("throws AuthConfigError when NEITHER key is set", () => {
    const e = env({ NEXT_PUBLIC_SUPABASE_URL: goodUrl });
    expect(() => readAuthEnv(e)).toThrow(AuthConfigError);
    expect(() => readAuthEnv(e)).toThrow(/NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY/);
  });

  it("throws AuthConfigError when both keys are blank", () => {
    const e = env({
      NEXT_PUBLIC_SUPABASE_URL: goodUrl,
      NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "",
      NEXT_PUBLIC_SUPABASE_ANON_KEY: "  ",
    });
    expect(() => readAuthEnv(e)).toThrow(AuthConfigError);
  });

  it("carries the AUTH_CONFIG_ERROR code for programmatic handling", () => {
    try {
      readAuthEnv(env({}));
      expect.unreachable("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(AuthConfigError);
      expect((err as AuthConfigError).code).toBe("AUTH_CONFIG_ERROR");
    }
  });
});
