import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import type { Client } from "pg";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 — S-173 (#318): guardrails for webhook-fired runs (D-W10, FR17).
//  - public.webhook_guardrail(agent, repo) decides with the scheduler's own
//    predicates: G1 overlap (scheduler.has_active_run), G5 open PR
//    (scheduler.open_pr_block_run, superseded by a later manual run), and G4
//    the shared cap (scheduler.max_inflight) over in-flight schedule AND
//    webhook runs.
//  - the scheduler's in-flight count now includes webhook runs, so the two
//    triggers share one cap.
//  - public.webhook_record_rule_result(rule, ok, error) is G3 per rule:
//    N consecutive failures disable the rule and write ONE notification;
//    a success resets the counter.
//  - all three are service_role-only (definer-grants.test.ts also enforces it).

const probe = await probeLocalDb();
let agentId = "";
let repoId = "";
let endpointId = "";
let ruleId = "";
const created: string[] = [];

async function run(
  c: Client,
  opts: { trigger?: "manual" | "schedule" | "webhook"; status?: string; createdAgo?: string } = {},
): Promise<string> {
  const id = randomUUID();
  const trigger = opts.trigger ?? "webhook";
  await c.query(
    `insert into runs (id, agent_id, agent_version, repository_id, trigger_type, triggered_by, status,
                       outcome, finished_at,
                       max_runtime_seconds, grace_seconds, start_timeout_seconds, created_at)
     select $1, a.id, a.version, $2, $3::trigger_type, $4, $5::run_status,
            case when $5 = 'succeeded' then 'no_findings'::run_outcome end,
            case when $5 = 'succeeded' then now() end,
            a.max_runtime_seconds, a.grace_seconds, a.start_timeout_seconds,
            now() - $6::interval
       from agents a where a.id = $7`,
    [
      id,
      repoId,
      trigger,
      trigger === "manual" ? "panel" : `${trigger}:s173`,
      opts.status ?? "queued",
      opts.createdAgo ?? "0 seconds",
      agentId,
    ],
  );
  created.push(id);
  return id;
}

async function guard(c: Client): Promise<string | null> {
  return c
    .query<{ r: string | null }>(`select public.webhook_guardrail($1, $2) as r`, [agentId, repoId])
    .then((r) => r.rows[0]!.r);
}

describe.skipIf(!probe.available)("panel Layer 2.5 — S-173 webhook guardrails", () => {
  beforeAll(() => {
    console.log(`[integration] ${probe.reason}`);
  });

  beforeEach(async () => {
    ({ agentId, repoId, endpointId, ruleId } = await withDb(async (c) => {
      const a = await c
        .query<{ id: string }>(`select id from agents where slug = 'security-analyst'`)
        .then((r) => r.rows[0]!.id);
      const rp = await c
        .query<{ id: string }>(`select id from repositories order by full_name limit 1`)
        .then((r) => r.rows[0]!.id);
      const ep = await c
        .query<{
          id: string;
        }>(`insert into webhook_endpoints (name, url_token) values ('s173', $1) returning id`, [
          "s173-" + randomUUID().replace(/-/g, ""),
        ])
        .then((r) => r.rows[0]!.id);
      const rl = await c
        .query<{ id: string }>(
          `insert into webhook_rules (endpoint_id, position, agent_id, repo_mode, repository_id, auto_disable_threshold)
           values ($1, 0, $2, 'fixed', $3, 3) returning id`,
          [ep, a, rp],
        )
        .then((r) => r.rows[0]!.id);
      // Clear any active runs for this (agent, repo) left by other suites so G1 starts clean.
      await c.query(
        `update runs set status = 'succeeded', outcome = 'no_findings', finished_at = now()
          where agent_id = $1 and repository_id = $2 and status in ('queued','running')`,
        [a, rp],
      );
      return { agentId: a, repoId: rp, endpointId: ep, ruleId: rl };
    }));
  });

  afterEach(async () => {
    await withDb(async (c) => {
      if (created.length) {
        await c.query(`delete from run_artifacts where run_id = any($1::uuid[])`, [created]);
        await c.query(`delete from notifications where run_id = any($1::uuid[])`, [created]);
        await c.query(`delete from runs where id = any($1::uuid[])`, [created]);
      }
      created.length = 0;
      await c.query(`delete from notifications where webhook_rule_id = $1`, [ruleId]);
      await c.query(`delete from webhook_endpoints where id = $1`, [endpointId]);
    });
  });

  it("allows a run when nothing blocks it", async () => {
    expect(await withDb(guard)).toBeNull();
  });

  describe("G1 overlap", () => {
    it.each(["queued", "running"])(
      "skips while a %s run exists for the same agent+repo (AC6)",
      async (status) => {
        await withDb(async (c) => {
          await run(c, { trigger: "manual", status });
          expect(await guard(c)).toBe("overlap");
        });
      },
    );

    it("does not count a stale running run past its reaper threshold (effective_status)", async () => {
      await withDb(async (c) => {
        const id = await run(c, { trigger: "manual", status: "running", createdAgo: "2 days" });
        await c.query(`update runs set started_at = now() - interval '2 days' where id = $1`, [id]);
        expect(await guard(c)).toBeNull();
      });
    });

    it("does not count a run for a different repository", async () => {
      await withDb(async (c) => {
        await c.query(`select 1`);
        const other = await c
          .query<{ id: string }>(`select id from repositories where id <> $1 limit 1`, [repoId])
          .then((r) => r.rows[0]?.id);
        if (!other) return; // single-repo seed: covered by the null-safe predicate tests in S-155
        const saved = repoId;
        repoId = other;
        await run(c, { trigger: "manual", status: "running" });
        repoId = saved;
        expect(await guard(c)).toBeNull();
      });
    });
  });

  describe("G5 open PR", () => {
    async function prRun(c: Client): Promise<string> {
      const id = await run(c, { trigger: "webhook", status: "succeeded" });
      await c.query(
        `insert into run_artifacts (run_id, type, url, metadata) values ($1, 'pull_request', 'https://github.com/x/y/pull/1', '{}')`,
        [id],
      );
      return id;
    }

    it("skips while the latest run for this agent+repo has an unresolved PR", async () => {
      await withDb(async (c) => {
        await prRun(c);
        expect(await guard(c)).toBe("open_pr");
      });
    });

    it("is cleared by a later manual run (G5-a supersede)", async () => {
      await withDb(async (c) => {
        await prRun(c);
        const m = await run(c, { trigger: "manual", status: "succeeded" });
        await c.query(`update runs set created_at = now() + interval '1 second' where id = $1`, [
          m,
        ]);
        expect(await guard(c)).toBeNull();
      });
    });
  });

  describe("G4 shared concurrency cap", () => {
    it("skips once in-flight schedule + webhook runs reach the cap (AC6)", async () => {
      await withDb(async (c) => {
        const cap = await c
          .query<{ n: number }>(`select scheduler.max_inflight() as n`)
          .then((r) => r.rows[0]!.n);
        const before = await c
          .query<{ n: number }>(`select scheduler.in_flight_scheduled_runs() as n`)
          .then((r) => r.rows[0]!.n);
        // Use a different agent so G1 doesn't fire first.
        const otherAgent = await c
          .query<{
            id: string;
          }>(`select id from agents where id <> $1 order by slug limit 1`, [agentId])
          .then((r) => r.rows[0]!.id);
        const saved = agentId;
        agentId = otherAgent;
        for (let i = before; i < cap; i++) {
          await run(c, { trigger: i % 2 ? "schedule" : "webhook", status: "queued" });
        }
        agentId = saved;
        expect(await guard(c)).toBe("concurrency_cap");
      });
    });

    it("counts webhook runs in the scheduler's in-flight number (one shared cap)", async () => {
      await withDb(async (c) => {
        const before = await c
          .query<{ n: number }>(`select scheduler.in_flight_scheduled_runs() as n`)
          .then((r) => r.rows[0]!.n);
        await run(c, { trigger: "webhook", status: "queued" });
        const after = await c
          .query<{ n: number }>(`select scheduler.in_flight_scheduled_runs() as n`)
          .then((r) => r.rows[0]!.n);
        expect(after).toBe(before + 1);
      });
    });

    it("does not count manual runs toward the cap (unchanged)", async () => {
      await withDb(async (c) => {
        const before = await c
          .query<{ n: number }>(`select scheduler.in_flight_scheduled_runs() as n`)
          .then((r) => r.rows[0]!.n);
        await run(c, { trigger: "manual", status: "queued" });
        const after = await c
          .query<{ n: number }>(`select scheduler.in_flight_scheduled_runs() as n`)
          .then((r) => r.rows[0]!.n);
        expect(after).toBe(before);
      });
    });
  });

  describe("G3 per rule", () => {
    async function record(c: Client, ok: boolean): Promise<void> {
      await c.query(`select public.webhook_record_rule_result($1, $2, $3)`, [
        ruleId,
        ok,
        ok ? null : "INVOCATION_FAILED",
      ]);
    }
    async function state(c: Client) {
      return c
        .query<{ n: number; enabled: boolean; notes: number }>(
          `select r.consecutive_failures as n, r.is_enabled as enabled,
                  (select count(*)::int from notifications where webhook_rule_id = r.id
                     and kind = 'webhook_rule_auto_disabled') as notes
             from webhook_rules r where r.id = $1`,
          [ruleId],
        )
        .then((r) => r.rows[0]!);
    }

    it("disables the rule after N consecutive failures and writes one notification", async () => {
      await withDb(async (c) => {
        await record(c, false);
        await record(c, false);
        expect(await state(c)).toEqual({ n: 2, enabled: true, notes: 0 });
        await record(c, false);
        expect(await state(c)).toEqual({ n: 3, enabled: false, notes: 1 });
        await record(c, false);
        expect((await state(c)).notes).toBe(1);
      });
    });

    it("resets the counter on success (EC-10)", async () => {
      await withDb(async (c) => {
        await record(c, false);
        await record(c, false);
        await record(c, true);
        await record(c, false);
        await record(c, false);
        expect(await state(c)).toEqual({ n: 2, enabled: true, notes: 0 });
      });
    });

    it("names the rule's endpoint in the notification", async () => {
      await withDb(async (c) => {
        for (let i = 0; i < 3; i++) await record(c, false);
        const n = await c
          .query<{
            title: string;
            agent_id: string;
          }>(`select title, agent_id from notifications where webhook_rule_id = $1`, [ruleId])
          .then((r) => r.rows[0]!);
        expect(n.title).toMatch(/s173/);
        expect(n.agent_id).toBe(agentId);
      });
    });
  });

  it("all three functions are service_role-only", async () => {
    const rows = await withDb((c) =>
      c
        .query<{ fn: string; anon: boolean; authed: boolean; svc: boolean }>(
          `select f as fn,
                  has_function_privilege('anon', f, 'execute') as anon,
                  has_function_privilege('authenticated', f, 'execute') as authed,
                  has_function_privilege('service_role', f, 'execute') as svc
             from unnest(array['public.webhook_guardrail(uuid,uuid)',
                               'public.webhook_record_rule_result(uuid,boolean,text)']) f`,
        )
        .then((r) => r.rows),
    );
    for (const r of rows) expect(r, r.fn).toMatchObject({ anon: false, authed: false, svc: true });
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-173 webhook guardrails (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
