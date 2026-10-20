import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { randomBytes } from "node:crypto";
import { localRestConfig, probeLocalDb, withDb } from "./db";
import {
  createWebhookEndpoint,
  deleteWebhookEndpoint,
  getEndpointSecret,
  getWebhookEndpointsForList,
  rotateWebhookEndpointSecret,
  updateWebhookEndpoint,
} from "@/lib/supabase/queries";

// Layer 2.5 — S-176 (#321): endpoint admin through the real queries + RPCs.
//  - create inserts the endpoint AND its Vault secret in one transaction
//    (public.webhook_create_endpoint); a failed insert leaves no secret behind;
//  - rotate replaces the secret; the old one stops verifying;
//  - update never touches token or secret;
//  - delete removes the Vault secret, then the row (rules + deliveries cascade);
//  - the list query never returns a secret, and no RPC result does either;
//  - every admin RPC is service_role-only.

const probe = await probeLocalDb();
const ANON_KEY = process.env.SUPABASE_ANON_KEY ?? process.env.ANON_KEY ?? "";
let client: SupabaseClient;
const created: string[] = [];

const token = () => randomBytes(32).toString("base64url");
const secret = () => randomBytes(32).toString("hex");

async function vaultCount(id: string): Promise<number> {
  return withDb((c) =>
    c
      .query<{
        n: number;
      }>(`select count(*)::int n from vault.secrets where name = $1`, [`webhook_endpoint_${id}`])
      .then((r) => r.rows[0]!.n),
  );
}

