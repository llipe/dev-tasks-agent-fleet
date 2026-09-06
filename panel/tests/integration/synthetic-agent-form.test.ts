import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import type { Client } from "pg";
import { probeLocalDb, withDb } from "./db";
import { getAgentBySlug } from "@/lib/supabase/queries";
import { buildFieldDescriptors } from "@/lib/schema/form";

/**
 * S-113 (#126) — Layer 2.5 (task 2.16, AC7). Inserts a SYNTHETIC agent row with
 * a different params_schema into the REAL local stack, reads it back through the
 * same query helper the form route uses, and asserts the descriptor mapping
 * renders its fields — proving a new agent is a row, not a deploy, end to end
 * through the database.
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

const fx = { agentId: "", slug: "" };

const SYNTHETIC_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["target_url"],
  properties: {
    target_url: { type: "string", title: "Target URL" },
    depth: { type: "integer", title: "Crawl depth", minimum: 1, maximum: 10, default: 3 },
    follow_redirects: { type: "boolean", title: "Follow redirects", default: true },
    mode: { type: "string", title: "Scan mode", enum: ["fast", "deep"], default: "fast" },
  },
};

async function seedFixture(c: Client): Promise<void> {
  fx.agentId = randomUUID();
  fx.slug = `s113-synthetic-${fx.agentId.slice(0, 8)}`;
  await c.query(
    `insert into agents (id, slug, name, runtime_arn, requires_repository,
                         max_runtime_seconds, grace_seconds, start_timeout_seconds,
                         params_schema, is_enabled)
     values ($1, $2, $3, $4, false, 900, 60, 300, $5::jsonb, true)`,
    [
      fx.agentId,
      fx.slug,
      "S-113 synthetic agent",
      "arn:test:runtime/syn",
      JSON.stringify(SYNTHETIC_SCHEMA),
    ],
  );
  await c.query(`grant usage on schema public to service_role`);
  await c.query(`grant select on all tables in schema public to service_role`);
}

async function cleanupFixture(c: Client): Promise<void> {
  if (fx.agentId) await c.query(`delete from agents where id = $1`, [fx.agentId]);
}

describe.skipIf(!runSuite)("panel Layer 2.5 — synthetic agent form (S-113, AC7)", () => {
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

  it("reads the synthetic agent and maps its schema to the four expected controls", async () => {
    const agent = await getAgentBySlug(client, fx.slug);
    expect(agent).not.toBeNull();
    const fields = buildFieldDescriptors(agent!.params_schema);

    // NOTE: Postgres `jsonb` does NOT preserve object key order (it stores keys
    // in its own internal order), so the field ORDER after a DB round-trip is
    // not the schema authoring order. The contract that matters is that every
    // property maps to the right control — assert the set, not the sequence.
    const mapping = Object.fromEntries(fields.map((f) => [f.name, f.control]));
    expect(mapping).toEqual({
      target_url: "text",
      depth: "number",
      follow_redirects: "toggle",
      mode: "select",
    });
    // bounds survived the round-trip through the DB
    const depth = fields.find((f) => f.name === "depth")!;
    expect(depth.min).toBe(1);
    expect(depth.max).toBe(10);
    const mode = fields.find((f) => f.name === "mode")!;
    expect(mode.options).toEqual(["fast", "deep"]);
    // required marking from the schema's required array
    expect(fields.find((f) => f.name === "target_url")!.required).toBe(true);
  });
});

if (!runSuite) {
  describe("panel Layer 2.5 — synthetic agent form (skipped)", () => {
    it.skip(`SKIPPED: ${skipReason}`, () => {});
  });
}
