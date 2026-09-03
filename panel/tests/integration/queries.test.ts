import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { Client } from "pg";
import { probeLocalDb, withDb } from "./db";
import {
  getAgentBySlug,
  getEnabledAgents,
  getEnabledRepositories,
  getRunArtifacts,
  getRunById,
  getRunEvents,
  getRunSteps,
  getRunsByAgentSlug,
  RUN_EVENTS_READ_LIMIT,
} from "@/lib/supabase/queries";

// Layer 2.5 shape harness (S-104 / issue #117, CT-5, EC-17..EC-19). Runs each
// of the eight typed helpers against the REAL seeded local stack through a
// service-role PostgREST client (the helpers' production transport), and
// asserts the RUNTIME shape — declared keys present with declared types — not
// just a TypeScript cast (a cast proves nothing at runtime, CT-5).
//
// A service-role key is required (the helpers bypass RLS by design). We resolve
// it from SUPABASE_SERVICE_ROLE_KEY / SERVICE_ROLE_KEY; absent, the suite skips
// with a recorded reason rather than passing vacuously.
//
// Docker-gated; skips with a recorded reason when the stack is down.

const probe = await probeLocalDb();

const API_URL = process.env.SUPABASE_URL ?? process.env.API_URL ?? "http://127.0.0.1:54321";
const SERVICE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY ?? process.env.SERVICE_ROLE_KEY ?? "";
const keyPresent = SERVICE_KEY.trim().length > 0;
const skipReason = !probe.available
  ? probe.reason
  : keyPresent
    ? ""
    : "SUPABASE_SERVICE_ROLE_KEY / SERVICE_ROLE_KEY not set — export it from `supabase status -o env`";
const runSuite = probe.available && keyPresent;

// A run we insert to give run_steps / run_events / run_artifacts helpers data,
// including a no-repository run (EC-18) and an over-limit event stream (EC-19).
interface Fixture {
  agentId: string;
  runId: string;
}
const fx: Fixture = { agentId: "", runId: "" };

async function seedFixture(c: Client): Promise<void> {
  fx.agentId = randomUUID();
  await c.query(
    `insert into agents (id, slug, name, runtime_arn, requires_repository,
                         max_runtime_seconds, grace_seconds, start_timeout_seconds)
     values ($1, $2, $3, $4, false, 900, 60, 300)`,
    [fx.agentId, `s104-queries-${fx.agentId}`, "S-104 queries test agent", "arn:test:runtime/q"],
  );

  // A run with NO repository (agent.requires_repository = false, EC-18).
  fx.runId = randomUUID();
  await c.query(
    `insert into runs (id, agent_id, agent_version, status, repository_id,
                       queued_at, started_at, finished_at,
                       max_runtime_seconds, grace_seconds, start_timeout_seconds, outcome)
     values ($1, $2, '0.1.0', 'succeeded', null,
             now() - interval '5 min', now() - interval '4 min', now() - interval '1 min',
             900, 60, 300, 'no_vulnerabilities')`,
    [fx.runId, fx.agentId],
  );

  await c.query(
    `insert into run_steps (run_id, seq, key, status, started_at, finished_at)
     values ($1, 1, 'checkout', 'succeeded', now() - interval '4 min', now() - interval '3 min')`,
    [fx.runId],
  );

  await c.query(
    `insert into run_artifacts (run_id, type, title, url)
     values ($1, 'pull_request', 'chore: bump deps', 'https://github.com/x/y/pull/1')`,
    [fx.runId],
  );

  // Seed RUN_EVENTS_READ_LIMIT + 25 events so the bounded read (EC-19) is
  // actually exercised (over the 2000 cap).
  const total = RUN_EVENTS_READ_LIMIT + 25;
  const values: string[] = [];
  const params: unknown[] = [fx.runId];
  for (let i = 1; i <= total; i++) {
    values.push(`($1, ${i}, 'info', 'event ${i}')`);
  }
  await c.query(
    `insert into run_events (run_id, seq, level, message) values ${values.join(",")}`,
    params,
  );
}

async function cleanupFixture(c: Client): Promise<void> {
  if (fx.runId) {
    await c.query(`delete from run_events where run_id = $1`, [fx.runId]);
    await c.query(`delete from run_steps where run_id = $1`, [fx.runId]);
    await c.query(`delete from run_artifacts where run_id = $1`, [fx.runId]);
    await c.query(`delete from runs where id = $1`, [fx.runId]);
  }
  if (fx.agentId) {
    await c.query(`delete from agents where id = $1`, [fx.agentId]);
  }
}

/**
 * Reproduce, on the LOCAL CLI stack only, the `service_role` SELECT grants that
 * the hosted Supabase platform applies automatically as default table
 * privileges. The live project already carries these 84 platform-managed grants
 * (confirmed by the S-115 baseline diff,
 * docs/runbooks/issue-115-baseline-adoption.md), which is why they were
 * deliberately kept OUT of the canonical migration — re-issuing platform grants
 * was judged platform tampering.
 *
 * `supabase db reset` on this CLI version does NOT reproduce those automatic
 * grants, so the service-role PostgREST transport (the panel's real read path)
 * is denied locally with `42501` even though it works against production. This
 * grant makes the LOCAL stack match production truth so the helper transport is
 * actually exercised. It grants SELECT to `service_role` ONLY — never `anon` —
 * so the RLS deny-all posture is untouched (anon still reads zero rows because
 * RLS, not a missing grant, is the gate).
 */
