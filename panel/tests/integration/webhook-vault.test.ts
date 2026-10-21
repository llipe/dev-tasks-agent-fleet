import { beforeAll, describe, expect, it } from "vitest";
import { createClient } from "@supabase/supabase-js";
import { localRestConfig, probeLocalDb, withDb } from "./db";

// Layer 2.5 — S-166 (#310): per-endpoint Vault signing secret + webhook.config.
//
//  - webhook.set_endpoint_secret / read_endpoint_secret round-trip through Vault
//    under `webhook_endpoint_<id>`; an absent secret reads null (the route fails
//    closed, test plan EC-21).
//  - webhook.config getters return the seeded defaults (delivery_retention_days=30,
//    bot_login).
//  - public.webhook_endpoint_secret(uuid) is the ONLY path the panel uses
//    (PostgREST can only reach `public`). It is SECURITY DEFINER and returns a
//    secret, so it must be executable by service_role only: anon and
//    authenticated are denied both at the SQL level and through PostgREST with
//    the anon key (#357 is the pre-existing bug this pattern must not repeat).
//  - No webhook table has a column holding the secret (AC9).
//
// Docker-gated via `probeLocalDb`. Writes are cleaned up per test.

const probe = await probeLocalDb();
const ANON_KEY = process.env.SUPABASE_ANON_KEY ?? process.env.ANON_KEY ?? "";

const FIXTURE_TOKEN = "s166-test-token-aaaaaaaaaaaaaaaaaaaaaa";

async function withEndpoint<T>(fn: (endpointId: string) => Promise<T>): Promise<T> {
  const id = await withDb((c) =>
    c
      .query<{
        id: string;
      }>(`insert into webhook_endpoints (name, url_token) values ('s166', $1) returning id`, [
        FIXTURE_TOKEN,
      ])
      .then((r) => r.rows[0]!.id),
  );
  try {
    return await fn(id);
  } finally {
    await withDb(async (c) => {
      await c.query(`delete from vault.secrets where name = $1`, [`webhook_endpoint_${id}`]);
      await c.query(`delete from webhook_endpoints where id = $1`, [id]);
    });
  }
}

const SECRET_FUNCTIONS = [
  "webhook.set_endpoint_secret(uuid,text)",
  "webhook.read_endpoint_secret(uuid)",
  "webhook.delete_endpoint_secret(uuid)",
  "public.webhook_endpoint_secret(uuid)",
] as const;

