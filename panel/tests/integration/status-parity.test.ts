import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import type { Client } from "pg";
import { probeLocalDb, withDb } from "./db";
import { effectiveStatus, type RunStatus, type StatusInput } from "@/lib/domain/status";

// Layer 2.5 SR3 parity harness (S-104 / issue #117, CT-1..CT-4). Proves the
// TypeScript `effectiveStatus` (lib/domain/status.ts) agrees, row-for-row,
// with the canonical SQL `v_runs.effective_status` case expression over a
// fixture matrix that includes exact-boundary rows. The DB is never mocked
// (TESTING.md Layer 2.5 boundary).
//
// Clock discipline: each row is read back together with the DB's own `now()`,
// and that same instant is injected into `effectiveStatus`, so the two sides
// are compared against one clock — never a JS `Date.now()` that skews from the
// Postgres clock by a few ms and turns an exact-boundary row into a flake.
//
// Docker-gated: skips with a recorded reason when the local stack is down, so
// it stays reachable from `make validate` without a daemon.
//
// G2 note: this is the one test pinning SD4's duplicated SQL/TS logic. Locally
// it runs against a real stack; in CI the Node job MUST start the stack and
// treat a skip here as a failure (test plan G2). A green `make validate` with
// this suite skipped asserts nothing about parity.

const probe = await probeLocalDb();

interface ParityFixture {
  agentId: string;
  runIds: string[];
}

async function insertAgent(c: Client): Promise<string> {
  const id = randomUUID();
  await c.query(
    `insert into agents (id, slug, name, runtime_arn, requires_repository,
                         max_runtime_seconds, grace_seconds, start_timeout_seconds)
     values ($1, $2, $3, $4, false, 900, 60, 300)`,
    [id, `s104-parity-${id}`, "S-104 parity test agent", "arn:test:runtime/s104"],
  );
  return id;
}

// Insert a run with explicit clocks expressed as an offset (seconds) applied to
// the DB `now()` at insert time. A `startedOffsetSecs` of -960 means
// started_at = now() - 960s (exactly at the 900+60 threshold). Null offsets
// leave the timestamp null.
interface RunSpec {
  status: RunStatus;
  startedOffsetSecs: number | null;
  queuedOffsetSecs: number;
  maxRuntimeSeconds?: number;
  graceSeconds?: number;
  startTimeoutSeconds?: number;
  label: string;
}

async function insertRun(c: Client, agentId: string, spec: RunSpec): Promise<string> {
  const id = randomUUID();
  const max = spec.maxRuntimeSeconds ?? 900;
  const grace = spec.graceSeconds ?? 60;
  const startTimeout = spec.startTimeoutSeconds ?? 300;
  await c.query(
    `insert into runs (id, agent_id, agent_version, status,
                       queued_at,
                       started_at,
                       max_runtime_seconds, grace_seconds, start_timeout_seconds,
                       outcome)
     values ($1, $2, '0.1.0', $3::run_status,
             now() - make_interval(secs => $4::int),
             case when $5::int is null then null
                  else now() - make_interval(secs => $5::int) end,
             $6::int, $7::int, $8::int,
             case when $3::text = 'succeeded' then 'no_vulnerabilities'::run_outcome else null end)`,
    [
      id,
      agentId,
      spec.status,
      spec.queuedOffsetSecs,
      spec.startedOffsetSecs,
      max,
      grace,
      startTimeout,
    ],
  );
  return id;
}

// Read a run back through v_runs together with the DB clock, and build the
// StatusInput the TS mirror consumes. All timestamps -> epoch ms.
async function readParityRow(
  c: Client,
  runId: string,
): Promise<{ sqlEffective: RunStatus; tsInput: StatusInput; nowMs: number; label: string }> {
  const row = await c
    .query(
      `select v.status, v.effective_status,
              extract(epoch from v.started_at) * 1000 as started_ms,
              extract(epoch from v.queued_at)  * 1000 as queued_ms,
              v.max_runtime_seconds, v.grace_seconds, v.start_timeout_seconds,
              extract(epoch from now()) * 1000 as now_ms
         from v_runs v where v.id = $1`,
      [runId],
    )
    .then((r) => r.rows[0]);

  return {
    sqlEffective: row.effective_status as RunStatus,
    nowMs: Number(row.now_ms),
    label: runId,
    tsInput: {
      status: row.status as RunStatus,
      startedAtMs: row.started_ms === null ? null : Number(row.started_ms),
      queuedAtMs: row.queued_ms === null ? null : Number(row.queued_ms),
      maxRuntimeSeconds: row.max_runtime_seconds === null ? null : Number(row.max_runtime_seconds),
      graceSeconds: row.grace_seconds === null ? null : Number(row.grace_seconds),
      startTimeoutSeconds:
        row.start_timeout_seconds === null ? null : Number(row.start_timeout_seconds),
    },
  };
}

