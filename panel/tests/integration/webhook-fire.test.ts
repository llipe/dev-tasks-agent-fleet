import { createHmac, randomBytes } from "node:crypto";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 — S-172 (#317): a signed, matching delivery creates a real `runs`
// row with trigger_type='webhook' / triggered_by='webhook:<endpoint>:<rule>',
// and the delivery links run_id + matched_rule_id (AC1). Everything is real
// except the AgentCore network call: the AWS wrapper is stubbed so the test
// needs no AWS access (same boundary the fire route's L1 suite mocks).

const aws = vi.hoisted(() => ({ invokeAgentRuntime: vi.fn() }));
vi.mock("@/lib/aws/invoke", () => aws);

const probe = await probeLocalDb();
const SECRET = "s172-l25-secret";
let token = "";
let endpointId = "";
let ruleId = "";
let repoName = "";

async function post(deliveryId: string) {
  const body = JSON.stringify({
    action: "created",
    comment: { body: "security review" },
    repository: { full_name: repoName },
    sender: { login: "alice", type: "User" },
  });
  const { POST } = await import("@/app/api/webhooks/[token]/route");
  const res = await POST(
    new Request(`http://local/api/webhooks/${token}`, {
      method: "POST",
      body,
      headers: {
        "x-github-event": "issue_comment",
        "x-github-delivery": deliveryId,
        "x-hub-signature-256": "sha256=" + createHmac("sha256", SECRET).update(body).digest("hex"),
      },
    }),
    { params: Promise.resolve({ token }) },
  );
  return { status: res.status, json: (await res.json()) as Record<string, unknown> };
}

describe.skipIf(!probe.available)("panel Layer 2.5 — S-172 webhook fires a run", () => {
  beforeAll(() => {
    console.log(`[integration] ${probe.reason}`);
  });

  beforeEach(async () => {
    aws.invokeAgentRuntime.mockReset();
    token = randomBytes(32).toString("base64url");
    ({ endpointId, ruleId, repoName } = await withDb(async (c) => {
      const ep = await c
        .query<{ id: string }>(
          `insert into webhook_endpoints (name, url_token, event_allowlist)
           values ('s172', $1, array['issue_comment']) returning id`,
          [token],
        )
        .then((r) => r.rows[0]!.id);
      await c.query(`select webhook.set_endpoint_secret($1, $2)`, [ep, SECRET]);
      const rule = await c
        .query<{ id: string }>(
          `insert into webhook_rules (endpoint_id, position, event_types, conditions, agent_id,
                                      repo_mode, repo_payload_field, params)
           select $1, 0, array['issue_comment'],
                  '[{"field":"comment.body","op":"equals","value":"security review"}]'::jsonb,
                  id, 'payload_field', 'repository.full_name', '{"static":{"mode":"audit_only"}}'::jsonb
             from agents where slug = 'security-analyst' returning id`,
          [ep],
        )
        .then((r) => r.rows[0]!.id);
      const name = await c
        .query<{
          full_name: string;
        }>(
          `select full_name from repositories where is_enabled and archived_at is null order by full_name limit 1`,
        )
        .then((r) => r.rows[0]!.full_name);
      return { endpointId: ep, ruleId: rule, repoName: name };
    }));
  });

  afterEach(async () => {
    await withDb(async (c) => {
      await c.query(`delete from runs where triggered_by = $1`, [
        `webhook:${endpointId}:${ruleId}`,
      ]);
      await c.query(`select webhook.delete_endpoint_secret($1)`, [endpointId]);
      await c.query(`delete from webhook_endpoints where id = $1`, [endpointId]);
    });
  });

  it("creates a queued webhook run and links it from the delivery (AC1)", async () => {
    aws.invokeAgentRuntime.mockResolvedValue(undefined);
    const res = await post("fire-1");
    expect(res.status).toBe(202);
    expect(res.json).toMatchObject({ status: "queued" });
    const runId = res.json.run_id as string;

    const run = await withDb((c) =>
      c
        .query(
          `select r.trigger_type::text as trigger_type, r.triggered_by, r.status::text as status,
                  r.params, rp.full_name
             from runs r join repositories rp on rp.id = r.repository_id where r.id = $1`,
          [runId],
        )
        .then((x) => x.rows[0]),
    );
    expect(run).toEqual({
      trigger_type: "webhook",
      triggered_by: `webhook:${endpointId}:${ruleId}`,
      status: "queued",
      params: { mode: "audit_only" },
      full_name: repoName,
    });

    const delivery = await withDb((c) =>
      c
        .query(
          `select outcome::text as outcome, run_id, matched_rule_id from webhook_deliveries where endpoint_id = $1`,
          [endpointId],
        )
        .then((x) => x.rows),
    );
    expect(delivery).toEqual([{ outcome: "fired", run_id: runId, matched_rule_id: ruleId }]);

    // The agent got the real contract payload, bounded by the webhook timeout.
    expect(aws.invokeAgentRuntime).toHaveBeenCalledWith(
      expect.objectContaining({ runtimeArn: expect.any(String) }),
      expect.objectContaining({
        timeoutMs: 8000,
        payload: expect.objectContaining({ run_id: runId, params: { mode: "audit_only" } }),
      }),
    );
  });

  it("records a run that failed to start, still links it, and acks with 202 (EC-22)", async () => {
    aws.invokeAgentRuntime.mockRejectedValue(
      Object.assign(new Error("boom"), { code: "INVOCATION_FAILED", status: 502 }),
    );
    const res = await post("fire-2");
    expect(res).toMatchObject({ status: 202, json: { status: "failed_to_start" } });
    const runId = res.json.run_id as string;
    const status = await withDb((c) =>
      c
        .query<{ s: string }>(`select status::text as s from runs where id = $1`, [runId])
        .then((x) => x.rows[0]!.s),
    );
    expect(status).toBe("failed_to_start");
    const outcome = await withDb((c) =>
      c
        .query<{
          o: string;
        }>(`select outcome::text as o from webhook_deliveries where run_id = $1`, [runId])
        .then((x) => x.rows[0]!.o),
    );
    expect(outcome).toBe("fired");
  });

  it("fires once for a replayed delivery (one run, AC2)", async () => {
    aws.invokeAgentRuntime.mockResolvedValue(undefined);
    await post("fire-3");
    const again = await post("fire-3");
    expect(again).toEqual({ status: 200, json: { duplicate: true } });
    expect(aws.invokeAgentRuntime).toHaveBeenCalledTimes(1);
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-172 webhook fires a run (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
