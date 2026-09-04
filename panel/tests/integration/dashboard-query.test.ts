import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { Client } from "pg";
import { probeLocalDb, withDb } from "./db";
import { getDashboardData } from "@/lib/supabase/queries";
import { buildAgentSummaries, type AgentSummaryInput } from "@/lib/domain/dashboard";

/**
 * Layer 2.5 harness for the dashboard read (S-107 / issue #120, CT-1/CT-7/CT-8).
 *
 * Three properties that can only be proven against the real stack:
 *  - CT-7: the read is two requests total, never one-per-agent. Asserted by
 *    instrumenting the PostgREST client's `fetch` and confirming the request
 *    count does not grow when the agent count doubles.
 *  - CT-8: an agent with more than PostgREST `max_rows` (1000) runs is counted
 *    truthfully — a displayed count of exactly 1000 against 1400 seeded rows is
 *    a FAIL, not a rounding artifact.
 *  - CT-1: a stale `running` row is counted in the `timed_out` bucket by the
 *    shaper fed from the real rows, not the `running` bucket.
 *
 * Docker-gated + service-role-key-gated, same as queries.test.ts. Skips with a
 * recorded reason rather than passing vacuously (test-plan G2 — a skip is not
 * evidence; the story PR must state whether this ran live).
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
    [id, slug, `dash test ${slug}`, "arn:test:runtime/dash"],
  );
  createdAgentIds.push(id);
  return id;
}

// Insert `n` succeeded runs for an agent efficiently (batched).
async function insertSucceededRuns(c: Client, agentId: string, n: number): Promise<void> {
  const BATCH = 500;
  for (let start = 0; start < n; start += BATCH) {
    const count = Math.min(BATCH, n - start);
    const values: string[] = [];
    for (let i = 0; i < count; i++) {
      values.push(
        `(gen_random_uuid(), '${agentId}', '0.1.0', 'succeeded',
          now() - interval '5 min', now() - interval '4 min', now() - interval '1 min',
          900, 60, 300, 'no_vulnerabilities')`,
      );
    }
    await c.query(
      `insert into runs (id, agent_id, agent_version, status,
                         queued_at, started_at, finished_at,
                         max_runtime_seconds, grace_seconds, start_timeout_seconds, outcome)
       values ${values.join(",")}`,
    );
  }
}

// Insert one stale running run (started well past its window).
async function insertStaleRunning(c: Client, agentId: string): Promise<void> {
  await c.query(
    `insert into runs (id, agent_id, agent_version, status,
                       queued_at, started_at, finished_at,
                       max_runtime_seconds, grace_seconds, start_timeout_seconds, outcome)
     values (gen_random_uuid(), $1, '0.1.0', 'running',
             now() - interval '30 min', now() - interval '25 min', null,
             900, 60, 300, null)`,
    [agentId],
  );
}

async function cleanup(c: Client): Promise<void> {
  for (const id of createdAgentIds) {
    await c.query(`delete from runs where agent_id = $1`, [id]);
    await c.query(`delete from agents where id = $1`, [id]);
  }
  createdAgentIds.length = 0;
}

// Build a fetch wrapper that counts PostgREST requests (the /rest/v1 calls).
function countingClient(): { client: SupabaseClient; count: () => number } {
  let requests = 0;
  const client = createClient(API_URL, SERVICE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false },
    global: {
      fetch: (input: RequestInfo | URL, init?: RequestInit) => {
        requests += 1;
        return fetch(input, init);
      },
    },
  });
  return { client, count: () => requests };
}

describe.skipIf(!runSuite)("panel Layer 2.5 — dashboard read", () => {
  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    await withDb(grantServiceRoleSelectLocalOnly);
  });

  afterAll(async () => {
    await withDb(cleanup);
  });

  it("is two reads regardless of agent count — never N+1 (CT-7)", async () => {
    // 8 agents, each with a few runs.
    await withDb(async (c) => {
      for (let i = 0; i < 8; i++) {
        const id = await insertAgent(c, `dash-ct7-a-${randomUUID()}`);
        await insertSucceededRuns(c, id, 3);
      }
    });

    const first = countingClient();
    await getDashboardData(first.client);
    const eightAgentRequests = first.count();

    // Double to 16 agents.
    await withDb(async (c) => {
      for (let i = 0; i < 8; i++) {
        const id = await insertAgent(c, `dash-ct7-b-${randomUUID()}`);
        await insertSucceededRuns(c, id, 3);
      }
    });

    const second = countingClient();
    await getDashboardData(second.client);
    const sixteenAgentRequests = second.count();

    // The count must not grow with agent count. Small runs → one agents read +
    // one runs page each time. Allow equality, forbid doubling.
    expect(sixteenAgentRequests).toBe(eightAgentRequests);
    expect(eightAgentRequests).toBeLessThanOrEqual(3);
  });

  it("counts an agent with >1000 runs truthfully, not capped at max_rows (CT-8)", async () => {
    const OVER = 1400;
    let agentId = "";
    await withDb(async (c) => {
      agentId = await insertAgent(c, `dash-ct8-${randomUUID()}`);
      await insertSucceededRuns(c, agentId, OVER);
    });

    const { client } = countingClient();
    const data = await getDashboardData(client);
    const agentInput: AgentSummaryInput[] = data.agents
      .filter((a) => a.id === agentId)
      .map((a) => ({
        id: a.id,
        slug: a.slug,
        name: a.name,
        description: a.description,
        requiresRepository: a.requires_repository,
        runs: data.runs
          .filter((r) => r.agent_id === a.id)
          .map((r) => ({
            status: r.status,
            startedAtMs: r.started_at ? Date.parse(r.started_at) : null,
            queuedAtMs: Date.parse(r.queued_at),
            finishedAtMs: r.finished_at ? Date.parse(r.finished_at) : null,
            createdAtMs: Date.parse(r.created_at),
            maxRuntimeSeconds: r.max_runtime_seconds,
            graceSeconds: r.grace_seconds,
            startTimeoutSeconds: r.start_timeout_seconds,
            outcome: r.outcome,
          })),
      }));
    const summaries = buildAgentSummaries(agentInput, Date.now());
    const summary = summaries.find((s) => s.id === agentId);
    expect(summary).toBeDefined();
    // The exact CT-8 assertion: 1400 seeded, count must be 1400 — not 1000.
    expect(summary?.runCount).toBe(OVER);
    expect(summary?.breakdown.succeeded).toBe(OVER);
  });

  it("counts a stale running run as timed_out in the breakdown (CT-1)", async () => {
    let agentId = "";
    await withDb(async (c) => {
      agentId = await insertAgent(c, `dash-ct1-${randomUUID()}`);
      await insertSucceededRuns(c, agentId, 2);
      await insertStaleRunning(c, agentId);
    });

    const { client } = countingClient();
    const data = await getDashboardData(client);
    const a = data.agents.find((x) => x.id === agentId)!;
    const summaries = buildAgentSummaries(
      [
        {
          id: a.id,
          slug: a.slug,
          name: a.name,
          description: a.description,
          requiresRepository: a.requires_repository,
          runs: data.runs
            .filter((r) => r.agent_id === a.id)
            .map((r) => ({
              status: r.status,
              startedAtMs: r.started_at ? Date.parse(r.started_at) : null,
              queuedAtMs: Date.parse(r.queued_at),
              finishedAtMs: r.finished_at ? Date.parse(r.finished_at) : null,
              createdAtMs: Date.parse(r.created_at),
              maxRuntimeSeconds: r.max_runtime_seconds,
              graceSeconds: r.grace_seconds,
              startTimeoutSeconds: r.start_timeout_seconds,
              outcome: r.outcome,
            })),
        },
      ],
      Date.now(),
    );
    const summary = summaries.find((s) => s.id === agentId);
    expect(summary?.breakdown.running).toBe(0);
    expect(summary?.breakdown.timed_out).toBe(1);
    expect(summary?.breakdown.succeeded).toBe(2);
  });

  it("returns the seeded dependency-update agent with correct shape (AC-107.1)", async () => {
    const { client } = countingClient();
    const data = await getDashboardData(client);
    expect(Array.isArray(data.agents)).toBe(true);
    expect(Array.isArray(data.runs)).toBe(true);
    const dep = data.agents.find((a) => a.slug === "dependency-update");
    expect(dep).toBeDefined();
  });
});

if (!runSuite) {
  describe("panel Layer 2.5 — dashboard read (skipped)", () => {
    it.skip(`SKIPPED: ${skipReason}`, () => {});
  });
}
