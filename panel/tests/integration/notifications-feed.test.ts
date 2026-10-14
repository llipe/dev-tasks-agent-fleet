import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { randomUUID } from "node:crypto";
import { probeLocalDb, localRestConfig, withDb } from "./db";
import {
  getNotificationTotal,
  getNotifications,
  getUnreadCount,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/lib/supabase/queries";

// Layer 2.5 — S-163 (#275): notifications feed reads + mark-read against the
// real DB. The anon RLS deny-all is covered by rls-deny-all.test.ts; here we
// exercise the service-role read/mutate helpers. Docker-gated (#134).

const probe = await probeLocalDb();

function serviceClient(): SupabaseClient {
  const { url, serviceKey } = localRestConfig();
  return createClient(url, serviceKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

describe.skipIf(!probe.available)("panel Layer 2.5 — S-163 notifications feed", () => {
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

  async function makeNotif(kind: string, read = false): Promise<string> {
    const id = randomUUID();
    made.push(id);
    await withDb((c) =>
      c.query(
        `insert into notifications (id, kind, agent_id, title, detail, read_at)
         values ($1,$2::notification_kind,$3,$4,'detail',$5)`,
        [id, kind, agentId, `t ${kind}`, read ? new Date().toISOString() : null],
      ),
    );
    return id;
  }

  it("getNotifications returns newest-first; limit bounds the popover", async () => {
    const a = await makeNotif("run_failed");
    await new Promise((r) => setTimeout(r, 10));
    const b = await makeNotif("pr_opened");

    const all = await getNotifications(client);
    const idx = (id: string) => all.findIndex((n) => n.id === id);
    expect(idx(b)).toBeLessThan(idx(a)); // newest first

    const limited = await getNotifications(client, 1);
    expect(limited.length).toBe(1);
  });

  it("getUnreadCount and getNotificationTotal reflect read state", async () => {
    const u0 = await getUnreadCount(client);
    const t0 = await getNotificationTotal(client);
    await makeNotif("run_failed", false);
    await makeNotif("run_succeeded", true);
    expect(await getUnreadCount(client)).toBe(u0 + 1); // only the unread one
    expect(await getNotificationTotal(client)).toBe(t0 + 2);
  });

  it("markNotificationRead sets read_at and drops it from the unread count", async () => {
    const id = await makeNotif("run_failed", false);
    const before = await getUnreadCount(client);
    await markNotificationRead(client, id);
    expect(await getUnreadCount(client)).toBe(before - 1);
    const row = (await getNotifications(client)).find((n) => n.id === id)!;
    expect(row.read_at).not.toBeNull();
  });

  it("markAllNotificationsRead clears every unread", async () => {
    await makeNotif("run_failed", false);
    await makeNotif("pr_opened", false);
    await markAllNotificationsRead(client);
    expect(await getUnreadCount(client)).toBe(0);
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-163 notifications feed (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
