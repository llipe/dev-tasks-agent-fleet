import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import type { Client } from "pg";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 harness for reap_stale_runs() (S-103 / issue #116). These tests
// exercise the REAL reaper function on a live local Postgres (never mocked —
// TESTING.md Layer 2.5 boundary) and pin its full behavioral contract:
//   - runs.status transitions (timed_out / failed_to_start)
//   - error_code (RUNTIME_TIMEOUT / START_TIMEOUT) — MUST be preserved
//   - the explanatory run_events row at seq = max(seq)+1
//   - data.reaped_by / data.reason
//   - the issue #99 open-run_steps closure on BOTH branches
//   - the human-readable message + error_message text
//
// This file is authored test-first against the CURRENT (Spanish) message text
// so the S-103 English migration can be proven behavior-preserving: every
// non-message assertion must survive the migration untouched, and only the
// text-content expectations flip to English (task 2.5).
//
// Docker-gated: when the local stack is down the whole suite skips with a
// recorded reason (TESTING.md), so it stays reachable from `make validate`
// without turning a missing daemon into a red gate.

const probe = await probeLocalDb();

// A run row requires an agent (FK agent_id -> agents.id, on delete restrict)
// and the not-null snapshot columns. We create a throwaway agent per test run
// and clean up everything we insert in afterEach.
interface Fixture {
  agentId: string;
  runIds: string[];
}

async function insertAgent(c: Client): Promise<string> {
  const id = randomUUID();
  await c.query(
    `insert into agents (id, slug, name, runtime_arn, requires_repository,
                         max_runtime_seconds, grace_seconds, start_timeout_seconds)
     values ($1, $2, $3, $4, false, 3600, 120, 300)`,
    [id, `s103-test-${id}`, "S-103 reaper test agent", "arn:test:runtime/s103"],
  );
  return id;
}

// Insert a run already past its running -> timed_out threshold:
// started_at is (max_runtime + grace + 60s) in the past.
async function insertStaleRunningRun(c: Client, agentId: string): Promise<string> {
  const id = randomUUID();
  await c.query(
    `insert into runs (id, agent_id, agent_version, status,
                       queued_at, started_at,
                       max_runtime_seconds, grace_seconds, start_timeout_seconds)
     values ($1, $2, '0.1.0', 'running',
             now() - interval '2 hours',
             now() - make_interval(secs => 3600 + 120 + 60),
             3600, 120, 300)`,
    [id, agentId],
  );
  return id;
}

// Insert a run still queued past its start_timeout: queued_at is
// (start_timeout + 60s) in the past, started_at null.
async function insertStaleQueuedRun(c: Client, agentId: string): Promise<string> {
  const id = randomUUID();
  await c.query(
    `insert into runs (id, agent_id, agent_version, status,
                       queued_at,
                       max_runtime_seconds, grace_seconds, start_timeout_seconds)
     values ($1, $2, '0.1.0', 'queued',
             now() - make_interval(secs => 300 + 60),
             3600, 120, 300)`,
    [id, agentId],
  );
  return id;
}

async function insertStep(
  c: Client,
  runId: string,
  seq: number,
  status: string,
): Promise<string> {
  const id = randomUUID();
  await c.query(
    `insert into run_steps (id, run_id, seq, key, status, started_at)
     values ($1, $2, $3, $4, $5, now() - interval '90 minutes')`,
    [id, runId, seq, `step-${seq}`, status],
  );
  return id;
}

describe.skipIf(!probe.available)("panel Layer 2.5 — reap_stale_runs()", () => {
  const created: Fixture = { agentId: "", runIds: [] };

  beforeAll(() => {
    console.log(`[integration] ${probe.reason}`);
  });

  afterEach(async () => {
    // Clean up in FK-safe order. run_events / run_steps / run_artifacts cascade
    // from runs, but we delete explicitly to keep the table tidy for repeat runs.
    await withDb(async (c) => {
      for (const runId of created.runIds) {
        await c.query(`delete from run_events where run_id = $1`, [runId]);
        await c.query(`delete from run_steps where run_id = $1`, [runId]);
        await c.query(`delete from runs where id = $1`, [runId]);
      }
      if (created.agentId) {
        await c.query(`delete from agents where id = $1`, [created.agentId]);
      }
    });
    created.agentId = "";
    created.runIds = [];
  });

  it("transitions a stale running run to timed_out with RUNTIME_TIMEOUT", async () => {
    await withDb(async (c) => {
      created.agentId = await insertAgent(c);
      const runId = await insertStaleRunningRun(c, created.agentId);
      created.runIds.push(runId);

      const reaped = await c
        .query<{ reap_stale_runs: number }>(`select reap_stale_runs()`)
        .then((r) => r.rows[0]?.reap_stale_runs);
      expect(reaped).toBeGreaterThanOrEqual(1);

      const run = await c
        .query(
          `select status, error_code, finished_at, error_message
             from runs where id = $1`,
          [runId],
        )
        .then((r) => r.rows[0]);
      expect(run.status).toBe("timed_out");
      expect(run.error_code).toBe("RUNTIME_TIMEOUT");
      expect(run.finished_at).not.toBeNull();
      // CURRENT (Spanish) error_message text — flips to English in task 2.5.
      expect(run.error_message).toContain("Sin reporte de término");
    });
  });

  it("writes the explanatory event at seq = max(seq)+1 with reaped_by/reason", async () => {
    await withDb(async (c) => {
      created.agentId = await insertAgent(c);
      const runId = await insertStaleRunningRun(c, created.agentId);
      created.runIds.push(runId);

      // Seed two pre-existing events so max(seq) = 5; the reaper must use 6.
      await c.query(
        `insert into run_events (run_id, seq, level, message) values
           ($1, 4, 'info', 'pre-existing event a'),
           ($1, 5, 'info', 'pre-existing event b')`,
        [runId],
      );

      await c.query(`select reap_stale_runs()`);

      const ev = await c
        .query(
          `select seq, level, message, data
             from run_events
            where run_id = $1 and data->>'reaped_by' = 'reap_stale_runs'`,
          [runId],
        )
        .then((r) => r.rows);
      expect(ev).toHaveLength(1);
      expect(ev[0].seq).toBe(6); // max(5)+1
      expect(ev[0].level).toBe("error");
      expect(ev[0].data.reaped_by).toBe("reap_stale_runs");
      expect(ev[0].data.reason).toBe("RUNTIME_TIMEOUT");
      // CURRENT (Spanish) message — flips to English in task 2.5.
      expect(ev[0].message).toContain("timed_out");
      expect(ev[0].message).toContain("el agente nunca reportó término");
    });
  });

  it("closes open run_steps as failed on the timed_out branch (issue #99)", async () => {
    await withDb(async (c) => {
      created.agentId = await insertAgent(c);
      const runId = await insertStaleRunningRun(c, created.agentId);
      created.runIds.push(runId);

      const runningStep = await insertStep(c, runId, 1, "running");
      const pendingStep = await insertStep(c, runId, 2, "pending");
      const doneStep = await insertStep(c, runId, 3, "succeeded");

      await c.query(`select reap_stale_runs()`);

      const steps = await c
        .query(
          `select id, status, finished_at, error_message
             from run_steps where run_id = $1 order by seq`,
          [runId],
        )
        .then((r) => r.rows);

      const byId = Object.fromEntries(steps.map((s) => [s.id, s]));
      // running + pending get closed as failed with finished_at + attribution
      expect(byId[runningStep].status).toBe("failed");
      expect(byId[runningStep].finished_at).not.toBeNull();
      expect(byId[runningStep].error_message).toContain("reap_stale_runs");
      expect(byId[pendingStep].status).toBe("failed");
      // already-terminal step is left untouched
      expect(byId[doneStep].status).toBe("succeeded");
      expect(byId[doneStep].error_message).toBeNull();
    });
  });

  it("transitions a stale queued run to failed_to_start with START_TIMEOUT", async () => {
    await withDb(async (c) => {
      created.agentId = await insertAgent(c);
      const runId = await insertStaleQueuedRun(c, created.agentId);
      created.runIds.push(runId);

      await c.query(`select reap_stale_runs()`);

      const run = await c
        .query(`select status, error_code, error_message from runs where id = $1`, [runId])
        .then((r) => r.rows[0]);
      expect(run.status).toBe("failed_to_start");
      expect(run.error_code).toBe("START_TIMEOUT");
      // CURRENT (Spanish) error_message — flips to English in task 2.5.
      expect(run.error_message).toContain("no reportó inicio");

      const ev = await c
        .query(
          `select message, data
             from run_events
            where run_id = $1 and data->>'reaped_by' = 'reap_stale_runs'`,
          [runId],
        )
        .then((r) => r.rows[0]);
      expect(ev.data.reason).toBe("START_TIMEOUT");
      // CURRENT (Spanish) message — flips to English in task 2.5.
      expect(ev.message).toContain("nunca reportó inicio");
    });
  });

  it("is a safe no-op for a queued run that has no steps", async () => {
    await withDb(async (c) => {
      created.agentId = await insertAgent(c);
      const runId = await insertStaleQueuedRun(c, created.agentId);
      created.runIds.push(runId);

      // No steps inserted; the step-closure UPDATE must be a 0-row no-op.
      await expect(c.query(`select reap_stale_runs()`)).resolves.toBeDefined();

      const stepCount = await c
        .query<{ n: string }>(`select count(*)::text as n from run_steps where run_id = $1`, [
          runId,
        ])
        .then((r) => r.rows[0]?.n);
      expect(stepCount).toBe("0");
    });
  });

  it("leaves an already-terminal run untouched on a second pass", async () => {
    await withDb(async (c) => {
      created.agentId = await insertAgent(c);
      const runId = await insertStaleRunningRun(c, created.agentId);
      created.runIds.push(runId);

      await c.query(`select reap_stale_runs()`);
      const first = await c
        .query(`select finished_at from runs where id = $1`, [runId])
        .then((r) => r.rows[0]?.finished_at);

      // Second pass: the run is now timed_out (not running/queued), so the
      // reaper must not touch it — finished_at stays put and no new event.
      await c.query(`select reap_stale_runs()`);
      const second = await c
        .query(`select finished_at from runs where id = $1`, [runId])
        .then((r) => r.rows[0]?.finished_at);
      expect(second).toEqual(first);

      const reaperEvents = await c
        .query<{ n: string }>(
          `select count(*)::text as n from run_events
            where run_id = $1 and data->>'reaped_by' = 'reap_stale_runs'`,
          [runId],
        )
        .then((r) => r.rows[0]?.n);
      expect(reaperEvents).toBe("1");
    });
  });

  it("handles a stale run whose max(seq) is null (no prior events)", async () => {
    await withDb(async (c) => {
      created.agentId = await insertAgent(c);
      const runId = await insertStaleRunningRun(c, created.agentId);
      created.runIds.push(runId);

      // No pre-existing events: coalesce(max(seq),0)+1 must yield seq = 1.
      await c.query(`select reap_stale_runs()`);
      const ev = await c
        .query(
          `select seq from run_events
            where run_id = $1 and data->>'reaped_by' = 'reap_stale_runs'`,
          [runId],
        )
        .then((r) => r.rows[0]);
      expect(ev.seq).toBe(1);
    });
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — reap_stale_runs() (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
