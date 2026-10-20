import { createHmac, randomBytes } from "node:crypto";
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 — S-169 (#314): POST /api/webhooks/[token] against the real local DB.
// The route handler is invoked directly (no server), with the service-role
// client from the environment, so the real queries, unique index and Vault
// secret are exercised. Covers AC2/AC3 and EC-14, EC-18, EC-20.

const probe = await probeLocalDb();
const SECRET = "s169-l25-secret";

let token = "";
let endpointId = "";

async function post(
  body: string,
  headers: Record<string, string>,
  tok = token,
): Promise<{ status: number; json: Record<string, unknown> }> {
  const { POST } = await import("@/app/api/webhooks/[token]/route");
  const res = await POST(
    new Request(`http://local/api/webhooks/${tok}`, { method: "POST", body, headers }),
    { params: Promise.resolve({ token: tok }) },
  );
  return { status: res.status, json: (await res.json()) as Record<string, unknown> };
}

function signed(body: string, deliveryId: string | null, event = "pull_request", secret = SECRET) {
  const h: Record<string, string> = {
    "content-type": "application/json",
    "x-github-event": event,
    "x-hub-signature-256": "sha256=" + createHmac("sha256", secret).update(body).digest("hex"),
  };
  if (deliveryId) h["x-github-delivery"] = deliveryId;
  return h;
}

async function rows(): Promise<
  { delivery_id: string | null; dedup_key: string | null; outcome: string; reason: string | null }[]
> {
  return withDb((c) =>
    c
      .query(
        `select delivery_id, dedup_key, outcome::text as outcome, reason
           from webhook_deliveries where endpoint_id = $1 order by created_at, id`,
        [endpointId],
      )
      .then((r) => r.rows),
  );
}

describe.skipIf(!probe.available)("panel Layer 2.5 — S-169 inbound webhook route", () => {
  beforeAll(() => {
    console.log(`[integration] ${probe.reason}`);
  });

  beforeEach(async () => {
    token = randomBytes(32).toString("base64url");
    endpointId = await withDb(async (c) => {
      const id = await c
        .query<{ id: string }>(
          `insert into webhook_endpoints (name, url_token, event_allowlist)
           values ('s169', $1, array['pull_request']) returning id`,
          [token],
        )
        .then((r) => r.rows[0]!.id);
      await c.query(`select webhook.set_endpoint_secret($1, $2)`, [id, SECRET]);
      return id;
    });
  });

  afterEach(async () => {
    await withDb(async (c) => {
      await c.query(`select webhook.delete_endpoint_secret($1)`, [endpointId]);
      await c.query(`delete from webhook_endpoints where id = $1`, [endpointId]);
    });
  });

  it("records a signed, allowlisted delivery as received and claims its key (AC1 front half)", async () => {
    const body = '{"action":"opened"}';
    const res = await post(body, signed(body, "d-1"));
    expect(res).toEqual({ status: 202, json: { received: true } });
    expect(await rows()).toEqual([
      { delivery_id: "d-1", dedup_key: "id:d-1", outcome: "received", reason: null },
    ]);
  });

  it("answers a replay with 200 duplicate and creates no second claim (AC2)", async () => {
    const body = "{}";
    await post(body, signed(body, "d-2"));
    const again = await post(body, signed(body, "d-2"));
    expect(again).toEqual({ status: 200, json: { duplicate: true } });
    const r = await rows();
    expect(r.map((x) => x.outcome)).toEqual(["received", "duplicate"]);
    expect(r.filter((x) => x.dedup_key !== null)).toHaveLength(1);
  });

  it("records unsigned and wrong-secret requests as unauthorized with no key (AC2, D-W16)", async () => {
    const body = "{}";
    const unsigned = await post(body, {
      "x-github-delivery": "d-3",
      "x-github-event": "pull_request",
    });
    const wrong = await post(body, signed(body, "d-3", "pull_request", "not-the-secret"));
    expect([unsigned.status, wrong.status]).toEqual([401, 401]);
    expect(await rows()).toEqual([
      { delivery_id: "d-3", dedup_key: null, outcome: "unauthorized", reason: "header_missing" },
      {
        delivery_id: "d-3",
        dedup_key: null,
        outcome: "unauthorized",
        reason: "signature_mismatch",
      },
    ]);
  });

  it("lets the genuine delivery through after a forged one reused its id (EC-20)", async () => {
    const body = '{"real":true}';
    const forged = await post(body, signed(body, "real-id", "pull_request", "attacker"));
    const genuine = await post(body, signed(body, "real-id"));
    expect([forged.status, genuine.status]).toEqual([401, 202]);
    expect((await rows()).map((x) => x.outcome)).toEqual(["unauthorized", "received"]);
  });

  it("claims exactly once when the same delivery arrives concurrently (EC-14)", async () => {
    const body = '{"race":1}';
    const results = await Promise.all(
      Array.from({ length: 5 }, () => post(body, signed(body, "race"))),
    );
    expect(results.map((r) => r.status).sort()).toEqual([200, 200, 200, 200, 202]);
    const r = await rows();
    expect(r.filter((x) => x.dedup_key !== null)).toHaveLength(1);
    expect(r).toHaveLength(5);
  });

  it("dedups on a body hash when the delivery header is absent, per endpoint (EC-18)", async () => {
    const body = '{"no":"id"}';
    expect((await post(body, signed(body, null))).status).toBe(202);
    expect((await post(body, signed(body, null))).status).toBe(200);
    const claimed = (await rows()).filter((x) => x.dedup_key !== null);
    expect(claimed).toHaveLength(1);
    expect(claimed[0]!.dedup_key).toMatch(/^body:[0-9a-f]{64}$/);
  });

  it("records a non-allowlisted event as ignored (AC3)", async () => {
    const body = "{}";
    const res = await post(body, signed(body, "d-4", "issues"));
    expect(res).toEqual({ status: 202, json: { ignored: true, reason: "event_not_allowed" } });
    expect((await rows())[0]).toMatchObject({ outcome: "ignored", reason: "event_not_allowed" });
  });

  it("answers 413 for an oversized body and writes no row (AC3)", async () => {
    const body = "x".repeat(5 * 1024 * 1024 + 1);
    const res = await post(body, signed(body, "d-5"));
    expect(res.status).toBe(413);
    expect(await rows()).toEqual([]);
  });

  it("answers 404 for a disabled endpoint and writes no row", async () => {
    await withDb((c) =>
      c.query(`update webhook_endpoints set is_enabled = false where id = $1`, [endpointId]),
    );
    const body = "{}";
    expect((await post(body, signed(body, "d-6"))).status).toBe(404);
    expect(await rows()).toEqual([]);
  });

  it("answers 404 for an unknown well-formed token", async () => {
    const body = "{}";
    expect(
      (await post(body, signed(body, "d-7"), randomBytes(32).toString("base64url"))).status,
    ).toBe(404);
  });

  it("answers 401 when the endpoint has no secret in Vault (EC-21)", async () => {
    await withDb((c) => c.query(`select webhook.delete_endpoint_secret($1)`, [endpointId]));
    const body = "{}";
    expect((await post(body, signed(body, "d-8"))).status).toBe(401);
    expect((await rows())[0]).toMatchObject({
      outcome: "unauthorized",
      reason: "secret_not_configured",
    });
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-169 inbound webhook route (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
