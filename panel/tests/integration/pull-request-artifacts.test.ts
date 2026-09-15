import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { Client } from "pg";
import { probeLocalDb, withDb } from "./db";
import { getPullRequestArtifactsForRuns } from "@/lib/supabase/queries";

/**
 * Layer 2.5 harness for the Run History inline PR-link read (Story S-144,
 * spec §10/§11, issue #204).
 *
 * Load-bearing properties that can only be proven against the real stack:
 *  - A single grouped read regardless of the number of run ids on the page —
 *    never N+1 (AC3).
 *  - Empty id list -> `{}`, zero-cost (no read issued at all).
 *  - A non-`pull_request` artifact type (e.g. `diff`) is excluded from the
 *    result even when it is the newest artifact for that run.
 *  - The v1.1 addendum tie-break: when a single run carries more than one
 *    `pull_request` artifact, the most-recently-created one wins
 *    (`order by created_at desc limit 1` per `run_id`), not incidental
 *    row order.
 *
 * Docker-gated + service-role-key-gated, same pattern as the other Layer 2.5
 * suites (`filtered-runs.test.ts`, `run-detail-queries.test.ts`).
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
    [id, slug, `pr-artifacts test ${slug}`, "arn:test:runtime/pr-artifacts"],
  );
  createdAgentIds.push(id);
  return id;
}

async function insertRun(c: Client, agentId: string, minutesAgo = 10): Promise<string> {
  const id = randomUUID();
  await c.query(
    `insert into runs (id, agent_id, agent_version, status,
                       queued_at, started_at, finished_at, created_at,
                       max_runtime_seconds, grace_seconds, start_timeout_seconds, outcome)
     values ($1, $2, '0.1.0', 'succeeded',
             now() - ($3 || ' min')::interval - interval '1 min',
             now() - ($3 || ' min')::interval,
             now() - ($3 || ' min')::interval + interval '3 min',
             now() - ($3 || ' min')::interval,
             900, 60, 300, 'no_vulnerabilities')`,
    [id, agentId, String(minutesAgo)],
  );
  return id;
}

async function insertArtifact(
  c: Client,
  runId: string,
  type: string,
  url: string,
  createdAtOffsetSeconds = 0,
): Promise<string> {
  const id = randomUUID();
  await c.query(
    `insert into run_artifacts (id, run_id, type, title, url, created_at)
     values ($1, $2, $3::artifact_type, 'Bump lodash', $4, now() + ($5 || ' seconds')::interval)`,
    [id, runId, type, url, String(createdAtOffsetSeconds)],
  );
  return id;
}

async function cleanup(c: Client): Promise<void> {
  for (const id of createdAgentIds) {
    await c.query(
      `delete from run_artifacts where run_id in (select id from runs where agent_id = $1)`,
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

// Build a fetch wrapper that counts PostgREST requests (the /rest/v1 calls),
// same pattern as `dashboard-query.test.ts`'s CT-7 assertion.
function countingClient(): { client: SupabaseClient; count: () => number } {
  let requests = 0;
  const c = createClient(API_URL, SERVICE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false },
    global: {
      fetch: (input: RequestInfo | URL, init?: RequestInit) => {
        requests += 1;
        return fetch(input, init);
      },
    },
  });
  return { client: c, count: () => requests };
}

describe.skipIf(!runSuite)("panel Layer 2.5 — getPullRequestArtifactsForRuns", () => {
  beforeAll(async () => {
    console.log(`[integration] ${probe.reason || skipReason}`);
    await withDb(grantServiceRoleSelectLocalOnly);
  });

  afterAll(async () => {
    await withDb(cleanup);
  });

  it("returns an empty object for an empty id list — no read issued (zero-cost)", async () => {
    const { client: c, count } = countingClient();
    const result = await getPullRequestArtifactsForRuns(c, []);
    expect(result).toEqual({});
    expect(count()).toBe(0);
  });

  it("returns the pull_request artifact for a run that carries one (AC1)", async () => {
    const slug = `pr-basic-${randomUUID()}`;
    let runId = "";
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      runId = await insertRun(c, agentId);
      await insertArtifact(c, runId, "pull_request", "https://github.com/llipe/x/pull/42");
    });

    const result = await getPullRequestArtifactsForRuns(client(), [runId]);
    expect(result[runId]).toBeDefined();
    expect(result[runId].url).toBe("https://github.com/llipe/x/pull/42");
    expect(result[runId].type).toBe("pull_request");
  });

  it("excludes a run with no pull_request artifact (AC2) — absent from the result", async () => {
    const slug = `pr-none-${randomUUID()}`;
    let runId = "";
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      runId = await insertRun(c, agentId);
    });

    const result = await getPullRequestArtifactsForRuns(client(), [runId]);
    expect(result[runId]).toBeUndefined();
  });

  it("excludes a non-pull_request artifact type even when it is the only/newest artifact", async () => {
    const slug = `pr-wrongtype-${randomUUID()}`;
    let runId = "";
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      runId = await insertRun(c, agentId);
      await insertArtifact(c, runId, "diff", "https://github.com/llipe/x/commit/abc.diff");
    });

    const result = await getPullRequestArtifactsForRuns(client(), [runId]);
    expect(result[runId]).toBeUndefined();
  });

  it("resolves multiple pull_request artifacts on one run via most-recent-created_at tie-break (v1.1 addendum)", async () => {
    const slug = `pr-tiebreak-${randomUUID()}`;
    let runId = "";
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      runId = await insertRun(c, agentId);
      // Older PR artifact first, then a newer superseding one.
      await insertArtifact(
        c,
        runId,
        "pull_request",
        "https://github.com/llipe/x/pull/1",
        -60, // created 60s in the past relative to now()
      );
      await insertArtifact(
        c,
        runId,
        "pull_request",
        "https://github.com/llipe/x/pull/2",
        0, // most recent
      );
    });

    const result = await getPullRequestArtifactsForRuns(client(), [runId]);
    expect(result[runId]).toBeDefined();
    expect(result[runId].url).toBe("https://github.com/llipe/x/pull/2");
  });

  it("is a single grouped read regardless of the number of run ids on the page — never N+1 (AC3)", async () => {
    const slug = `pr-n1-${randomUUID()}`;
    const runIdsSmall: string[] = [];
    const runIdsLarge: string[] = [];
    await withDb(async (c) => {
      const agentId = await insertAgent(c, slug);
      for (let i = 0; i < 3; i++) {
        const id = await insertRun(c, agentId, 10 + i);
        await insertArtifact(c, id, "pull_request", `https://github.com/llipe/x/pull/${i}`);
        runIdsSmall.push(id);
      }
      for (let i = 0; i < 25; i++) {
        const id = await insertRun(c, agentId, 40 + i);
        await insertArtifact(c, id, "pull_request", `https://github.com/llipe/x/pull/l${i}`);
        runIdsLarge.push(id);
      }
    });

    const small = countingClient();
    await getPullRequestArtifactsForRuns(small.client, runIdsSmall);
    const smallRequests = small.count();

    const large = countingClient();
    await getPullRequestArtifactsForRuns(large.client, [...runIdsSmall, ...runIdsLarge]);
    const largeRequests = large.count();

    // Request count does not grow with the number of run ids on the page.
    expect(smallRequests).toBe(1);
    expect(largeRequests).toBe(1);
  });
});
