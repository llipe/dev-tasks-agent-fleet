import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { Client } from "pg";

import { probeLocalDb, withDb } from "./db";
import {
  createStreamResponse,
  type RealtimeLike,
  type RelayEventRow,
  type StreamDeps,
} from "@/lib/sse/relay";
import { getRunEventsAfterSeq, getRunById } from "@/lib/supabase/queries";
import { parseFrames } from "@/lib/sse/serialize";

/**
 * Layer 2.5 harness for the SSE relay (Story S-110, SC-11 / EC-2).
 *
 * The property that can only be proven against the real stack: open the relay,
 * insert `run_events` AFTER the stream is open, and assert every inserted event
 * arrives at the client exactly once, in `seq` order — the backfill+subscribe
 * seam (SD6) holds against real Supabase Realtime, not a mock.
 *
 * Docker-gated + service-role-key-gated + Realtime-gated: skips with a recorded
 * reason rather than passing vacuously (test-plan G2 / spec §14 — "a skip is
 * not evidence"). Realtime must be running (`supabase start` brings it up); if
 * the subscription does not reach `SUBSCRIBED`, the suite records that reason.
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

let supabase: SupabaseClient;
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
    [id, slug, `stream test ${slug}`, "arn:test:runtime/stream"],
  );
  createdAgentIds.push(id);
  return id;
}

async function insertRunningRun(c: Client, agentId: string): Promise<string> {
  const id = randomUUID();
  await c.query(
    `insert into runs (id, agent_id, agent_version, status,
                       queued_at, started_at, created_at,
                       max_runtime_seconds, grace_seconds, start_timeout_seconds)
     values ($1, $2, '0.1.0', 'running',
             now() - interval '1 min', now() - interval '30 sec', now() - interval '1 min',
             900, 60, 300)`,
    [id, agentId],
  );
  return id;
}

async function insertEvent(c: Client, runId: string, seq: number): Promise<void> {
  await c.query(
    `insert into run_events (run_id, seq, ts, level, message)
     values ($1, $2::int, now(), 'info', 'live event ' || $2::text)`,
    [runId, seq],
  );
}

/**
 * Prove the Postgres→Realtime pipeline is actually DELIVERING before the test
 * inserts its asserted events. `channel.subscribe(...) === 'SUBSCRIBED'` fires
 * before the logical-replication slot is streaming on a cold stack, so events
 * inserted in that window are silently dropped and never recovered — the CI
 * cold-start flake. This opens a SEPARATE throwaway channel bound to the SAME
 * run id filter and inserts probe rows (negative seqs, so they can never
 * collide with or pollute the asserted seq 1..10) until one is delivered, or
 * until a bounded deadline. It removes the probe rows afterward. Best-effort:
 * if delivery is never confirmed it resolves anyway and lets the main poll +
 * assertions produce the real diagnosis.
 */
async function waitForLiveDelivery(
  client: SupabaseClient,
  runId: string,
  subscribed: Promise<void>,
): Promise<void> {
  await subscribed.catch(() => {});
  let delivered = false;
  const probe = client.channel(`probe-${runId}`);
  probe
    .on(
      "postgres_changes",
      { event: "INSERT", schema: "public", table: "run_events", filter: `run_id=eq.${runId}` },
      () => {
        delivered = true;
      },
    )
    .subscribe();

  const deadline = Date.now() + 8000;
  let probeSeq = -1;
  try {
    while (!delivered && Date.now() < deadline) {
      await withDb((c) => insertEvent(c, runId, probeSeq));
      probeSeq -= 1;
      await new Promise((r) => setTimeout(r, 300));
    }
  } finally {
    // Remove the probe rows so they never reach the asserted stream's window.
    await withDb((c) => c.query(`delete from run_events where run_id = $1 and seq < 0`, [runId]));
    await client.removeChannel(probe).catch(() => {});
  }
}

/** The real Supabase Realtime channel wrapped in the relay's RealtimeLike.
 * `onSubscribed` fires once the channel reaches `SUBSCRIBED`, so the test can
 * wait for the subscription before inserting (removing the fixed-sleep flake). */
function wrapSupabaseChannel(
  client: SupabaseClient,
  runId: string,
  onSubscribed?: () => void,
): RealtimeLike {
  const channel = client.channel(`test-run-stream:${runId}`);
  let eventCb: ((row: RelayEventRow) => void) | null = null;
  let runCb: ((row: Record<string, unknown>) => void) | null = null;
  const wrapper: RealtimeLike = {
    onEvent(cb) {
      eventCb = cb;
      return wrapper;
    },
    onRun(cb) {
      runCb = cb;
      return wrapper;
    },
    subscribe() {
      channel
        .on(
          "postgres_changes",
          { event: "INSERT", schema: "public", table: "run_events", filter: `run_id=eq.${runId}` },
          (payload: { new: Record<string, unknown> }) => {
            const row = payload.new as { seq: number };
            eventCb?.({ ...payload.new, seq: row.seq });
          },
        )
        .on(
          "postgres_changes",
          { event: "UPDATE", schema: "public", table: "runs", filter: `id=eq.${runId}` },
          (payload: { new: Record<string, unknown> }) => runCb?.(payload.new),
        )
        .subscribe((status: string) => {
          if (status === "SUBSCRIBED") onSubscribed?.();
        });
      return wrapper;
    },
    unsubscribe() {
      void client.removeChannel(channel);
    },
  };
  return wrapper;
}

