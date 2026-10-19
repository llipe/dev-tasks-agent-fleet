import { beforeAll, describe, expect, it } from "vitest";
import type { Client } from "pg";
import type { AnySchema } from "ajv";
import { validateParams } from "@/lib/schema/validate";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 — S-165 (#309): webhook_endpoints / webhook_rules / webhook_deliveries.
//
// Verifies the migration applied by `supabase db reset`:
//  - the three tables and two enums exist;
//  - the (endpoint_id, position) and (endpoint_id, dedup_key) uniques hold;
//  - D-W16: rows that share a delivery_id with a null dedup_key are all accepted
//    (unauthorized attempts are tracked but never claim the dedup key), and an
//    unauthorized row can never carry a dedup_key;
//  - the repo_mode CHECK, the url_token format CHECK (EC-8), the length caps (R-3);
//  - FK behavior: deleting a run nulls run_id, deleting a rule nulls matched_rule_id
//    (EC-12), deleting an endpoint cascades its rules and deliveries;
//  - deny-all RLS: the anon role reads zero rows from each table while rows exist.
//    (`rls-deny-all.test.ts` also covers these tables through its schema
//    enumeration via PostgREST; this is the direct, non-vacuous SQL-role check.)
//
// Every test runs inside a transaction that is rolled back, so the shared local
// database is left as it was. Docker-gated via `probeLocalDb`.

const probe = await probeLocalDb();

const TOKEN_A = "s165-test-token-aaaaaaaaaaaaaaaaaaaaaa";
const TOKEN_B = "s165-test-token-bbbbbbbbbbbbbbbbbbbbbb";

/** Run `fn` in a transaction that is always rolled back. */
async function inTx<T>(fn: (c: Client) => Promise<T>): Promise<T> {
  return withDb(async (c) => {
    await c.query("begin");
    try {
      return await fn(c);
    } finally {
      await c.query("rollback");
    }
  });
}

/** Run one statement under a savepoint so an expected failure doesn't abort the tx. */
async function attempt(c: Client, sql: string, params: unknown[] = []): Promise<void> {
  await c.query("savepoint s");
  try {
    await c.query(sql, params);
    await c.query("release savepoint s");
  } catch (err) {
    await c.query("rollback to savepoint s");
    throw err;
  }
}

async function seedEndpoint(c: Client, token = TOKEN_A): Promise<string> {
  const r = await c.query<{ id: string }>(
    `insert into webhook_endpoints (name, url_token, event_allowlist)
     values ('s165', $1, array['pull_request']) returning id`,
    [token],
  );
  return r.rows[0]!.id;
}

async function anAgentId(c: Client): Promise<string> {
  const r = await c.query<{ id: string }>(`select id from agents order by slug limit 1`);
  return r.rows[0]!.id;
}

async function aRepoId(c: Client): Promise<string> {
  const r = await c.query<{ id: string }>(`select id from repositories limit 1`);
  return r.rows[0]!.id;
}

async function seedRule(c: Client, endpointId: string, position: number): Promise<string> {
  const r = await c.query<{ id: string }>(
    `insert into webhook_rules (endpoint_id, position, event_types, agent_id, repo_mode, repo_payload_field)
     values ($1, $2, array['pull_request'], $3, 'payload_field', 'repository.full_name') returning id`,
    [endpointId, position, await anAgentId(c)],
  );
  return r.rows[0]!.id;
}

describe.skipIf(!probe.available)("panel Layer 2.5 — S-165 webhook schema", () => {
  beforeAll(() => {
    console.log(`[integration] ${probe.reason}`);
  });

  it("has the three webhook tables", async () => {
    const names = await withDb((c) =>
      c
        .query<{ table_name: string }>(
          `select table_name from information_schema.tables
            where table_schema = 'public' and table_type = 'BASE TABLE'
              and table_name like 'webhook\\_%'`,
        )
        .then((r) => r.rows.map((x) => x.table_name).sort()),
    );
    expect(names).toEqual(["webhook_deliveries", "webhook_endpoints", "webhook_rules"]);
  });

  it("defines the webhook enums with the expected values", async () => {
    const rows = await withDb((c) =>
      c
        .query<{ typname: string; labels: string[] }>(
          `select t.typname, array_agg(e.enumlabel::text order by e.enumsortorder)::text[] as labels
             from pg_type t join pg_enum e on e.enumtypid = t.oid
            where t.typname in ('webhook_source', 'webhook_outcome')
            group by t.typname order by t.typname`,
        )
        .then((r) => r.rows),
    );
    expect(rows).toEqual([
      {
        typname: "webhook_outcome",
        labels: [
          "received",
          "unauthorized",
          "duplicate",
          "ignored",
          "no_match",
          "route_rejected",
          "skipped",
          "fired",
        ],
      },
      { typname: "webhook_source", labels: ["github", "generic"] },
    ]);
  });

  describe("webhook_endpoints", () => {
    it("applies the documented defaults", async () => {
      const row = await inTx(async (c) => {
        const id = await seedEndpoint(c);
        return (
          await c.query(
            `select source, signature_header, delivery_id_header, ignore_bot_author, is_enabled
               from webhook_endpoints where id = $1`,
            [id],
          )
        ).rows[0];
      });
      expect(row).toEqual({
        source: "github",
        signature_header: "x-hub-signature-256",
        delivery_id_header: "x-github-delivery",
        ignore_bot_author: true,
        is_enabled: true,
      });
    });

    it("rejects a duplicate url_token", async () => {
      await inTx(async (c) => {
        await seedEndpoint(c, TOKEN_A);
        await expect(seedEndpoint(c, TOKEN_A)).rejects.toThrow(/duplicate key/);
      });
    });

    it.each([
      ["too short", "short-token"],
      ["path traversal", "../aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
      ["encoded slash", "aaaaaaaaaaaaaaaa%2Faaaaaaaaaaaaaaaa"],
      ["too long", "a".repeat(65)],
    ])("rejects a url_token that is %s (EC-8)", async (_label, token) => {
      await inTx(async (c) => {
        await expect(
          attempt(c, `insert into webhook_endpoints (url_token) values ($1)`, [token]),
        ).rejects.toThrow(/check constraint/);
      });
    });
  });

  describe("webhook_rules", () => {
    it("rejects a duplicate (endpoint_id, position)", async () => {
      await inTx(async (c) => {
        const ep = await seedEndpoint(c);
        await seedRule(c, ep, 0);
        await expect(seedRule(c, ep, 0)).rejects.toThrow(/duplicate key/);
      });
    });

    it("allows the same position on different endpoints", async () => {
      await inTx(async (c) => {
        await seedRule(c, await seedEndpoint(c, TOKEN_A), 0);
        await expect(seedRule(c, await seedEndpoint(c, TOKEN_B), 0)).resolves.toBeTruthy();
      });
    });

    it("allows swapping positions in one transaction (deferrable unique)", async () => {
      await inTx(async (c) => {
        const ep = await seedEndpoint(c);
        const r0 = await seedRule(c, ep, 0);
        const r1 = await seedRule(c, ep, 1);
        await c.query(`set constraints uq_webhook_rules_endpoint_position deferred`);
        await c.query(`update webhook_rules set position = 1 where id = $1`, [r0]);
        await c.query(`update webhook_rules set position = 0 where id = $1`, [r1]);
        await expect(
          c.query(`set constraints uq_webhook_rules_endpoint_position immediate`),
        ).resolves.toBeTruthy();
      });
    });

    it("allows only one default rule per endpoint", async () => {
      await inTx(async (c) => {
        const ep = await seedEndpoint(c);
        const a = await seedRule(c, ep, 0);
        const b = await seedRule(c, ep, 1);
        await c.query(`update webhook_rules set is_default = true where id = $1`, [a]);
        await expect(
          attempt(c, `update webhook_rules set is_default = true where id = $1`, [b]),
        ).rejects.toThrow(/duplicate key/);
      });
    });

    it("rejects repo_mode='fixed' without a repository_id", async () => {
      await inTx(async (c) => {
        const ep = await seedEndpoint(c);
        await expect(
          attempt(
            c,
            `insert into webhook_rules (endpoint_id, position, agent_id, repo_mode)
             values ($1, 0, $2, 'fixed')`,
            [ep, await anAgentId(c)],
          ),
        ).rejects.toThrow(/check constraint/);
      });
    });

    it("rejects repo_mode='payload_field' without a repo_payload_field", async () => {
      await inTx(async (c) => {
        const ep = await seedEndpoint(c);
        await expect(
          attempt(
            c,
            `insert into webhook_rules (endpoint_id, position, agent_id, repo_mode)
             values ($1, 0, $2, 'payload_field')`,
            [ep, await anAgentId(c)],
          ),
        ).rejects.toThrow(/check constraint/);
      });
    });

    it("accepts repo_mode='fixed' with a repository_id", async () => {
      await inTx(async (c) => {
        const ep = await seedEndpoint(c);
        await expect(
          c.query(
            `insert into webhook_rules (endpoint_id, position, agent_id, repo_mode, repository_id)
             values ($1, 0, $2, 'fixed', $3)`,
            [ep, await anAgentId(c), await aRepoId(c)],
          ),
        ).resolves.toBeTruthy();
      });
    });

    it.each([
      ["an unknown repo_mode", `repo_mode = 'bogus'`],
      ["non-array conditions", `conditions = '{}'::jsonb`],
      ["non-object params", `params = '[]'::jsonb`],
      ["a zero auto_disable_threshold", `auto_disable_threshold = 0`],
      ["a negative position", `position = -1`],
    ])("rejects %s", async (_label, setClause) => {
      await inTx(async (c) => {
        const rule = await seedRule(c, await seedEndpoint(c), 0);
        await expect(
          attempt(c, `update webhook_rules set ${setClause} where id = $1`, [rule]),
        ).rejects.toThrow(/check constraint|invalid input value/);
      });
    });
  });

  describe("webhook_deliveries (D-W16 dedup)", () => {
    it("rejects a second claimed dedup_key on the same endpoint", async () => {
      await inTx(async (c) => {
        const ep = await seedEndpoint(c);
        const sql = `insert into webhook_deliveries (endpoint_id, delivery_id, dedup_key) values ($1, 'd-1', 'd-1')`;
        await c.query(sql, [ep]);
        await expect(attempt(c, sql, [ep])).rejects.toThrow(/duplicate key/);
      });
    });

    it("allows the same dedup_key on different endpoints", async () => {
      await inTx(async (c) => {
        const sql = `insert into webhook_deliveries (endpoint_id, delivery_id, dedup_key) values ($1, 'd-1', 'd-1')`;
        await c.query(sql, [await seedEndpoint(c, TOKEN_A)]);
        await expect(c.query(sql, [await seedEndpoint(c, TOKEN_B)])).resolves.toBeTruthy();
      });
    });

    it("accepts many unauthorized rows sharing a delivery_id, then the genuine claimed one", async () => {
      await inTx(async (c) => {
        const ep = await seedEndpoint(c);
        for (let i = 0; i < 3; i++) {
          await c.query(
            `insert into webhook_deliveries (endpoint_id, delivery_id, outcome)
             values ($1, 'real-id', 'unauthorized')`,
            [ep],
          );
        }
        await c.query(
          `insert into webhook_deliveries (endpoint_id, delivery_id, dedup_key, outcome)
           values ($1, 'real-id', 'real-id', 'received')`,
          [ep],
        );
        const n = await c.query<{ n: number }>(
          `select count(*)::int as n from webhook_deliveries where endpoint_id = $1 and delivery_id = 'real-id'`,
          [ep],
        );
        expect(n.rows[0]!.n).toBe(4);
      });
    });

    it("rejects an unauthorized row that carries a dedup_key", async () => {
      await inTx(async (c) => {
        await expect(
          attempt(
            c,
            `insert into webhook_deliveries (endpoint_id, delivery_id, dedup_key, outcome)
             values ($1, 'x', 'x', 'unauthorized')`,
            [await seedEndpoint(c)],
          ),
        ).rejects.toThrow(/check constraint/);
      });
    });

    it.each([
      ["delivery_id", 201],
      ["dedup_key", 201],
      ["event_type", 101],
      ["reason", 501],
    ])("caps %s length (R-3)", async (column, len) => {
      await inTx(async (c) => {
        await expect(
          attempt(c, `insert into webhook_deliveries (endpoint_id, ${column}) values ($1, $2)`, [
            await seedEndpoint(c),
            "x".repeat(len),
          ]),
        ).rejects.toThrow(/check constraint/);
      });
    });

    it("has the non-unique delivery_id lookup index and the feed index", async () => {
      const defs = await withDb((c) =>
        c
          .query<{
            indexdef: string;
          }>(`select indexdef from pg_indexes where tablename = 'webhook_deliveries'`)
          .then((r) => r.rows.map((x) => x.indexdef)),
      );
      expect(defs.some((d) => /\(endpoint_id, delivery_id\)/.test(d) && !/UNIQUE/.test(d))).toBe(
        true,
      );
      expect(defs.some((d) => /UNIQUE.*\(endpoint_id, dedup_key\)/.test(d))).toBe(true);
      expect(defs.some((d) => /\(endpoint_id, created_at DESC\)/.test(d))).toBe(true);
    });
  });

  describe("foreign keys", () => {
    it("nulls run_id when the run is deleted, and keeps the delivery", async () => {
      await inTx(async (c) => {
        const ep = await seedEndpoint(c);
        const run = await c.query<{ id: string }>(
          `insert into runs (id, agent_id, agent_version, trigger_type, triggered_by, status,
                             max_runtime_seconds, grace_seconds, start_timeout_seconds)
           select gen_random_uuid(), id, version, 'webhook', 'webhook:test', 'queued',
                  max_runtime_seconds, grace_seconds, start_timeout_seconds
             from agents order by slug limit 1 returning id`,
        );
        const runId = run.rows[0]!.id;
        const d = await c.query<{ id: string }>(
          `insert into webhook_deliveries (endpoint_id, outcome, run_id) values ($1, 'fired', $2) returning id`,
          [ep, runId],
        );
        await c.query(`delete from runs where id = $1`, [runId]);
        const after = await c.query(`select run_id from webhook_deliveries where id = $1`, [
          d.rows[0]!.id,
        ]);
        expect(after.rows).toEqual([{ run_id: null }]);
      });
    });

    it("nulls matched_rule_id when the rule is deleted (EC-12)", async () => {
      await inTx(async (c) => {
        const ep = await seedEndpoint(c);
        const rule = await seedRule(c, ep, 0);
        const d = await c.query<{ id: string }>(
          `insert into webhook_deliveries (endpoint_id, outcome, matched_rule_id) values ($1, 'no_match', $2) returning id`,
          [ep, rule],
        );
        await c.query(`delete from webhook_rules where id = $1`, [rule]);
        const after = await c.query(
          `select matched_rule_id from webhook_deliveries where id = $1`,
          [d.rows[0]!.id],
        );
        expect(after.rows).toEqual([{ matched_rule_id: null }]);
      });
    });

    it("cascades rules and deliveries when the endpoint is deleted", async () => {
      await inTx(async (c) => {
        const ep = await seedEndpoint(c);
        await seedRule(c, ep, 0);
        await c.query(`insert into webhook_deliveries (endpoint_id) values ($1)`, [ep]);
        await c.query(`delete from webhook_endpoints where id = $1`, [ep]);
        const left = await c.query<{ r: number; d: number }>(
          `select (select count(*)::int from webhook_rules where endpoint_id = $1) as r,
                  (select count(*)::int from webhook_deliveries where endpoint_id = $1) as d`,
          [ep],
        );
        expect(left.rows[0]).toEqual({ r: 0, d: 0 });
      });
    });
  });

  it("bumps updated_at on update for all three tables", async () => {
    await inTx(async (c) => {
      const ep = await seedEndpoint(c);
      const rule = await seedRule(c, ep, 0);
      const d = await c.query<{ id: string }>(
        `insert into webhook_deliveries (endpoint_id) values ($1) returning id`,
        [ep],
      );
      // Backdate, then touch each row; the trigger must move updated_at forward.
      for (const [table, id] of [
        ["webhook_endpoints", ep],
        ["webhook_rules", rule],
        ["webhook_deliveries", d.rows[0]!.id],
      ] as const) {
        await c.query(`update ${table} set updated_at = now() - interval '1 day' where id = $1`, [
          id,
        ]);
        await c.query(`update ${table} set created_at = created_at where id = $1`, [id]);
        const r = await c.query<{ fresh: boolean }>(
          `select updated_at > now() - interval '1 hour' as fresh from ${table} where id = $1`,
          [id],
        );
        expect(r.rows[0]!.fresh, table).toBe(true);
      }
    });
  });

  it("seeds one disabled local sample endpoint whose rule params satisfy the agent schema", async () => {
    const row = await withDb((c) =>
      c
        .query<{
          is_enabled: boolean;
          agent_id: string;
          params_schema: AnySchema;
          static_params: Record<string, unknown>;
        }>(
          `select e.is_enabled, r.agent_id, a.params_schema, r.params->'static' as static_params
             from webhook_endpoints e
             join webhook_rules r on r.endpoint_id = e.id
             join agents a on a.id = r.agent_id
            where e.url_token = 'local-dev-sample-endpoint-token-0000000'`,
        )
        .then((r) => r.rows),
    );
    expect(row).toHaveLength(1);
    // Disabled, so the route treats it as unknown (404) if it ever reaches a real DB.
    expect(row[0]!.is_enabled).toBe(false);
    const v = validateParams(row[0]!.agent_id, row[0]!.params_schema, row[0]!.static_params);
    expect(v.valid, JSON.stringify(v)).toBe(true);
  });

  it("denies the anon role every row while rows exist (non-vacuous RLS check)", async () => {
    await inTx(async (c) => {
      const ep = await seedEndpoint(c);
      await seedRule(c, ep, 0);
      await c.query(`insert into webhook_deliveries (endpoint_id) values ($1)`, [ep]);
      const asOwner = await c.query<{ e: number; r: number; d: number }>(
        `select (select count(*)::int from webhook_endpoints) as e,
                (select count(*)::int from webhook_rules) as r,
                (select count(*)::int from webhook_deliveries) as d`,
      );
      expect(asOwner.rows[0]!.e).toBeGreaterThan(0);
      expect(asOwner.rows[0]!.r).toBeGreaterThan(0);
      expect(asOwner.rows[0]!.d).toBeGreaterThan(0);

      await c.query(`set local role anon`);
      for (const table of ["webhook_endpoints", "webhook_rules", "webhook_deliveries"]) {
        const seen = await c.query<{ n: number }>(`select count(*)::int as n from ${table}`).then(
          (r) => r.rows[0]!.n,
          () => 0, // a permission error is also a deny
        );
        expect(seen, table).toBe(0);
      }
    });
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-165 webhook schema (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
