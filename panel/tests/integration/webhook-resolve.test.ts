import { createHmac, randomBytes } from "node:crypto";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 — S-171 (#316): routing + resolution through the real route, real
// rules, the real repositories allowlist, and the real bot-login RPC.
// Since S-172 a resolved route invokes the agent (AWS stubbed here) and is `fired`.

// A resolved route invokes the agent since S-172; stub only the AWS call.
const aws = vi.hoisted(() => ({ invokeAgentRuntime: vi.fn(async () => undefined) }));
vi.mock("@/lib/aws/invoke", () => aws);

const probe = await probeLocalDb();
const SECRET = "s171-l25-secret";
let token = "";
let endpointId = "";
let repoName = "";

async function post(
  payload: unknown,
  event = "issue_comment",
  deliveryId = randomBytes(8).toString("hex"),
) {
  const body = JSON.stringify(payload);
  const { POST } = await import("@/app/api/webhooks/[token]/route");
  const res = await POST(
    new Request(`http://local/api/webhooks/${token}`, {
      method: "POST",
      body,
      headers: {
        "x-github-event": event,
        "x-github-delivery": deliveryId,
        "x-hub-signature-256": "sha256=" + createHmac("sha256", SECRET).update(body).digest("hex"),
      },
    }),
    { params: Promise.resolve({ token }) },
  );
  return { status: res.status, json: (await res.json()) as Record<string, unknown> };
}

async function lastRow() {
  return withDb((c) =>
    c
      .query<{ outcome: string; reason: string | null; matched_rule_id: string | null }>(
        `select outcome::text as outcome, reason, matched_rule_id
           from webhook_deliveries where endpoint_id = $1 order by created_at desc, id desc limit 1`,
        [endpointId],
      )
      .then((r) => r.rows[0]),
  );
}

async function addRule(over: {
  position: number;
  conditions?: unknown;
  params?: unknown;
  is_default?: boolean;
}) {
  return withDb((c) =>
    c
      .query<{ id: string }>(
        `insert into webhook_rules (endpoint_id, position, event_types, conditions, is_default, agent_id,
                                    repo_mode, repo_payload_field, params)
         select $1, $2, array['issue_comment'], $3::jsonb, $4, id, 'payload_field', 'repository.full_name', $5::jsonb
           from agents where slug = 'security-analyst'
         returning id`,
        [
          endpointId,
          over.position,
          JSON.stringify(over.conditions ?? []),
          over.is_default ?? false,
          JSON.stringify(over.params ?? { static: { mode: "audit_only" } }),
        ],
      )
      .then((r) => r.rows[0]!.id),
  );
}

const hit = (
  full_name: string,
  body = "security review",
  sender = { login: "alice", type: "User" },
) => ({
  action: "created",
  comment: { body },
  repository: { full_name },
  sender,
});

describe.skipIf(!probe.available)("panel Layer 2.5 — S-171 route resolution", () => {
  beforeAll(() => {
    console.log(`[integration] ${probe.reason}`);
  });

  beforeEach(async () => {
    token = randomBytes(32).toString("base64url");
    ({ endpointId, repoName } = await withDb(async (c) => {
      const id = await c
        .query<{ id: string }>(
          `insert into webhook_endpoints (name, url_token, event_allowlist)
           values ('s171', $1, array['issue_comment']) returning id`,
          [token],
        )
        .then((r) => r.rows[0]!.id);
      await c.query(`select webhook.set_endpoint_secret($1, $2)`, [id, SECRET]);
      const name = await c
        .query<{
          full_name: string;
        }>(
          `select full_name from repositories where is_enabled and archived_at is null order by full_name limit 1`,
        )
        .then((r) => r.rows[0]!.full_name);
      return { endpointId: id, repoName: name };
    }));
  });

  afterEach(async () => {
    await withDb(async (c) => {
      await c.query(`delete from runs where triggered_by like $1`, [`webhook:${endpointId}:%`]);
      await c.query(`select webhook.delete_endpoint_secret($1)`, [endpointId]);
      await c.query(`delete from webhook_endpoints where id = $1`, [endpointId]);
    });
  });

  it("resolves the first matching rule against an allowlisted payload repo (AC4)", async () => {
    await addRule({
      position: 0,
      conditions: [{ field: "comment.body", op: "equals", value: "deploy" }],
    });
    const second = await addRule({
      position: 1,
      conditions: [{ field: "comment.body", op: "equals", value: "security review" }],
    });
    const res = await post(hit(repoName));
    expect(res.status).toBe(202);
    expect(await lastRow()).toEqual({
      outcome: "fired",
      reason: null,
      matched_rule_id: second,
    });
  });

  it("matches the payload repo name case-insensitively (EC-7)", async () => {
    const r = await addRule({ position: 0 });
    await post(hit(repoName.toUpperCase()));
    expect(await lastRow()).toMatchObject({ outcome: "fired", matched_rule_id: r });
  });

  it("rejects a payload repo that isn't registered, and creates no repository (AC5, I-4)", async () => {
    const r = await addRule({ position: 0 });
    const before = await withDb((c) =>
      c
        .query<{ n: number }>(`select count(*)::int as n from repositories`)
        .then((x) => x.rows[0]!.n),
    );
    const res = await post(hit("attacker/not-registered"));
    expect(res.json).toEqual({ skipped: true, reason: "repository_not_allowed" });
    expect(await lastRow()).toEqual({
      outcome: "route_rejected",
      reason: "repository_not_allowed",
      matched_rule_id: r,
    });
    const after = await withDb((c) =>
      c
        .query<{ n: number }>(`select count(*)::int as n from repositories`)
        .then((x) => x.rows[0]!.n),
    );
    expect(after).toBe(before);
  });

  it("rejects a disabled repository", async () => {
    await addRule({ position: 0 });
    await withDb((c) =>
      c.query(`update repositories set is_enabled = false where full_name = $1`, [repoName]),
    );
    try {
      await post(hit(repoName));
      expect((await lastRow())!.reason).toBe("repository_not_allowed");
    } finally {
      await withDb((c) =>
        c.query(`update repositories set is_enabled = true where full_name = $1`, [repoName]),
      );
    }
  });

  it("rejects params that fail the agent schema (AC5)", async () => {
    await addRule({ position: 0, params: { static: { mode: "destroy-everything" } } });
    await post(hit(repoName));
    expect((await lastRow())!).toMatchObject({
      outcome: "route_rejected",
      reason: "invalid_params",
    });
  });

  it("records no_match when nothing matches and there is no default", async () => {
    await addRule({
      position: 0,
      conditions: [{ field: "comment.body", op: "equals", value: "deploy" }],
    });
    const res = await post(hit(repoName, "hello"));
    expect(res.json).toEqual({ skipped: true, reason: "no_match" });
    expect(await lastRow()).toEqual({ outcome: "no_match", reason: null, matched_rule_id: null });
  });

  it("falls through to the default rule", async () => {
    await addRule({
      position: 0,
      conditions: [{ field: "comment.body", op: "equals", value: "deploy" }],
    });
    const def = await addRule({ position: 1, is_default: true });
    await post(hit(repoName, "hello"));
    expect(await lastRow()).toMatchObject({ outcome: "fired", matched_rule_id: def });
  });

  it("ignores an event from the configured bot account (AC7)", async () => {
    await addRule({ position: 0 });
    const bot = await withDb((c) =>
      c.query<{ b: string }>(`select webhook.bot_login() as b`).then((r) => r.rows[0]!.b),
    );
    const res = await post(hit(repoName, "security review", { login: bot, type: "Bot" }));
    expect(res.json).toEqual({ ignored: true, reason: "bot_author" });
    expect(await lastRow()).toEqual({
      outcome: "ignored",
      reason: "bot_author",
      matched_rule_id: null,
    });
  });

  it("records dropped undeclared params in the reason and never sends them", async () => {
    const r = await addRule({
      position: 0,
      params: { static: { mode: "audit_only" }, from_payload: { token: "comment.body" } },
    });
    await post(hit(repoName));
    expect(await lastRow()).toEqual({
      outcome: "fired",
      reason: "dropped undeclared params: token",
      matched_rule_id: r,
    });
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-171 route resolution (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
