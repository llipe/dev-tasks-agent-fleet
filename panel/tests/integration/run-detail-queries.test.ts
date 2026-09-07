import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { Client } from "pg";
import { probeLocalDb, withDb } from "./db";
import {
  getRunById,
  getRunSteps,
  getRunEvents,
  getRunEventsInRange,
  getRunArtifacts,
  RUN_EVENTS_READ_LIMIT,
} from "@/lib/supabase/queries";

/**
 * Layer 2.5 harness for the run-detail read path (S-109 / issue #122).
 *
 * Two properties that can only be proven against the real stack (test-plan
 * CT-1..CT-5, SC-8):
 *  - A seeded run with steps + events + a `pull_request` artifact returns the
 *    expected row shapes through the read helpers.
 *  - A run with 2,500 events returns exactly the most-recent 2,000 in `seq`
 *    order (SD11 bound), honored under the PostgREST `max_rows=1000` ceiling
 *    (the paged read in `getRunEvents`), and the load-earlier range read
 *    returns the prior slice with no overlap.
 *
 * Docker-gated + service-role-key-gated, same as the other Layer 2.5 suites.
 * Skips with a recorded reason rather than passing vacuously (test-plan G2).
 */

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

const createdAgentIds: string[] = [];

async function grantServiceRoleSelectLocalOnly(c: Client): Promise<void> {
  await c.query(`grant usage on schema public to service_role`);
  await c.query(`grant select on all tables in schema public to service_role`);
}

async function insertAgent(c: Client, slug: string): Promise<string> {
  const id = randomUUID();
  await c.query(
    `insert into agents (id, slug, name, runtime_arn, requires_repository,
                         max_runtime_seconds, grace_seconds, start_timeout_seconds)
     values ($1, $2, $3, $4, false, 900, 60, 300)`,
    [id, slug, `run-detail test ${slug}`, "arn:test:runtime/rundetail"],
  );
  createdAgentIds.push(id);
  return id;
}

async function insertRun(
  c: Client,
  agentId: string,
  status: string,
  outcome: string | null,
): Promise<string> {
  const id = randomUUID();
  await c.query(
    `insert into runs (id, agent_id, agent_version, status,
                       queued_at, started_at, finished_at, created_at,
                       max_runtime_seconds, grace_seconds, start_timeout_seconds, outcome)
     values ($1, $2, '0.1.0', $3::run_status,
             now() - interval '10 min', now() - interval '9 min',
             case when $3::run_status in ('succeeded','failed','timed_out')
                  then now() - interval '5 min' else null end,
             now() - interval '10 min',
             900, 60, 300, $4::run_outcome)`,
    [id, agentId, status, outcome],
  );
  return id;
}

async function insertStep(c: Client, runId: string, seq: number, key: string): Promise<string> {
  const id = randomUUID();
  await c.query(
    `insert into run_steps (id, run_id, seq, key, title, status)
     values ($1, $2, $3, $4, $5, 'succeeded')`,
    [id, runId, seq, key, key],
  );
  return id;
}

async function insertEvents(c: Client, runId: string, count: number): Promise<void> {
  // Bulk insert seq 1..count via generate_series to keep the 2,500-event test fast.
  await c.query(
    `insert into run_events (run_id, seq, ts, level, message)
     select $1, g, now() - (($2 - g) || ' ms')::interval, 'info', 'event ' || g
     from generate_series(1, $2) as g`,
    [runId, count],
  );
}

async function insertArtifact(c: Client, runId: string, url: string): Promise<void> {
  await c.query(
    `insert into run_artifacts (id, run_id, type, title, url)
     values ($1, $2, 'pull_request', 'Bump lodash', $3)`,
    [randomUUID(), runId, url],
  );
}

async function cleanup(c: Client): Promise<void> {
  for (const id of createdAgentIds) {
    await c.query(
      `delete from run_events where run_id in (select id from runs where agent_id = $1)`,
      [id],
    );
    await c.query(
      `delete from run_artifacts where run_id in (select id from runs where agent_id = $1)`,
      [id],
    );
    await c.query(
      `delete from run_steps where run_id in (select id from runs where agent_id = $1)`,
      [id],
    );
    await c.query(`delete from runs where agent_id = $1`, [id]);
    await c.query(`delete from agents where id = $1`, [id]);
  }
  createdAgentIds.length = 0;
}

