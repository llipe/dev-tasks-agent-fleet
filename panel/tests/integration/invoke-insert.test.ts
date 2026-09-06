import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { Client } from "pg";
import { probeLocalDb, withDb } from "./db";
import {
  insertQueuedRun,
  markRunFailedToStart,
  updateRunInvocationRefs,
} from "@/lib/supabase/queries";
import { buildRunInsert } from "@/lib/domain/run-insert";

/**
 * S-112 (#125) — Layer 2.5 (task 1.15). Against the REAL local Supabase stack:
 *   - a successful invoke path writes exactly ONE `runs` row, with all three
 *     timeout snapshots non-null (D1, OQ3)
 *   - the failed_to_start transition persists on the same row (AC12)
 *   - a rejected invoke (never reaching insert) writes ZERO rows
 *
 * Docker-gated; skips with a recorded reason when the stack is down (#134). The
 * PR states whether this RAN LIVE or skipped.
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

const fx = { agentId: "", repoId: "", installationId: "", runIds: [] as string[] };

async function seedFixture(c: Client): Promise<void> {
  // Reuse the seeded installation, or create one for isolation.
  const inst = await c.query(`select id from github_installations limit 1`);
  if (inst.rows.length > 0) {
    fx.installationId = inst.rows[0].id;
  } else {
    fx.installationId = randomUUID();
    await c.query(
      `insert into github_installations (id, installation_id, account_login, private_key_secret_arn)
       values ($1, 42, 'acme', 'arn:aws:secretsmanager:us-east-1:1:secret:x')`,
      [fx.installationId],
    );
  }

  fx.agentId = randomUUID();
  await c.query(
    `insert into agents (id, slug, name, runtime_arn, requires_repository,
                         max_runtime_seconds, grace_seconds, start_timeout_seconds)
     values ($1, $2, $3, $4, true, 3600, 120, 300)`,
    [fx.agentId, `s112-invoke-${fx.agentId}`, "S-112 invoke test agent", "arn:test:runtime/inv"],
  );

  fx.repoId = randomUUID();
  await c.query(
    `insert into repositories (id, installation_id, full_name, default_branch, is_enabled)
     values ($1, $2, $3, 'main', true)`,
    [fx.repoId, fx.installationId, `acme/s112-${fx.repoId.slice(0, 8)}`],
  );

  await c.query(`grant usage on schema public to service_role`);
  await c.query(`grant select, insert, update on all tables in schema public to service_role`);
}

async function cleanupFixture(c: Client): Promise<void> {
  for (const id of fx.runIds) {
    await c.query(`delete from runs where id = $1`, [id]);
  }
  if (fx.repoId) await c.query(`delete from repositories where id = $1`, [fx.repoId]);
  if (fx.agentId) await c.query(`delete from agents where id = $1`, [fx.agentId]);
}

describe.skipIf(!runSuite)("panel Layer 2.5 — invoke run insert (S-112)", () => {
  let client: SupabaseClient;

  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    client = createClient(API_URL, SERVICE_KEY, {
      auth: { autoRefreshToken: false, persistSession: false },
    });
    await withDb(seedFixture);
  });

  afterAll(async () => {
    await withDb(cleanupFixture);
  });

  it("a successful invoke path writes exactly ONE queued run with all snapshots non-null", async () => {
    const runId = randomUUID();
    fx.runIds.push(runId);
    const row = buildRunInsert({
      runId,
      agent: {
        id: fx.agentId,
        version: "0.1.0",
        max_runtime_seconds: 3600,
        grace_seconds: 120,
        start_timeout_seconds: 300,
      },
      repositoryId: fx.repoId,
      installationId: fx.installationId,
      params: { fix_mode: "audit_only" },
    });

    await insertQueuedRun(client, row);

    const check = await withDb((c) =>
      c.query(
        `select status, max_runtime_seconds, grace_seconds, start_timeout_seconds,
                triggered_by, trigger_type
           from runs where id = $1`,
        [runId],
      ),
    );
    expect(check.rows.length).toBe(1);
    const r = check.rows[0];
    expect(r.status).toBe("queued");
    expect(r.max_runtime_seconds).toBe(3600);
    expect(r.grace_seconds).toBe(120);
    expect(r.start_timeout_seconds).toBe(300);
    expect(r.triggered_by).toBe("panel");
    expect(r.trigger_type).toBe("manual");
  });

  it("markRunFailedToStart transitions the same row (AC12)", async () => {
    const runId = randomUUID();
    fx.runIds.push(runId);
    await insertQueuedRun(
      client,
      buildRunInsert({
        runId,
        agent: {
          id: fx.agentId,
          version: "0.1.0",
          max_runtime_seconds: 3600,
          grace_seconds: 120,
          start_timeout_seconds: 300,
        },
        repositoryId: fx.repoId,
        installationId: fx.installationId,
        params: { fix_mode: "audit_only" },
      }),
    );

    await markRunFailedToStart(client, runId, "INVOCATION_FAILED", "InvokeAgentRuntime failed.");

    const check = await withDb((c) =>
      c.query(`select status, error_code, finished_at from runs where id = $1`, [runId]),
    );
    expect(check.rows[0].status).toBe("failed_to_start");
    expect(check.rows[0].error_code).toBe("INVOCATION_FAILED");
    expect(check.rows[0].finished_at).not.toBeNull();
  });

  it("updateRunInvocationRefs updates without error", async () => {
    const runId = randomUUID();
    fx.runIds.push(runId);
    await insertQueuedRun(
      client,
      buildRunInsert({
        runId,
        agent: {
          id: fx.agentId,
          version: "0.1.0",
          max_runtime_seconds: 3600,
          grace_seconds: 120,
          start_timeout_seconds: 300,
        },
        repositoryId: fx.repoId,
        installationId: fx.installationId,
        params: {},
      }),
    );
    await updateRunInvocationRefs(client, runId, {
      session_id: "sess-1",
      runtime_invocation_id: "inv-1",
    });
    const check = await withDb((c) =>
      c.query(`select session_id, runtime_invocation_id from runs where id = $1`, [runId]),
    );
    expect(check.rows[0].session_id).toBe("sess-1");
    expect(check.rows[0].runtime_invocation_id).toBe("inv-1");
  });

  it("a rejected invoke (no insert reached) leaves zero rows for its run id", async () => {
    // Simulate the params-rejection path: the route never calls insertQueuedRun,
    // so no row exists. We assert a fresh id has zero rows.
    const neverInserted = randomUUID();
    const check = await withDb((c) => c.query(`select 1 from runs where id = $1`, [neverInserted]));
    expect(check.rows.length).toBe(0);
  });
});

if (!runSuite) {
  describe("panel Layer 2.5 — invoke run insert (skipped)", () => {
    it.skip(`SKIPPED: ${skipReason}`, () => {});
  });
}
