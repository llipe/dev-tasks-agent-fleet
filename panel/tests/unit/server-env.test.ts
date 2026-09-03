import { describe, expect, it } from "vitest";
import { readSupabaseEnv, SupabaseConfigError } from "@/lib/supabase/server";

// Layer 1 unit coverage for the fail-fast env validation (S-104 / issue #117,
// EC-12, AC-104.1). A missing or malformed SUPABASE_* variable must throw a
// named startup error, never yield an `undefined` client that null-dereferences
// later on an unrelated line. `readSupabaseEnv` takes an explicit env map so no
// process.env mutation is needed.

const goodKey = "service-role-key-value";
const goodUrl = "http://127.0.0.1:54321";

// Build a NodeJS.ProcessEnv-typed map from the fields under test. ProcessEnv is
// an index signature of string|undefined, so a plain object literal satisfies
// it; the helper is `as NodeJS.ProcessEnv` at the boundary to keep call sites
// readable.
function env(fields: Record<string, string | undefined>): NodeJS.ProcessEnv {
  return fields as NodeJS.ProcessEnv;
}

describe("readSupabaseEnv — fail-fast validation (EC-12)", () => {
  it("returns url + serviceRoleKey when both are present and valid", () => {
    const e = env({ SUPABASE_URL: goodUrl, SUPABASE_SERVICE_ROLE_KEY: goodKey });
    expect(readSupabaseEnv(e)).toEqual({ url: goodUrl, serviceRoleKey: goodKey });
  });

  it("throws SupabaseConfigError when SUPABASE_URL is unset", () => {
    const e = env({ SUPABASE_SERVICE_ROLE_KEY: goodKey });
    expect(() => readSupabaseEnv(e)).toThrow(SupabaseConfigError);
    expect(() => readSupabaseEnv(e)).toThrow(/SUPABASE_URL is not set/);
  });

  it("throws SupabaseConfigError when SUPABASE_URL is empty/whitespace", () => {
    const e = env({ SUPABASE_URL: "   ", SUPABASE_SERVICE_ROLE_KEY: goodKey });
    expect(() => readSupabaseEnv(e)).toThrow(SupabaseConfigError);
  });

  it("throws SupabaseConfigError when SUPABASE_URL is not a valid URL", () => {
    const e = env({ SUPABASE_URL: "not-a-url", SUPABASE_SERVICE_ROLE_KEY: goodKey });
    expect(() => readSupabaseEnv(e)).toThrow(/not a valid URL/);
  });

  it("throws SupabaseConfigError when the service role key is unset", () => {
    const e = env({ SUPABASE_URL: goodUrl });
    expect(() => readSupabaseEnv(e)).toThrow(SupabaseConfigError);
    expect(() => readSupabaseEnv(e)).toThrow(/SUPABASE_SERVICE_ROLE_KEY is not set/);
  });

  it("throws SupabaseConfigError when the service role key is empty", () => {
    const e = env({ SUPABASE_URL: goodUrl, SUPABASE_SERVICE_ROLE_KEY: "" });
    expect(() => readSupabaseEnv(e)).toThrow(SupabaseConfigError);
  });

  it("carries the SUPABASE_CONFIG_ERROR code for programmatic handling", () => {
    try {
      readSupabaseEnv(env({}));
      expect.unreachable("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(SupabaseConfigError);
      expect((err as SupabaseConfigError).code).toBe("SUPABASE_CONFIG_ERROR");
    }
  });
});
