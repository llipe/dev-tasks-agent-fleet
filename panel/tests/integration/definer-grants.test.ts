import { beforeAll, describe, expect, it } from "vitest";
import { createClient } from "@supabase/supabase-js";
import { localRestConfig, probeLocalDb, withDb } from "./db";

// Layer 2.5 — issue #357: no SECURITY DEFINER function in `public` may be
// executable by `anon` or `authenticated`.
//
// Postgres grants EXECUTE to PUBLIC on every new function, and Supabase exposes
// `public` functions through PostgREST at /rest/v1/rpc/<name>. A SECURITY
// DEFINER function runs as its owner and bypasses RLS, so an anon-executable one
// lets anyone holding the publishable (anon) key run it. The panel, pg_cron and
// the notify-sweep reach these functions as service_role or postgres, never as
// anon/authenticated.
//
// The function list is enumerated FROM THE CATALOG, so a future SECURITY DEFINER
// function added without the revoke fails here (same posture as the
// schema-enumerated rls-deny-all.test.ts).

const probe = await probeLocalDb();
const ANON_KEY = process.env.SUPABASE_ANON_KEY ?? process.env.ANON_KEY ?? "";

interface FnPrivs {
  fn: string;
  anon: boolean;
  authed: boolean;
  svc: boolean;
}

async function definerFunctions(): Promise<FnPrivs[]> {
  return withDb((c) =>
    c
      .query<FnPrivs>(
        `select p.oid::regprocedure::text as fn,
                has_function_privilege('anon', p.oid, 'execute') as anon,
                has_function_privilege('authenticated', p.oid, 'execute') as authed,
                has_function_privilege('service_role', p.oid, 'execute') as svc
           from pg_proc p
           join pg_namespace n on n.oid = p.pronamespace
          where n.nspname = 'public' and p.prosecdef
          order by 1`,
      )
      .then((r) => r.rows),
  );
}

describe.skipIf(!probe.available)("panel Layer 2.5 — #357 SECURITY DEFINER grants", () => {
  beforeAll(() => {
    console.log(`[integration] ${probe.reason}`);
  });

  it("finds the known SECURITY DEFINER functions (guards a vacuous pass)", async () => {
    const names = (await definerFunctions()).map((f) => f.fn);
    expect(names).toEqual(
      expect.arrayContaining(["reap_stale_runs()", "scheduler_record_fire_failure(uuid,text)"]),
    );
    expect(names.some((n) => n.startsWith("scheduler_preview_next_runs("))).toBe(true);
  });

  it("no public SECURITY DEFINER function is executable by anon or authenticated", async () => {
    const exposed = (await definerFunctions()).filter((f) => f.anon || f.authed).map((f) => f.fn);
    expect(exposed).toEqual([]);
  });

  it("service_role can still execute every public SECURITY DEFINER function", async () => {
    const missing = (await definerFunctions()).filter((f) => !f.svc).map((f) => f.fn);
    expect(missing).toEqual([]);
  });

  it.skipIf(!ANON_KEY)(
    "the anon key is denied scheduler_record_fire_failure through PostgREST",
    async () => {
      const { url } = localRestConfig();
      const anon = createClient(url, ANON_KEY, { auth: { persistSession: false } });
      const { error } = await anon.rpc("scheduler_record_fire_failure", {
        p_schedule_id: "00000000-0000-0000-0000-000000000000",
        p_error: "probe-357",
      });
      expect(error?.code).toBe("42501");
    },
  );

  it.skipIf(!ANON_KEY)("the anon key is denied reap_stale_runs through PostgREST", async () => {
    const { url } = localRestConfig();
    const anon = createClient(url, ANON_KEY, { auth: { persistSession: false } });
    const { error } = await anon.rpc("reap_stale_runs");
    expect(error?.code).toBe("42501");
  });

  it("the service role still calls scheduler_record_fire_failure through PostgREST (the panel's path)", async () => {
    const { url, serviceKey } = localRestConfig();
    const svc = createClient(url, serviceKey, { auth: { persistSession: false } });
    // A nonexistent schedule id: the function runs and updates nothing.
    const { error } = await svc.rpc("scheduler_record_fire_failure", {
      p_schedule_id: "00000000-0000-0000-0000-000000000000",
      p_error: "probe-357",
    });
    expect(error).toBeNull();
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — #357 SECURITY DEFINER grants (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
