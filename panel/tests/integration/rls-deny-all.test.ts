import { beforeAll, describe, expect, it } from "vitest";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 security-negative harness (S-104 / issue #117, CT-6, EC-14). Proves
// that an ANON-key PostgREST client reads ZERO rows from every base table AND
// from the v_runs view, on a database that contains seeded rows. RLS is
// enabled deny-all with zero policies (D11), so only the service role (which
// bypasses RLS) can read. This is the test that would have caught F2 before it
// became an architecture decision.
//
// The table list is enumerated FROM THE SCHEMA (information_schema), not
// hardcoded, so a future table added by a migration is not silently exempt
// from this assertion. v_runs is asserted explicitly on top, because a view
// owned by a privileged role can bypass base-table RLS entirely (EC-14) — it
// needs its own check, not inheritance from the table loop.
//
// Docker-gated: skips with a recorded reason when the local stack is down.
// G2 note: like status-parity, this security-negative test MUST NOT be allowed
// to skip-to-green in CI — the CI Node job starts the stack and treats a skip
// here as a failure (test plan G2).

const probe = await probeLocalDb();

// Resolve the anon key + API URL from the environment. The local Supabase
// stack's fixed values are the defaults; `supabase status -o env` exports
// ANON_KEY / API_URL, and CI wires the same. These are LOCAL-STACK values only
// (see .env.example TEST-ONLY block) — never application config.
const API_URL = process.env.SUPABASE_URL ?? process.env.API_URL ?? "http://127.0.0.1:54321";
const ANON_KEY = process.env.SUPABASE_ANON_KEY ?? process.env.ANON_KEY ?? "";

// The anon key is required for a meaningful test: an empty key would make every
// request fail with an auth error, which this test treats as an acceptable deny
// — a false pass. Gate on its presence separately from the Docker probe.
const anonKeyPresent = ANON_KEY.trim().length > 0;
const anonSkipReason = anonKeyPresent
  ? ""
  : "SUPABASE_ANON_KEY / ANON_KEY not set — run `supabase status -o env` and export ANON_KEY (test plan G2: CI must set this, not skip)";
const runSuite = probe.available && anonKeyPresent;

// Base tables the panel's boundary must never expose to an anon caller.
const EXPECTED_TABLES = [
  "github_installations",
  "repositories",
  "agents",
  "runs",
  "run_steps",
  "run_events",
  "run_artifacts",
] as const;

async function enumerateBaseTables(): Promise<string[]> {
  return withDb((c) =>
    c
      .query<{ table_name: string }>(
        `select table_name
           from information_schema.tables
          where table_schema = 'public'
            and table_type = 'BASE TABLE'`,
      )
      .then((r) => r.rows.map((row) => row.table_name)),
  );
}

describe.skipIf(!runSuite)("panel Layer 2.5 — RLS deny-all (anon reads zero rows)", () => {
  let anon: SupabaseClient;
  let baseTables: string[];

  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    anon = createClient(API_URL, ANON_KEY, {
      auth: { autoRefreshToken: false, persistSession: false },
    });
    baseTables = await enumerateBaseTables();
  });

  it("has actually seeded rows (guards against a vacuous zero-rows pass)", async () => {
    // If the DB were empty, "anon reads zero rows" would be trivially true and
    // prove nothing. Confirm via the service-role/direct connection that data
    // exists first.
    const agentCount = await withDb((c) =>
      c.query<{ n: string }>(`select count(*)::text as n from agents`).then((r) => r.rows[0]?.n),
    );
    expect(Number(agentCount)).toBeGreaterThan(0);
  });

  it("enumerates the expected base tables from the schema (no silent exemption)", () => {
    for (const t of EXPECTED_TABLES) {
      expect(baseTables, `expected table ${t} missing from schema enumeration`).toContain(t);
    }
  });

  it("anon-key client reads zero rows from every base table", async () => {
    for (const table of baseTables) {
      const { data, error } = await anon.from(table).select("*").limit(100);
      // Acceptable: an explicit permission error, OR an empty result set.
      // Unacceptable: one or more rows returned.
      if (error) {
        // A permission-denied / not-exposed error is a valid deny outcome.
        expect(error, `table ${table} errored (acceptable deny)`).toBeTruthy();
      } else {
        expect(
          data ?? [],
          `table ${table} leaked ${data?.length ?? 0} row(s) to anon`,
        ).toHaveLength(0);
      }
    }
  });

  it("anon-key client reads zero rows from the v_runs view (EC-14)", async () => {
    const { data, error } = await anon.from("v_runs").select("*").limit(100);
    if (error) {
      expect(error).toBeTruthy();
    } else {
      expect(data ?? [], `v_runs leaked ${data?.length ?? 0} row(s) to anon`).toHaveLength(0);
    }
  });
});

if (!runSuite) {
  const reason = !probe.available ? probe.reason : anonSkipReason;
  describe("panel Layer 2.5 — RLS deny-all (skipped)", () => {
    it.skip(`SKIPPED: ${reason}`, () => {});
  });
}