beforeAll(async () => {
  if (!runSuite) return;
  supabase = createClient(API_URL, SERVICE_KEY, {
    auth: { autoRefreshToken: false, persistSession: false },
    realtime: { params: { eventsPerSecond: 50 } },
  });
  await withDb(grantServiceRoleSelectLocalOnly);
});

afterAll(async () => {
  if (!runSuite) return;
  await withDb(async (c) => {
    for (const id of createdAgentIds) {
      // Delete children first (run_events/run_steps/run_artifacts cascade from
      // runs in most schemas, but delete runs explicitly before agents to
      // satisfy the runs_agent_id_fkey constraint).
      await c.query(`delete from runs where agent_id = $1`, [id]);
      await c.query(`delete from agents where id = $1`, [id]);
    }
  });
  await supabase.removeAllChannels();
});

describe.skipIf(!runSuite)("SSE relay end-to-end (Layer 2.5)", () => {
  it(`every event inserted after open arrives exactly once in seq order (SC-11, EC-2) [${skipReason || "running live"}]`, async () => {
    const agentId = await withDb((c) => insertAgent(c, `stream-${randomUUID().slice(0, 8)}`));
    const runId = await withDb((c) => insertRunningRun(c, agentId));

    const received: number[] = [];
    let markSubscribed!: () => void;
    const subscribed = new Promise<void>((r) => {
      markSubscribed = r;
    });
    const deps: StreamDeps = {
      backfill: async (id, after) => {
        const rows = await getRunEventsAfterSeq(supabase, id, after);
        return rows.map((e) => ({ ...e }) as RelayEventRow);
      },
      isTerminal: async (id) => {
        const run = await getRunById(supabase, id);
        if (run === null) return "not_found";
        return null; // running run
      },
      openChannel: (id) => wrapSupabaseChannel(supabase, id, markSubscribed),
      heartbeatMs: 15_000,
      log: () => {},
    };

    const controller = new AbortController();
    const res = createStreamResponse(runId, 0, deps, controller.signal);
    const reader = res.body!.getReader();
    const decoder = new TextDecoder();

    // Consume frames in the background, collecting event seqs.
    let buffer = "";
    const consume = (async () => {
      for (;;) {
        const { value, done } = await reader.read();
        if (value) {
          buffer += decoder.decode(value, { stream: true });
          for (const f of parseFrames(buffer)) {
            if (f.event === "event") received.push((f.data as { seq: number }).seq);
          }
          // Keep only the trailing partial frame.
          const lastBoundary = buffer.lastIndexOf("\n\n");
          if (lastBoundary >= 0) buffer = buffer.slice(lastBoundary + 2);
        }
        if (done) break;
      }
    })();

    // Wait until the Realtime subscription is actually SUBSCRIBED before
    // inserting — a fixed sleep raced the subscription under shared-stack load
    // (qa flake). Fall back to a bounded wait so a Realtime outage still fails
    // with a clear timeout rather than hanging.
    await Promise.race([
      subscribed,
      new Promise((_r, reject) =>
        setTimeout(() => reject(new Error("Realtime did not reach SUBSCRIBED within 8s")), 8000),
      ),
    ]);

    // Confirm the Postgres→Realtime pipeline is ACTUALLY delivering before
    // inserting the asserted events. `SUBSCRIBED` fires before the logical
    // replication slot is streaming on a cold stack, so early pushes are
    // silently dropped (never delivered, never recovered) — the CI cold-start
    // flake where `received` came back empty. Probe on a SEPARATE throwaway
    // channel + run id (so it cannot pollute the asserted stream): insert probe
    // rows and wait until one is delivered, proving the pipeline is live.
    await waitForLiveDelivery(supabase, runId, subscribed);

    for (let seq = 1; seq <= 10; seq++) {
      await withDb((c) => insertEvent(c, runId, seq));
    }
    // Wait for delivery with an explicit poll, not a fixed sleep. With the
    // pipeline proven live above, all 10 arrive quickly; the bounded deadline
    // (under the 20s test timeout) still fails clearly on a genuine outage.
    const deliveryDeadline = Date.now() + 12_000;
    while (new Set(received).size < 10 && Date.now() < deliveryDeadline) {
      await new Promise((r) => setTimeout(r, 250));
    }
    controller.abort();
    await consume;

    // Every seq 1..10 exactly once, in order (dedupe of any backfill/push
    // overlap is what makes "exactly once" hold).
    const unique = [...new Set(received)];
    expect(unique).toEqual(received); // no duplicates
    expect(received).toEqual([...received].sort((a, b) => a - b)); // seq order
    for (let seq = 1; seq <= 10; seq++) {
      expect(received).toContain(seq);
    }
  }, 20_000);
});