describe.skipIf(!probe.available)("panel Layer 2.5 — S-176 webhook endpoint admin", () => {
  beforeAll(() => {
    console.log(`[integration] ${probe.reason}`);
    const { url, serviceKey } = localRestConfig();
    client = createClient(url, serviceKey, { auth: { persistSession: false } });
  });

  afterEach(async () => {
    await withDb(async (c) => {
      for (const id of created.splice(0)) {
        await c.query(`delete from vault.secrets where name = $1`, [`webhook_endpoint_${id}`]);
        await c.query(`delete from webhook_endpoints where id = $1`, [id]);
      }
    });
  });

  const base = {
    name: "s176 github",
    source: "github" as const,
    eventAllowlist: ["issue_comment", "pull_request"],
    ignoreBotAuthor: true,
    signatureHeader: "x-hub-signature-256",
    deliveryIdHeader: "x-github-delivery",
  };

  it("creates the endpoint and its Vault secret together, and the secret round-trips", async () => {
    const s = secret();
    const id = await createWebhookEndpoint(client, { ...base, urlToken: token(), secret: s });
    created.push(id);
    expect(await getEndpointSecret(client, id)).toBe(s);
    const row = await withDb((c) =>
      c
        .query(
          `select name, source::text, event_allowlist, ignore_bot_author, is_enabled from webhook_endpoints where id=$1`,
          [id],
        )
        .then((r) => r.rows[0]),
    );
    expect(row).toEqual({
      name: "s176 github",
      source: "github",
      event_allowlist: ["issue_comment", "pull_request"],
      ignore_bot_author: true,
      is_enabled: true,
    });
  });

  it("leaves no Vault secret when the insert fails (atomic)", async () => {
    const t = token();
    const id = await createWebhookEndpoint(client, { ...base, urlToken: t, secret: secret() });
    created.push(id);
    const before = await withDb((c) =>
      c
        .query<{
          n: number;
        }>(`select count(*)::int n from vault.secrets where name like 'webhook_endpoint_%'`)
        .then((r) => r.rows[0]!.n),
    );
    // Same token → unique violation inside the RPC.
    await expect(
      createWebhookEndpoint(client, { ...base, urlToken: t, secret: secret() }),
    ).rejects.toThrow();
    const after = await withDb((c) =>
      c
        .query<{
          n: number;
        }>(`select count(*)::int n from vault.secrets where name like 'webhook_endpoint_%'`)
        .then((r) => r.rows[0]!.n),
    );
    expect(after).toBe(before);
  });

  it("rotates the secret", async () => {
    const id = await createWebhookEndpoint(client, {
      ...base,
      urlToken: token(),
      secret: secret(),
    });
    created.push(id);
    const s2 = secret();
    await rotateWebhookEndpointSecret(client, id, s2);
    expect(await getEndpointSecret(client, id)).toBe(s2);
    expect(await vaultCount(id)).toBe(1);
  });

  it("updates settings without touching the token or the secret", async () => {
    const t = token();
    const s = secret();
    const id = await createWebhookEndpoint(client, { ...base, urlToken: t, secret: s });
    created.push(id);
    await updateWebhookEndpoint(client, id, {
      name: "renamed",
      eventAllowlist: ["push"],
      ignoreBotAuthor: false,
      isEnabled: false,
      signatureHeader: "x-hub-signature-256",
      deliveryIdHeader: "x-github-delivery",
    });
    const row = await withDb((c) =>
      c
        .query(
          `select name, url_token, event_allowlist, ignore_bot_author, is_enabled from webhook_endpoints where id=$1`,
          [id],
        )
        .then((r) => r.rows[0]),
    );
    expect(row).toEqual({
      name: "renamed",
      url_token: t,
      event_allowlist: ["push"],
      ignore_bot_author: false,
      is_enabled: false,
    });
    expect(await getEndpointSecret(client, id)).toBe(s);
  });

  it("deletes the Vault secret, the row, and its rules and deliveries", async () => {
    const id = await createWebhookEndpoint(client, {
      ...base,
      urlToken: token(),
      secret: secret(),
    });
    created.push(id); // cleanup is idempotent, so a failure before delete leaks nothing
    await withDb(async (c) => {
      const agent = await c
        .query<{ id: string }>(`select id from agents order by slug limit 1`)
        .then((r) => r.rows[0]!.id);
      await c.query(
        `insert into webhook_rules (endpoint_id, position, agent_id, repo_mode, repo_payload_field) values ($1, 0, $2, 'payload_field', 'repository.full_name')`,
        [id, agent],
      );
      await c.query(
        `insert into webhook_deliveries (endpoint_id, outcome) values ($1, 'unauthorized')`,
        [id],
      );
    });
    await deleteWebhookEndpoint(client, id);
    expect(await vaultCount(id)).toBe(0);
    const left = await withDb((c) =>
      c
        .query<{ e: number; r: number; d: number }>(
          `select (select count(*)::int from webhook_endpoints where id=$1) e,
                  (select count(*)::int from webhook_rules where endpoint_id=$1) r,
                  (select count(*)::int from webhook_deliveries where endpoint_id=$1) d`,
          [id],
        )
        .then((x) => x.rows[0]!),
    );
    expect(left).toEqual({ e: 0, r: 0, d: 0 });
  });

  it("lists endpoints with their rule count and never a secret", async () => {
    const s = secret();
    const id = await createWebhookEndpoint(client, { ...base, urlToken: token(), secret: s });
    created.push(id);
    await withDb(async (c) => {
      const agent = await c
        .query<{ id: string }>(`select id from agents order by slug limit 1`)
        .then((r) => r.rows[0]!.id);
      for (const p of [0, 1]) {
        await c.query(
          `insert into webhook_rules (endpoint_id, position, agent_id, repo_mode, repo_payload_field) values ($1, $2, $3, 'payload_field', 'repository.full_name')`,
          [id, p, agent],
        );
      }
    });
    const rows = await getWebhookEndpointsForList(client);
    const mine = rows.find((r) => r.id === id);
    expect(mine).toMatchObject({ id, name: "s176 github", rule_count: 2 });
    expect(JSON.stringify(rows)).not.toContain(s);
  });

  it("makes every admin RPC service_role-only (SQL and PostgREST with the anon key)", async () => {
    const fns = [
      "public.webhook_create_endpoint(text,webhook_source,text[],boolean,text,text,text,text)",
      "public.webhook_rotate_endpoint_secret(uuid,text)",
      "public.webhook_delete_endpoint(uuid)",
    ];
    const rows = await withDb((c) =>
      c
        .query<{ fn: string; anon: boolean; authed: boolean; svc: boolean }>(
          `select f as fn,
                  has_function_privilege('anon', f, 'execute') anon,
                  has_function_privilege('authenticated', f, 'execute') authed,
                  has_function_privilege('service_role', f, 'execute') svc
             from unnest($1::text[]) f`,
          [fns],
        )
        .then((r) => r.rows),
    );
    for (const r of rows) expect(r, r.fn).toMatchObject({ anon: false, authed: false, svc: true });

    const { url } = localRestConfig();
    const anon = createClient(url, ANON_KEY, { auth: { persistSession: false } });
    const res = await anon.rpc("webhook_rotate_endpoint_secret", {
      p_endpoint_id: "00000000-0000-0000-0000-000000000000",
      p_secret: "x",
    });
    expect(res.error).not.toBeNull();
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-176 webhook endpoint admin (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