// The fixture matrix: {status} x {fresh, stale}, plus the boundary and null
// specials. "stale" clocks are set well past the threshold; "fresh" well
// inside it. Boundary rows are handled in their own test with tight offsets.
const MATRIX: RunSpec[] = [
  // running
  { status: "running", startedOffsetSecs: 10, queuedOffsetSecs: 70, label: "running-fresh" },
  {
    status: "running",
    startedOffsetSecs: 960 + 120,
    queuedOffsetSecs: 960 + 180,
    label: "running-stale",
  },
  // queued
  { status: "queued", startedOffsetSecs: null, queuedOffsetSecs: 10, label: "queued-fresh" },
  {
    status: "queued",
    startedOffsetSecs: null,
    queuedOffsetSecs: 300 + 120,
    label: "queued-stale",
  },
  // terminal statuses with stale clocks — must all pass through (EC-4)
  {
    status: "succeeded",
    startedOffsetSecs: 5000,
    queuedOffsetSecs: 6000,
    label: "succeeded-stale",
  },
  { status: "failed", startedOffsetSecs: 5000, queuedOffsetSecs: 6000, label: "failed-stale" },
  {
    status: "canceled",
    startedOffsetSecs: 5000,
    queuedOffsetSecs: 6000,
    label: "canceled-stale",
  },
  {
    status: "timed_out",
    startedOffsetSecs: 5000,
    queuedOffsetSecs: 6000,
    label: "timed_out-stale",
  },
  {
    status: "failed_to_start",
    startedOffsetSecs: null,
    queuedOffsetSecs: 6000,
    label: "failed_to_start-stale",
  },
];

describe.skipIf(!probe.available)("panel Layer 2.5 — effectiveStatus ⇄ v_runs parity", () => {
  const created: ParityFixture = { agentId: "", runIds: [] };

  beforeAll(() => {
    console.log(`[integration] ${probe.reason}`);
  });

  afterEach(async () => {
    await withDb(async (c) => {
      for (const runId of created.runIds) {
        await c.query(`delete from runs where id = $1`, [runId]);
      }
      if (created.agentId) {
        await c.query(`delete from agents where id = $1`, [created.agentId]);
      }
    });
    created.agentId = "";
    created.runIds = [];
  });

  it("agrees on every status × clock combination in the matrix (CT-1)", async () => {
    await withDb(async (c) => {
      created.agentId = await insertAgent(c);
      for (const spec of MATRIX) {
        const runId = await insertRun(c, created.agentId, spec);
        created.runIds.push(runId);
        const { sqlEffective, tsInput, nowMs } = await readParityRow(c, runId);
        const tsEffective = effectiveStatus(tsInput, nowMs);
        expect(
          tsEffective,
          `disagreement on "${spec.label}" (status=${tsInput.status}): sql=${sqlEffective} ts=${tsEffective}`,
        ).toBe(sqlEffective);
      }
    });
  });

  it("null started_at on a running row does not derive timed_out (CT-3)", async () => {
    await withDb(async (c) => {
      created.agentId = await insertAgent(c);
      // running with null started_at and a very old queued_at
      const runId = await insertRun(c, created.agentId, {
        status: "running",
        startedOffsetSecs: null,
        queuedOffsetSecs: 100000,
        label: "running-null-started",
      });
      created.runIds.push(runId);
      const { sqlEffective, tsInput, nowMs } = await readParityRow(c, runId);
      expect(sqlEffective).toBe("running");
      expect(effectiveStatus(tsInput, nowMs)).toBe("running");
    });
  });

  it("resolves exact-boundary and ±1s rows identically on both sides (CT-2)", async () => {
    await withDb(async (c) => {
      created.agentId = await insertAgent(c);

      // running: threshold = started_at + (900 + 60) = 960s.
      // At exactly 960s the strict `>` has NOT tripped -> running.
      // At 961s -> timed_out. At 959s -> running.
      const runningCases: Array<{ off: number; expect: RunStatus }> = [
        { off: 959, expect: "running" },
        { off: 960, expect: "running" }, // exact equality passes through
        { off: 961, expect: "timed_out" },
      ];
      for (const rc of runningCases) {
        const runId = await insertRun(c, created.agentId, {
          status: "running",
          startedOffsetSecs: rc.off,
          queuedOffsetSecs: rc.off + 30,
          label: `running-boundary-${rc.off}`,
        });
        created.runIds.push(runId);
        const { sqlEffective, tsInput, nowMs } = await readParityRow(c, runId);
        const tsEffective = effectiveStatus(tsInput, nowMs);
        // Both sides must agree with each other first and foremost (SR3).
        expect(tsEffective, `running-boundary-${rc.off}: sql=${sqlEffective}`).toBe(sqlEffective);
      }

      // queued: threshold = queued_at + 300s.
      const queuedCases = [299, 300, 301];
      for (const off of queuedCases) {
        const runId = await insertRun(c, created.agentId, {
          status: "queued",
          startedOffsetSecs: null,
          queuedOffsetSecs: off,
          label: `queued-boundary-${off}`,
        });
        created.runIds.push(runId);
        const { sqlEffective, tsInput, nowMs } = await readParityRow(c, runId);
        expect(effectiveStatus(tsInput, nowMs), `queued-boundary-${off}: sql=${sqlEffective}`).toBe(
          sqlEffective,
        );
      }
    });
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — status parity (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