describe.skipIf(!probe.available)("panel Layer 2.5 — S-166 webhook Vault secret + config", () => {
  beforeAll(() => {
    console.log(`[integration] ${probe.reason}`);
  });

  it("round-trips an endpoint secret through Vault", async () => {
    await withEndpoint(async (id) => {
      const got = await withDb(async (c) => {
        await c.query(`select webhook.set_endpoint_secret($1, 'first-value')`, [id]);
        await c.query(`select webhook.set_endpoint_secret($1, 'rotated-value')`, [id]);
        return c
          .query<{ s: string | null }>(`select webhook.read_endpoint_secret($1) as s`, [id])
          .then((r) => r.rows[0]!.s);
      });
      expect(got).toBe("rotated-value");
    });
  });

  it("upserts a single Vault row per endpoint (rotation does not duplicate)", async () => {
    await withEndpoint(async (id) => {
      const n = await withDb(async (c) => {
        await c.query(`select webhook.set_endpoint_secret($1, 'a')`, [id]);
        await c.query(`select webhook.set_endpoint_secret($1, 'b')`, [id]);
        return c
          .query<{
            n: number;
          }>(`select count(*)::int as n from vault.secrets where name = $1`, [
            `webhook_endpoint_${id}`,
          ])
          .then((r) => r.rows[0]!.n);
      });
      expect(n).toBe(1);
    });
  });

  it("reads null for an endpoint with no secret (route fails closed, EC-21)", async () => {
    await withEndpoint(async (id) => {
      const got = await withDb((c) =>
        c
          .query<{ s: string | null }>(`select webhook.read_endpoint_secret($1) as s`, [id])
          .then((r) => r.rows[0]!.s),
      );
      expect(got).toBeNull();
    });
  });

  it("deletes the secret", async () => {
    await withEndpoint(async (id) => {
      const got = await withDb(async (c) => {
        await c.query(`select webhook.set_endpoint_secret($1, 'v')`, [id]);
        await c.query(`select webhook.delete_endpoint_secret($1)`, [id]);
        return c
          .query<{ s: string | null }>(`select webhook.read_endpoint_secret($1) as s`, [id])
          .then((r) => r.rows[0]!.s);
      });
      expect(got).toBeNull();
    });
  });

  it("rejects an empty secret value", async () => {
    await withEndpoint(async (id) => {
      await expect(
        withDb((c) => c.query(`select webhook.set_endpoint_secret($1, '')`, [id])),
      ).rejects.toThrow();
    });
  });

  it("returns the seeded webhook.config defaults", async () => {
    const row = await withDb((c) =>
      c
        .query<{
          days: number;
          bot: string | null;
        }>(`select webhook.delivery_retention_days() as days, webhook.bot_login() as bot`)
        .then((r) => r.rows[0]!),
    );
    expect(row.days).toBe(30);
    // `<app_slug>[bot]` shape (D-W12); the prod value is set per the runbook.
    expect(row.bot).toMatch(/^[a-z0-9-]+\[bot\]$/);
  });

  it("falls back to 30 days when delivery_retention_days is unset or invalid", async () => {
    const days = await withDb(async (c) => {
      await c.query("begin");
      try {
        await c.query(
          `update webhook.config set value = 'not-a-number' where key = 'delivery_retention_days'`,
        );
        return c
          .query<{ d: number }>(`select webhook.delivery_retention_days() as d`)
          .then((r) => r.rows[0]!.d);
      } finally {
        await c.query("rollback");
      }
    });
    expect(days).toBe(30);
  });

  describe("access control (only service_role may touch secrets)", () => {
    it.each(SECRET_FUNCTIONS)("anon and authenticated cannot execute %s", async (fn) => {
      const privs = await withDb((c) =>
        c
          .query<{ anon: boolean; authed: boolean; svc: boolean }>(
            `select has_function_privilege('anon', $1, 'execute') as anon,
                    has_function_privilege('authenticated', $1, 'execute') as authed,
                    has_function_privilege('service_role', $1, 'execute') as svc`,
            [fn],
          )
          .then((r) => r.rows[0]!),
      );
      expect(privs).toEqual({ anon: false, authed: false, svc: true });
    });

    it("anon and authenticated cannot read webhook.config", async () => {
      const privs = await withDb((c) =>
        c
          .query<{ anon: boolean; authed: boolean }>(
            `select has_table_privilege('anon', 'webhook.config', 'select') as anon,
                    has_table_privilege('authenticated', 'webhook.config', 'select') as authed`,
          )
          .then((r) => r.rows[0]!),
      );
      expect(privs).toEqual({ anon: false, authed: false });
    });

    it.skipIf(!ANON_KEY)(
      "the anon key cannot call public.webhook_endpoint_secret through PostgREST",
      async () => {
        await withEndpoint(async (id) => {
          await withDb((c) =>
            c.query(`select webhook.set_endpoint_secret($1, 'must-not-leak')`, [id]),
          );
          const { url } = localRestConfig();
          const anon = createClient(url, ANON_KEY, { auth: { persistSession: false } });
          const { data, error } = await anon.rpc("webhook_endpoint_secret", { p_endpoint_id: id });
          expect(error, "anon must be denied").toBeTruthy();
          expect(JSON.stringify(data ?? "")).not.toContain("must-not-leak");
        });
      },
    );

    it("the service role reads the secret through PostgREST (the panel's path)", async () => {
      await withEndpoint(async (id) => {
        await withDb((c) => c.query(`select webhook.set_endpoint_secret($1, 'svc-visible')`, [id]));
        const { url, serviceKey } = localRestConfig();
        const svc = createClient(url, serviceKey, { auth: { persistSession: false } });
        const { data, error } = await svc.rpc("webhook_endpoint_secret", { p_endpoint_id: id });
        expect(error).toBeNull();
        expect(data).toBe("svc-visible");
      });
    });
  });

  it("no webhook table has a column that could hold the secret (AC9)", async () => {
    const cols = await withDb((c) =>
      c
        .query<{ c: string }>(
          `select table_name || '.' || column_name as c
             from information_schema.columns
            where table_schema = 'public' and table_name like 'webhook\\_%'
              and column_name ~* '(secret|signature_value|hmac|token_hash)'`,
        )
        .then((r) => r.rows.map((x) => x.c)),
    );
    expect(cols).toEqual([]);
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-166 webhook Vault secret + config (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