async function grantServiceRoleSelectLocalOnly(c: Client): Promise<void> {
  await c.query(`grant usage on schema public to service_role`);
  await c.query(`grant select on all tables in schema public to service_role`);
}

const isIso = (v: unknown) => typeof v === "string" && !Number.isNaN(Date.parse(v));

describe.skipIf(!runSuite)("panel Layer 2.5 — query helper shapes", () => {
  let client: SupabaseClient;

  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    client = createClient(API_URL, SERVICE_KEY, {
      auth: { autoRefreshToken: false, persistSession: false },
    });
    await withDb(async (c) => {
      await grantServiceRoleSelectLocalOnly(c);
      await seedFixture(c);
    });
  });

  afterAll(async () => {
    await withDb(cleanupFixture);
  });

  it("getEnabledAgents returns AgentRow[] including the seeded dependency-update agent", async () => {
    const agents = await getEnabledAgents(client);
    expect(Array.isArray(agents)).toBe(true);
    expect(agents.length).toBeGreaterThan(0);
    const a = agents[0];
    expect(typeof a.id).toBe("string");
    expect(typeof a.slug).toBe("string");
    expect(typeof a.name).toBe("string");
    expect(typeof a.requires_repository).toBe("boolean");
    expect(typeof a.max_runtime_seconds).toBe("number");
    expect(typeof a.params_schema).toBe("object");
    expect(isIso(a.created_at)).toBe(true);
  });

  it("getAgentBySlug returns one AgentRow, and null for an unknown slug", async () => {
    const known = await getAgentBySlug(client, "dependency-update");
    expect(known).not.toBeNull();
    expect(known?.slug).toBe("dependency-update");

    const unknown = await getAgentBySlug(client, "no-such-agent-xyz");
    expect(unknown).toBeNull();
  });

  it("getEnabledRepositories returns RepositoryRow[]", async () => {
    const repos = await getEnabledRepositories(client);
    expect(Array.isArray(repos)).toBe(true);
    if (repos.length > 0) {
      const r = repos[0];
      expect(typeof r.full_name).toBe("string");
      expect(typeof r.default_branch).toBe("string");
      expect(r.archived_at).toBeNull();
      expect(r.is_enabled).toBe(true);
    }
  });

  it("getRunsByAgentSlug returns VRunRow[] with view-only columns present", async () => {
    const runs = await getRunsByAgentSlug(client, `s104-queries-${fx.agentId}`);
    expect(runs.length).toBe(1);
    const run = runs[0];
    expect(run.id).toBe(fx.runId);
    // view-only columns:
    expect(typeof run.agent_slug).toBe("string");
    expect(typeof run.agent_name).toBe("string");
    expect(typeof run.effective_status).toBe("string");
    // EC-18: no repository -> repository_full_name is null, no "null/null"
    expect(run.repository_id).toBeNull();
    expect(run.repository_full_name).toBeNull();
  });

  it("getRunById returns one VRunRow, null for an unknown id", async () => {
    const run = await getRunById(client, fx.runId);
    expect(run?.id).toBe(fx.runId);
    expect(run?.effective_status).toBe("succeeded"); // terminal, passes through

    const missing = await getRunById(client, randomUUID());
    expect(missing).toBeNull();
  });

  it("getRunSteps returns RunStepRow[] seq-ordered", async () => {
    const steps = await getRunSteps(client, fx.runId);
    expect(steps.length).toBe(1);
    expect(steps[0].key).toBe("checkout");
    expect(steps[0].status).toBe("succeeded");
    expect(typeof steps[0].seq).toBe("number");
  });

  it("getRunEvents is bounded to RUN_EVENTS_READ_LIMIT and seq-ordered ascending (EC-19)", async () => {
    const events = await getRunEvents(client, fx.runId);
    expect(events.length).toBe(RUN_EVENTS_READ_LIMIT);
    // ascending seq
    for (let i = 1; i < events.length; i++) {
      expect(events[i].seq).toBeGreaterThan(events[i - 1].seq);
    }
    // taken from the most-recent end: last event is the highest seq (2025)
    expect(events[events.length - 1].seq).toBe(RUN_EVENTS_READ_LIMIT + 25);
    expect(events[0].level).toBe("info");
  });

  it("getRunArtifacts returns RunArtifactRow[]", async () => {
    const artifacts = await getRunArtifacts(client, fx.runId);
    expect(artifacts.length).toBe(1);
    expect(artifacts[0].type).toBe("pull_request");
    expect(typeof artifacts[0].url).toBe("string");
  });

  it("returns [] (never null) for empty collections (EC-17)", async () => {
    const emptyRuns = await getRunsByAgentSlug(client, "agent-with-no-runs-xyz");
    expect(emptyRuns).toEqual([]);
    const emptySteps = await getRunSteps(client, randomUUID());
    expect(emptySteps).toEqual([]);
    const emptyEvents = await getRunEvents(client, randomUUID());
    expect(emptyEvents).toEqual([]);
    const emptyArtifacts = await getRunArtifacts(client, randomUUID());
    expect(emptyArtifacts).toEqual([]);
  });
});

if (!runSuite) {
  describe("panel Layer 2.5 — query helper shapes (skipped)", () => {
    it.skip(`SKIPPED: ${skipReason}`, () => {});
  });
}