function client(): SupabaseClient {
  return createClient(API_URL, SERVICE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

describe.skipIf(!runSuite)("panel Layer 2.5 — run-detail read", () => {
  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    await withDb(grantServiceRoleSelectLocalOnly);
  });

  afterAll(async () => {
    await withDb(cleanup);
  });

  it("returns run + steps + events + pull_request artifact shapes for a seeded run (CT-1..CT-5)", async () => {
    const slug = `rundetail-shapes-${randomUUID()}`;
    let runId = "";
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      runId = await insertRun(c, agentId, "failed", "needs_review");
      await insertStep(c, runId, 1, "checkout");
      await insertStep(c, runId, 2, "npm_audit");
      await insertEvents(c, runId, 5);
      await insertArtifact(c, runId, "https://github.com/llipe/x/pull/42");
    });

    const c = client();
    const run = await getRunById(c, runId);
    expect(run).not.toBeNull();
    // Came through v_runs → effective_status present (CT-1).
    expect(typeof run!.effective_status).toBe("string");
    expect(run!.status).toBe("failed");

    const steps = await getRunSteps(c, runId);
    expect(steps).toHaveLength(2);
    expect(steps[0].seq).toBeLessThan(steps[1].seq); // seq ascending (CT-3)

    const events = await getRunEvents(c, runId);
    expect(events).toHaveLength(5);
    // ascending by seq
    expect(events.map((e) => e.seq)).toEqual([1, 2, 3, 4, 5]);

    // AC14 read side: the pull_request artifact IS returned for a FAILED run (CT-4).
    const artifacts = await getRunArtifacts(c, runId);
    expect(artifacts).toHaveLength(1);
    expect(artifacts[0].type).toBe("pull_request");
    expect(artifacts[0].url).toBe("https://github.com/llipe/x/pull/42");
  });

  it("returns exactly the most-recent 2,000 events for a 2,500-event run, in seq order (SC-8/CT-2)", async () => {
    const slug = `rundetail-2500-${randomUUID()}`;
    let runId = "";
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      runId = await insertRun(c, agentId, "succeeded", "no_vulnerabilities");
      await insertEvents(c, runId, 2500);
    });

    const events = await getRunEvents(client(), runId);
    // SD11: bounded at 2,000, and NOT silently truncated to max_rows=1000.
    expect(events).toHaveLength(RUN_EVENTS_READ_LIMIT);
    // The MOST RECENT 2,000 = seq 501..2500, returned ascending for display.
    expect(events[0].seq).toBe(501);
    expect(events[events.length - 1].seq).toBe(2500);
    // Strictly ascending, no gaps.
    for (let i = 1; i < events.length; i++) {
      expect(events[i].seq).toBe(events[i - 1].seq + 1);
    }
  });

  it("load-earlier range read returns the prior slice with no overlap (SC-9)", async () => {
    const slug = `rundetail-earlier-${randomUUID()}`;
    let runId = "";
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      runId = await insertRun(c, agentId, "succeeded", "no_vulnerabilities");
      await insertEvents(c, runId, 2500);
    });

    const c = client();
    const recent = await getRunEvents(c, runId); // seq 501..2500
    const oldest = recent[0].seq; // 501
    // The prior window is seq 1..500.
    const earlier = await getRunEventsInRange(c, runId, 1, oldest - 1);
    expect(earlier).toHaveLength(500);
    expect(earlier[0].seq).toBe(1);
    expect(earlier[earlier.length - 1].seq).toBe(500);
    // No overlap with the recent window (max earlier < min recent).
    expect(earlier[earlier.length - 1].seq).toBeLessThan(oldest);
  });

  it("returns [] events and [] artifacts for a run with none (SC-11)", async () => {
    const slug = `rundetail-empty-${randomUUID()}`;
    let runId = "";
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      runId = await insertRun(c, agentId, "failed_to_start", null);
    });

    const c = client();
    expect(await getRunEvents(c, runId)).toEqual([]);
    expect(await getRunArtifacts(c, runId)).toEqual([]);
    expect(await getRunSteps(c, runId)).toEqual([]);
  });

  it("returns null for an unknown run id (AC9 read side)", async () => {
    const run = await getRunById(client(), randomUUID());
    expect(run).toBeNull();
  });
});

if (!runSuite) {
  describe("panel Layer 2.5 — run-detail read (skipped)", () => {
    it.skip(`SKIPPED: ${skipReason}`, () => {});
  });
}
