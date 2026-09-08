import { describe, expect, it } from "vitest";
import { AuthConfigError, readAuthEnv } from "@/lib/supabase/auth-env";

// Layer 1 unit coverage for the anon-key auth env validation (S-116). Mirrors
// the fail-fast posture of readSupabaseEnv: a missing/blank/malformed
// NEXT_PUBLIC_SUPABASE_* variable throws a named AuthConfigError rather than
// yielding an undefined client.

const goodUrl = "http://127.0.0.1:54321";
const goodKey = "anon-publishable-key";

function env(fields: Record<string, string | undefined>): NodeJS.ProcessEnv {
  return fields as NodeJS.ProcessEnv;
}

describe("readAuthEnv — fail-fast validation (S-116)", () => {
  it("returns url + anonKey when both are present and valid", () => {
    const e = env({ NEXT_PUBLIC_SUPABASE_URL: goodUrl, NEXT_PUBLIC_SUPABASE_ANON_KEY: goodKey });
    expect(readAuthEnv(e)).toEqual({ url: goodUrl, anonKey: goodKey });
  });

  it("throws AuthConfigError when the URL is unset", () => {
    const e = env({ NEXT_PUBLIC_SUPABASE_ANON_KEY: goodKey });
    expect(() => readAuthEnv(e)).toThrow(AuthConfigError);
    expect(() => readAuthEnv(e)).toThrow(/NEXT_PUBLIC_SUPABASE_URL is not set/);
  });

  it("throws AuthConfigError when the URL is blank/whitespace", () => {
    const e = env({ NEXT_PUBLIC_SUPABASE_URL: "   ", NEXT_PUBLIC_SUPABASE_ANON_KEY: goodKey });
    expect(() => readAuthEnv(e)).toThrow(AuthConfigError);
  });

  it("throws AuthConfigError when the URL is malformed", () => {
    const e = env({
      NEXT_PUBLIC_SUPABASE_URL: "not-a-url",
      NEXT_PUBLIC_SUPABASE_ANON_KEY: goodKey,
    });
    expect(() => readAuthEnv(e)).toThrow(/not a valid URL/);
  });

  it("throws AuthConfigError when the anon key is unset", () => {
    const e = env({ NEXT_PUBLIC_SUPABASE_URL: goodUrl });
    expect(() => readAuthEnv(e)).toThrow(AuthConfigError);
    expect(() => readAuthEnv(e)).toThrow(/NEXT_PUBLIC_SUPABASE_ANON_KEY is not set/);
  });

  it("throws AuthConfigError when the anon key is blank", () => {
    const e = env({ NEXT_PUBLIC_SUPABASE_URL: goodUrl, NEXT_PUBLIC_SUPABASE_ANON_KEY: "" });
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
