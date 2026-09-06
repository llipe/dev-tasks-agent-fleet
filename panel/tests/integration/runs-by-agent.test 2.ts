import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { Client } from "pg";
import { probeLocalDb, withDb } from "./db";
import { getAllRunsByAgentSlug, getStepProgressForRuns } from "@/lib/supabase/queries";
import { buildRunRows, type RunRowInput } from "@/lib/domain/run-row";
import type { VRunRow } from "@/lib/supabase/types";

/**
 * Layer 2.5 harness for the run-history read (S-108 / issue #121).
 *
 * Two properties that can only be proven against the real stack:
 *  - Runs return newest-first, unpaginated, from `v_runs` (AC-108.1).
 *  - **The AC10 standing guard (test-plan G5):** a synthetic stale `running`
 *    row — inserted with a small window, past its threshold — reads
 *    `timed_out` through `v_runs.effective_status`, and the run-history read
 *    path (query → row shaper) presents `timed_out`. The manual reaper-paused
 *    runbook verifies this once by hand; this test re-asserts it on every run
 *    so a regression that read the raw `status` fails CI.
 *
 * This test does NOT pause the reaper (that is the manual runbook's job on a
 * throwaway synthetic row). It relies on the read-time derivation, which is
 * independent of whether the reaper has run — exactly the two-layer guarantee.
 * To keep the assertion robust even if the reaper fires mid-test, it checks
 * that the effective status is `timed_out` whether the raw row is still
 * `running` (reaper behind) or already `timed_out` (reaper caught up).
 *
 * Docker-gated + service-role-key-gated, same as the other Layer 2.5 suites.
 * Skips with a recorded reason rather than passing vacuously (test-plan G2 —
 * a skip is not evidence; the story PR must state whether this ran live).
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
    [id, slug, `runhist test ${slug}`, "arn:test:runtime/runhist"],
  );
  createdAgentIds.push(id);
  return id;
}

// Insert a succeeded run created `minutesAgo` minutes ago.
async function insertSucceeded(c: Client, agentId: string, minutesAgo: number): Promise<string> {
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

// Insert one stale running run (started 25 min ago; small 90s window).
async function insertStaleRunning(c: Client, agentId: string): Promise<string> {
  const id = randomUUID();
  await c.query(
    `insert into runs (id, agent_id, agent_version, status,
                       queued_at, started_at, finished_at, created_at,
                       max_runtime_seconds, grace_seconds, start_timeout_seconds, outcome)
     values ($1, $2, '0.1.0', 'running',
             now() - interval '30 min', now() - interval '25 min', null,
             now() - interval '25 min',
             60, 30, 300, null)`,
    [id, agentId],
  );
  return id;
}

async function cleanup(c: Client): Promise<void> {
  for (const id of createdAgentIds) {
    await c.query(
      `delete from run_events where run_id in (select id from runs where agent_id = $1)`,
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

function toRunInput(row: VRunRow, done = 0, total = 0): RunRowInput {
  return {
    id: row.id,
    status: row.status,
    startedAtMs: row.started_at ? Date.parse(row.started_at) : null,
    queuedAtMs: Date.parse(row.queued_at),
    finishedAtMs: row.finished_at ? Date.parse(row.finished_at) : null,
    createdAtMs: Date.parse(row.created_at),
    durationMs: row.duration_ms,
    maxRuntimeSeconds: row.max_runtime_seconds,
    graceSeconds: row.grace_seconds,
    startTimeoutSeconds: row.start_timeout_seconds,
    outcome: row.outcome,
    repositoryFullName: row.repository_full_name,
    repositoryBranch: null,
    stepsDone: done,
    stepsTotal: total,
  };
}

describe.skipIf(!runSuite)("panel Layer 2.5 — run-history read", () => {
  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    await withDb(grantServiceRoleSelectLocalOnly);
  });

  afterAll(async () => {
    await withDb(cleanup);
  });

  it("returns runs newest-first, unpaginated, from v_runs (AC-108.1)", async () => {
    const slug = `runhist-order-${randomUUID()}`;
    await withDb(async (c) => {
      const id = await insertAgent(c, slug);
      await insertSucceeded(c, id, 60); // oldest
      await insertSucceeded(c, id, 30);
      await insertSucceeded(c, id, 5); // newest
    });

    const runs = await getAllRunsByAgentSlug(client(), slug);
    expect(runs).toHaveLength(3);
    // created_at strictly descending (newest-first).
    const times = runs.map((r) => Date.parse(r.created_at));
    for (let i = 1; i < times.length; i++) {
      expect(times[i - 1]).toBeGreaterThanOrEqual(times[i]);
    }
    // effective_status present (came through v_runs, not raw runs).
    expect(runs.every((r) => typeof r.effective_status === "string")).toBe(true);
  });

  it("presents a stale running run as timed_out through the read path (AC10 guard, G5)", async () => {
    const slug = `runhist-stale-${randomUUID()}`;
    let staleId = "";
    await withDb(async (c) => {
      const id = await insertAgent(c, slug);
      await insertSucceeded(c, id, 10);
      staleId = await insertStaleRunning(c, id);
    });

    const runs = await getAllRunsByAgentSlug(client(), slug);
    const stale = runs.find((r) => r.id === staleId);
    expect(stale).toBeDefined();

    // The view derives timed_out regardless of whether the reaper has run.
    expect(stale!.effective_status).toBe("timed_out");
    // Raw status is either still running (reaper behind) or already timed_out.
    expect(["running", "timed_out"]).toContain(stale!.status);

    // The row shaper (the actual UI read path) must present timed_out.
    const rows = buildRunRows(
      runs.map((r) => toRunInput(r)),
      Date.now(),
    );
    const staleRow = rows.find((r) => r.id === staleId);
    expect(staleRow?.effectiveStatus).toBe("timed_out");
  });

  it("returns an empty list for an agent with no runs, never null", async () => {
    const slug = `runhist-empty-${randomUUID()}`;
    await withDb(async (c) => {
      await insertAgent(c, slug);
    });
    const runs = await getAllRunsByAgentSlug(client(), slug);
    expect(Array.isArray(runs)).toBe(true);
    expect(runs).toHaveLength(0);
  });

  it("returns an empty step-progress map for an empty id list (no read issued)", async () => {
    const progress = await getStepProgressForRuns(client(), []);
    expect(progress.size).toBe(0);
  });

  it("folds step progress as done=non-pending / total, in one grouped read (gap #1)", async () => {
    const slug = `runhist-steps-${randomUUID()}`;
    let runId = "";
    await withDb(async (c) => {
      const id = await insertAgent(c, slug);
      runId = await insertSucceeded(c, id, 5);
      // 4 steps: 3 non-pending (done) + 1 pending → expect done=3, total=4.
      await c.query(
        `insert into run_steps (run_id, seq, key, status) values
           ($1, 1, 'checkout', 'succeeded'),
           ($1, 2, 'npm_audit', 'succeeded'),
           ($1, 3, 'test', 'failed'),
           ($1, 4, 'open_pr', 'pending')`,
        [runId],
      );
    });

    const progress = await getStepProgressForRuns(client(), [runId]);
    const p = progress.get(runId);
    expect(p).toBeDefined();
    expect(p).toEqual({ done: 3, total: 4 });

    // And it reaches the rendered `n/m` via the shaper.
    const runs = await getAllRunsByAgentSlug(client(), slug);
    const rows = buildRunRows(
      runs.map((r) => toRunInput(r, progress.get(r.id)?.done ?? 0, progress.get(r.id)?.total ?? 0)),
      Date.now(),
    );
    expect(rows.find((r) => r.id === runId)?.steps).toBe("3/4");
  });
});

if (!runSuite) {
  describe("panel Layer 2.5 — run-history read (skipped)", () => {
    it.skip(`SKIPPED: ${skipReason}`, () => {});
  });
}
