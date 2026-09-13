import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

import { probeLocalDb } from "./db";
import { createAuthServerClient, type CookieStore } from "@/lib/supabase/auth-server";

/**
 * S-119 — Layer 2.5 login round-trip (Docker-gated, spec §14.3).
 *
 * Runs against the REAL local Supabase stack. Proves the end-to-end auth
 * contract the login action depends on:
 *   - a user seeded via the admin API can `signInWithPassword` through the
 *     cookie-backed anon server client (S-116), and the sign-in SETS session
 *     cookies on the injected cookie store;
 *   - those cookies ROUND-TRIP: a fresh client built from the same stored
 *     cookies verifies the session via `getClaims()` (never `getSession()`);
 *   - a WRONG password fails (no session, no cookies);
 *   - **RLS stays deny-all (spec §14.3):** an authenticated end-user session
 *     still reads ZERO rows from the data tables — authenticating grants no
 *     row access (D11). This is the assertion that would catch a regression
 *     where login accidentally widened data visibility.
 *
 * A service-role key is required to seed the user; absent, the suite skips with
 * a recorded reason rather than passing vacuously.
 */

const probe = await probeLocalDb();

const API_URL = process.env.SUPABASE_URL ?? process.env.API_URL ?? "http://127.0.0.1:54321";
const SERVICE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY ?? process.env.SERVICE_ROLE_KEY ?? "";
const ANON_KEY = process.env.SUPABASE_ANON_KEY ?? process.env.ANON_KEY ?? "";

const keysPresent = SERVICE_KEY.trim().length > 0 && ANON_KEY.trim().length > 0;
const skipReason = !probe.available
  ? probe.reason
  : keysPresent
    ? ""
    : "SUPABASE_SERVICE_ROLE_KEY and/or SUPABASE_ANON_KEY not set — export from `supabase status -o env`";
const runSuite = probe.available && keysPresent;

// The auth clients read the NEXT_PUBLIC_* pair (auth-env.ts). Point them at the
// local stack for this suite, using the publishable name (#172, preferred). The
// local CLI stack only issues an anon-role key, so it is carried under the new
// name — exercising the publishable-first resolution. Set before any auth client
// is created.
if (runSuite) {
  process.env.NEXT_PUBLIC_SUPABASE_URL = API_URL;
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY = ANON_KEY;
}

/**
 * A minimal in-memory cookie store matching the `CookieStore` interface the
 * auth-server factory needs — the same surface Next's `cookies()` exposes. The
 * sign-in writes session cookies through `set`; a second client reads them back
 * via `getAll`, proving the round-trip without a browser.
 */
function memoryCookieStore(): CookieStore & { dump(): Array<{ name: string; value: string }> } {
  const jar = new Map<string, string>();
  return {
    getAll() {
      return Array.from(jar.entries()).map(([name, value]) => ({ name, value }));
    },
    set(name: string, value: string) {
      // A cleared cookie (empty value) is a delete, mirroring browser semantics.
      if (value === "") jar.delete(name);
      else jar.set(name, value);
    },
    dump() {
      return this.getAll();
    },
  };
}

const TEST_EMAIL = `s119-login-${randomUUID()}@example.test`;
const TEST_PASSWORD = `Pw-${randomUUID()}`;

describe.skipIf(!runSuite)("panel Layer 2.5 — login round-trip (S-119)", () => {
  let admin: SupabaseClient;
  let userId: string;

  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    admin = createClient(API_URL, SERVICE_KEY, {
      auth: { autoRefreshToken: false, persistSession: false },
    });
    const { data, error } = await admin.auth.admin.createUser({
      email: TEST_EMAIL,
      password: TEST_PASSWORD,
      email_confirm: true,
    });
    if (error) throw new Error(`failed to seed test user: ${error.message}`);
    userId = data.user!.id;
  });

  afterAll(async () => {
    if (userId) await admin.auth.admin.deleteUser(userId).catch(() => {});
  });

  it("signs in a seeded user and sets session cookies", async () => {
    const store = memoryCookieStore();
    const client = createAuthServerClient(store);
    const { data, error } = await client.auth.signInWithPassword({
      email: TEST_EMAIL,
      password: TEST_PASSWORD,
    });
    expect(error).toBeNull();
    expect(data.session).not.toBeNull();
    // The @supabase/ssr cookie adapter wrote at least one auth cookie.
    expect(store.dump().length).toBeGreaterThan(0);
  });

  it("round-trips the cookies: a fresh client verifies the session via getClaims()", async () => {
    const store = memoryCookieStore();
    const signInClient = createAuthServerClient(store);
    const { error: signInError } = await signInClient.auth.signInWithPassword({
      email: TEST_EMAIL,
      password: TEST_PASSWORD,
    });
    expect(signInError).toBeNull();

    // A DIFFERENT client built from the SAME stored cookies — the round-trip a
    // subsequent request performs. Verify identity with getClaims (AC8 posture).
    const readClient = createAuthServerClient(store);
    const { data, error } = await readClient.auth.getClaims();
    expect(error).toBeNull();
    expect(data?.claims).not.toBeNull();
    expect(data?.claims?.email).toBe(TEST_EMAIL);
  });

  it("rejects a wrong password with no session (anti-enumeration path)", async () => {
    const store = memoryCookieStore();
    const client = createAuthServerClient(store);
    const { data, error } = await client.auth.signInWithPassword({
      email: TEST_EMAIL,
      password: "definitely-not-the-password",
    });
    expect(error).not.toBeNull();
    expect(data.session).toBeNull();
    expect(store.dump().length).toBe(0);
  });

  it("RLS stays deny-all: an authenticated end-user session reads zero rows (spec §14.3)", async () => {
    // Sign in as the end user through an anon-key client that carries the user's
    // access token — exactly the privilege an authenticated browser session has.
    const authed = createClient(API_URL, ANON_KEY, {
      auth: { autoRefreshToken: false, persistSession: false },
    });
    const { data: signIn, error: signInError } = await authed.auth.signInWithPassword({
      email: TEST_EMAIL,
      password: TEST_PASSWORD,
    });
    expect(signInError).toBeNull();
    expect(signIn.session).not.toBeNull();

    // With a valid user JWT but RLS deny-all (D11) and zero policies, every data
    // table still returns zero rows (or an explicit permission error). Guard
    // against a vacuous pass by confirming rows exist via the service role.
    const seeded = await admin.from("agents").select("id").limit(1);
    expect((seeded.data ?? []).length).toBeGreaterThan(0);

    for (const table of ["agents", "runs", "run_events", "repositories"]) {
      const { data, error } = await authed.from(table).select("*").limit(50);
      if (error) {
        expect(error, `table ${table} errored (acceptable deny)`).toBeTruthy();
      } else {
        expect(
          data ?? [],
          `table ${table} leaked ${data?.length ?? 0} row(s) to an authenticated end user`,
        ).toHaveLength(0);
      }
    }
    await authed.auth.signOut().catch(() => {});
  });
});

if (!runSuite) {
  describe("panel Layer 2.5 — login round-trip (skipped)", () => {
    it.skip(`SKIPPED: ${skipReason}`, () => {});
  });
}
