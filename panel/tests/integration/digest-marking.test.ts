import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { randomUUID } from "node:crypto";
import { probeLocalDb, localRestConfig, withDb } from "./db";
import { getUndeliveredNotifications, markNotificationsEmailed } from "@/lib/supabase/queries";

// Layer 2.5 — S-159 (#271): digest selection + exactly-once emailed_at marking
// (SD-N6/N8). The selection returns only emailed_at-null rows; marking sets
// emailed_at so a subsequent select excludes them; a simulated send FAILURE
// (we simply do not call markNotificationsEmailed) leaves emailed_at null so the
// window retries next day (R-S9). Docker-gated.

const probe = await probeLocalDb();

function serviceClient(): SupabaseClient {
  const { url, serviceKey } = localRestConfig();
  return createClient(url, serviceKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

describe.skipIf(!probe.available)("panel Layer 2.5 — S-159 digest marking", () => {
  let client: SupabaseClient;
  let agentId: string;
  const made: string[] = [];

  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    client = serviceClient();
    agentId = await withDb((c) =>
      c
        .query<{ id: string }>(`select id from agents where slug='dependency-update' limit 1`)
        .then((r) => r.rows[0]!.id),
    );
  });

  afterEach(async () => {
    await withDb(async (c) => {
      for (const id of made.splice(0)) await c.query(`delete from notifications where id=$1`, [id]);
    });
  });

  async function makeNotif(kind: string): Promise<string> {
    const id = randomUUID();
    made.push(id);
    await withDb((c) =>
      c.query(
        `insert into notifications (id, kind, agent_id, title, detail)
         values ($1,$2::notification_kind,$3,$4,$5)`,
        [id, kind, agentId, `test ${kind}`, "detail"],
      ),
    );
    return id;
  }
  const emailedAt = (id: string) =>
    withDb((c) =>
      c
        .query(`select emailed_at from notifications where id=$1`, [id])
        .then((r) => r.rows[0]!.emailed_at),
    );

  it("selects only undelivered rows; marking removes them from the next selection", async () => {
    const a = await makeNotif("run_failed");
    const b = await makeNotif("pr_opened");

    const before = await getUndeliveredNotifications(client);
    const ids = before.map((n) => n.id);
    expect(ids).toContain(a);
    expect(ids).toContain(b);

    await markNotificationsEmailed(client, [a, b]);
    expect(await emailedAt(a)).not.toBeNull();

    const after = await getUndeliveredNotifications(client);
    const afterIds = after.map((n) => n.id);
    expect(afterIds).not.toContain(a);
    expect(afterIds).not.toContain(b);
  });

  it("a send failure (no mark call) leaves emailed_at null -> retried next window", async () => {
    const a = await makeNotif("run_failed");
    // Simulate the route's failure branch: it returns 502 WITHOUT calling
    // markNotificationsEmailed, so the row stays selectable.
    expect(await emailedAt(a)).toBeNull();
    const sel = await getUndeliveredNotifications(client);
    expect(sel.map((n) => n.id)).toContain(a);
  });

  it("selection is oldest-first so the digest reads chronologically", async () => {
    const first = await makeNotif("run_failed");
    await new Promise((r) => setTimeout(r, 10));
    const second = await makeNotif("run_succeeded");
    const sel = await getUndeliveredNotifications(client);
    const idxFirst = sel.findIndex((n) => n.id === first);
    const idxSecond = sel.findIndex((n) => n.id === second);
    expect(idxFirst).toBeGreaterThanOrEqual(0);
    expect(idxFirst).toBeLessThan(idxSecond);
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-159 digest marking (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
