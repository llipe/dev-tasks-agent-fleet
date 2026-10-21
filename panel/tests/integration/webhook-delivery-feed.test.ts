import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { randomBytes } from "node:crypto";
import { localRestConfig, probeLocalDb, withDb } from "./db";
import { getWebhookDeliveriesPage, getWebhookDeliveryRetentionDays } from "@/lib/supabase/queries";

// Layer 2.5 — S-178 (#323): the delivery-log feed query.
//  - newest first, one endpoint only;
//  - keyset pagination on (created_at, id): pages never overlap or skip, even
//    when many rows share a created_at (a burst in one transaction);
//  - the returned rows carry no payload and no secret (there is none to carry).

const probe = await probeLocalDb();
let client: SupabaseClient;
let ep = "";
let other = "";

async function endpoint(name: string): Promise<string> {
  return withDb((c) =>
    c
      .query<{
        id: string;
      }>(`insert into webhook_endpoints (name, url_token) values ($1, $2) returning id`, [
        name,
        randomBytes(32).toString("base64url"),
      ])
      .then((r) => r.rows[0]!.id),
  );
}

describe.skipIf(!probe.available)("panel Layer 2.5 — S-178 delivery feed", () => {
  beforeAll(() => {
    console.log(`[integration] ${probe.reason}`);
    const { url, serviceKey } = localRestConfig();
    client = createClient(url, serviceKey, { auth: { persistSession: false } });
  });

  beforeEach(async () => {
    ep = await endpoint("s178");
    other = await endpoint("s178-other");
    await withDb(async (c) => {
      // 7 rows: 3 share one timestamp (tie-break on id), the rest are 1 minute apart.
      await c.query(
        `insert into webhook_deliveries (endpoint_id, outcome, event_type, created_at, received_at)
         select $1, 'no_match', 'e' || g, ts, ts
           from generate_series(1, 7) g,
                lateral (select case when g <= 3 then timestamptz '2026-10-20 12:00:00+00'
                                     else timestamptz '2026-10-20 12:00:00+00' + (g || ' minutes')::interval end ts) t`,
        [ep],
      );
      await c.query(
        `insert into webhook_deliveries (endpoint_id, outcome) values ($1, 'unauthorized')`,
        [other],
      );
    });
  });

  afterEach(async () => {
    await withDb((c) =>
      c.query(`delete from webhook_endpoints where id = any($1::uuid[])`, [[ep, other]]),
    );
  });

  it("returns one endpoint's deliveries newest first", async () => {
    const { rows, nextCursor } = await getWebhookDeliveriesPage(client, ep, { limit: 50 });
    expect(rows).toHaveLength(7);
    expect(rows.every((r) => r.endpoint_id === ep)).toBe(true);
    const keys = rows.map((r) => [r.created_at, r.id] as const);
    const sorted = [...keys].sort((a, b) =>
      a[0] === b[0] ? (a[1] < b[1] ? 1 : -1) : a[0] < b[0] ? 1 : -1,
    );
    expect(keys).toEqual(sorted);
    expect(rows.slice(0, 4).map((r) => r.event_type)).toEqual(["e7", "e6", "e5", "e4"]);
    expect(nextCursor).toBeNull();
  });

  it("pages through ties without overlap or gaps", async () => {
    const seen: string[] = [];
    let cursor: { createdAt: string; id: string } | null = null;
    for (let i = 0; i < 10; i++) {
      const page: Awaited<ReturnType<typeof getWebhookDeliveriesPage>> =
        await getWebhookDeliveriesPage(client, ep, {
          limit: 2,
          before: cursor ?? undefined,
        });
      seen.push(...page.rows.map((r) => r.id));
      if (!page.nextCursor) break;
      cursor = page.nextCursor;
    }
    expect(seen).toHaveLength(7);
    expect(new Set(seen).size).toBe(7);
    const all = await getWebhookDeliveriesPage(client, ep, { limit: 50 });
    expect(seen).toEqual(all.rows.map((r) => r.id));
  });

  it("reads the configured retention for the log's note, through a service_role-only RPC", async () => {
    expect(await getWebhookDeliveryRetentionDays(client)).toBe(
      await withDb((c) =>
        c
          .query<{ n: number }>(`select webhook.delivery_retention_days() n`)
          .then((r) => r.rows[0]!.n),
      ),
    );
    const grants = await withDb((c) =>
      c
        .query(
          `select has_function_privilege('anon', 'public.webhook_delivery_retention_days()', 'execute') anon,
                  has_function_privilege('authenticated', 'public.webhook_delivery_retention_days()', 'execute') authed,
                  has_function_privilege('service_role', 'public.webhook_delivery_retention_days()', 'execute') svc`,
        )
        .then((r) => r.rows[0]),
    );
    expect(grants).toEqual({ anon: false, authed: false, svc: true });
  });

  it("returns only the log columns", async () => {
    const { rows } = await getWebhookDeliveriesPage(client, ep, { limit: 1 });
    expect(Object.keys(rows[0]!).sort()).toEqual(
      [
        "created_at",
        "dedup_key",
        "delivery_id",
        "endpoint_id",
        "event_type",
        "id",
        "matched_rule_id",
        "outcome",
        "reason",
        "received_at",
        "run_id",
        "updated_at",
      ].sort(),
    );
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-178 delivery feed (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
