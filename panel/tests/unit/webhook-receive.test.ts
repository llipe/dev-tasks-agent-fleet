import { createHmac } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import {
  receiveWebhook,
  type ReceiveDeps,
  type ReceiveEndpoint,
  WEBHOOK_MAX_BODY_BYTES,
} from "@/lib/webhooks/receive";

// Layer 1 — S-169 (#314): the inbound receive core (spec §6.1 steps 1–5, D-W2,
// D-W3, D-W11, D-W16). Pure over injected deps, so ordering and every outcome
// are asserted without a server or DB. Routing is S-171; this story stops at
// `received` / `ignored`.

const SECRET = "test-secret";
const TOKEN = "a".repeat(43);
const enc = new TextEncoder();

function endpoint(over: Partial<ReceiveEndpoint> = {}): ReceiveEndpoint {
  return {
    id: "ep-1",
    is_enabled: true,
    signature_header: "x-hub-signature-256",
    delivery_id_header: "x-github-delivery",
    event_allowlist: ["pull_request", "issue_comment"],
    ...over,
  };
}

function sign(body: Uint8Array, secret = SECRET): string {
  return "sha256=" + createHmac("sha256", secret).update(body).digest("hex");
}

interface Harness {
  deps: ReceiveDeps;
  logs: Record<string, unknown>[];
  calls: string[];
}

function harness(
  opts: {
    endpoint?: ReceiveEndpoint | null;
    secret?: string | null;
    claimConflicts?: boolean;
  } = {},
): Harness {
  const logs: Record<string, unknown>[] = [];
  const calls: string[] = [];
  const deps: ReceiveDeps = {
    getEndpoint: vi.fn(async () => {
      calls.push("getEndpoint");
      return opts.endpoint === undefined ? endpoint() : opts.endpoint;
    }),
    getSecret: vi.fn(async () => {
      calls.push("getSecret");
      return opts.secret === undefined ? SECRET : opts.secret;
    }),
    claim: vi.fn(async () => {
      calls.push("claim");
      return opts.claimConflicts ? null : "row-claimed";
    }),
    recordUnclaimed: vi.fn(async (row) => {
      calls.push(`recordUnclaimed:${row.outcome}`);
      return "row-unclaimed";
    }),
    setOutcome: vi.fn(async (_id, outcome) => {
      calls.push(`setOutcome:${outcome}`);
    }),
    log: (fields) => logs.push(fields),
  };
  return { deps, logs, calls };
}

function request(
  body: Uint8Array | null,
  headers: Record<string, string> = {},
): { headers: Headers; readBody: () => Promise<Uint8Array | null> } {
  return {
    headers: new Headers(headers),
    readBody: vi.fn(async () => body),
  };
}

function signedRequest(
  payload: unknown,
  extra: Record<string, string> = {},
  secret = SECRET,
): ReturnType<typeof request> {
  const body = enc.encode(JSON.stringify(payload));
  return request(body, {
    "x-hub-signature-256": sign(body, secret),
    "x-github-delivery": "d-1",
    "x-github-event": "pull_request",
    ...extra,
  });
}

describe("receiveWebhook", () => {
  describe("token and endpoint (404, no row)", () => {
    it.each([
      ["too short", "short"],
      ["path traversal", "../" + "a".repeat(40)],
      ["encoded slash", "a".repeat(20) + "%2F" + "a".repeat(20)],
      ["too long", "a".repeat(65)],
    ])("rejects a %s token without a DB lookup (EC-8)", async (_label, token) => {
      const h = harness();
      const res = await receiveWebhook(h.deps, { token, ...signedRequest({}) });
      expect(res.status).toBe(404);
      expect(h.calls).toEqual([]);
    });

    it.each([
      ["unknown", null],
      ["disabled", endpoint({ is_enabled: false })],
    ])("returns 404 for an %s endpoint and writes no row or body read", async (_label, ep) => {
      const h = harness({ endpoint: ep });
      const req = signedRequest({});
      const res = await receiveWebhook(h.deps, { token: TOKEN, ...req });
      expect(res.status).toBe(404);
      expect(h.calls).toEqual(["getEndpoint"]);
      expect(req.readBody).not.toHaveBeenCalled();
    });
  });

  it("returns 413 for a body over the cap and writes no row (AC3)", async () => {
    const h = harness();
    const res = await receiveWebhook(h.deps, { token: TOKEN, ...request(null) });
    expect(res.status).toBe(413);
    expect(h.calls).toEqual(["getEndpoint"]);
    expect(WEBHOOK_MAX_BODY_BYTES).toBe(5 * 1024 * 1024);
  });

  describe("signature (401, unclaimed row)", () => {
    it.each([
      ["missing", { "x-hub-signature-256": "" }, "header_missing"],
      ["wrong secret", {}, "signature_mismatch"],
      ["malformed", { "x-hub-signature-256": "sha1=abc" }, "header_malformed"],
    ])(
      "records %s as unauthorized without claiming a key (D-W16)",
      async (_label, extra, reason) => {
        const h = harness();
        const req = signedRequest({ a: 1 }, extra, _label === "wrong secret" ? "other" : SECRET);
        const res = await receiveWebhook(h.deps, { token: TOKEN, ...req });
        expect(res.status).toBe(401);
        expect(h.calls).toEqual(["getEndpoint", "getSecret", "recordUnclaimed:unauthorized"]);
        const row = vi.mocked(h.deps.recordUnclaimed).mock.calls[0]![0];
        expect(row).toMatchObject({
          endpoint_id: "ep-1",
          outcome: "unauthorized",
          delivery_id: "d-1",
          reason,
        });
      },
    );

    it("fails closed when the endpoint has no secret (EC-21)", async () => {
      const h = harness({ secret: null });
      const res = await receiveWebhook(h.deps, { token: TOKEN, ...signedRequest({}) });
      expect(res.status).toBe(401);
      expect(vi.mocked(h.deps.recordUnclaimed).mock.calls[0]![0].reason).toBe(
        "secret_not_configured",
      );
    });

    it("uses the endpoint's configured signature header", async () => {
      const h = harness({ endpoint: endpoint({ signature_header: "x-signature" }) });
      const body = enc.encode("{}");
      const res = await receiveWebhook(h.deps, {
        token: TOKEN,
        ...request(body, { "x-signature": sign(body), "x-github-event": "pull_request" }),
      });
      expect(res.status).toBe(202);
    });

    it("clips over-long header values to the column caps on the unauthorized row (R-3)", async () => {
      const h = harness();
      const req = signedRequest(
        {},
        { "x-github-delivery": "d".repeat(500), "x-github-event": "e".repeat(500) },
        "other",
      );
      await receiveWebhook(h.deps, { token: TOKEN, ...req });
      const row = vi.mocked(h.deps.recordUnclaimed).mock.calls[0]![0];
      expect(row.delivery_id!.length).toBeLessThanOrEqual(200);
      expect(row.event_type!.length).toBeLessThanOrEqual(100);
    });
  });

  describe("dedup (D-W16)", () => {
    it("claims the namespaced key for a verified delivery", async () => {
      const h = harness();
      await receiveWebhook(h.deps, { token: TOKEN, ...signedRequest({}) });
      expect(vi.mocked(h.deps.claim).mock.calls[0]![0]).toMatchObject({
        endpoint_id: "ep-1",
        delivery_id: "d-1",
        dedup_key: "id:d-1",
        event_type: "pull_request",
      });
    });

    it("returns 200 duplicate and records an unclaimed duplicate row on conflict", async () => {
      const h = harness({ claimConflicts: true });
      const res = await receiveWebhook(h.deps, { token: TOKEN, ...signedRequest({}) });
      expect(res).toMatchObject({ status: 200, body: { duplicate: true } });
      expect(h.calls).toEqual(["getEndpoint", "getSecret", "claim", "recordUnclaimed:duplicate"]);
    });
  });

  describe("event and body (202 ignored)", () => {
    it.each([
      ["a missing event header", { "x-github-event": "" }, "missing_event"],
      ["an event not on the allowlist", { "x-github-event": "issues" }, "event_not_allowed"],
    ])("ignores %s", async (_label, extra, reason) => {
      const h = harness();
      const res = await receiveWebhook(h.deps, { token: TOKEN, ...signedRequest({}, extra) });
      expect(res).toMatchObject({ status: 202, body: { ignored: true, reason } });
      expect(h.calls.at(-1)).toBe("setOutcome:ignored");
    });

    it.each([
      ["invalid JSON", "{not json"],
      ["an empty body", ""],
      ["a top-level array", "[1,2]"],
      ["a JSON string", '"x"'],
    ])("ignores %s after a valid signature (CT-3)", async (_label, text) => {
      const h = harness();
      const body = enc.encode(text);
      const res = await receiveWebhook(h.deps, {
        token: TOKEN,
        ...request(body, {
          "x-hub-signature-256": sign(body),
          "x-github-delivery": "d-1",
          "x-github-event": "pull_request",
        }),
      });
      expect(res).toMatchObject({ status: 202, body: { ignored: true, reason: "invalid_json" } });
    });
  });

  it("returns 202 received with the parsed payload for an allowlisted, valid delivery", async () => {
    const h = harness();
    const res = await receiveWebhook(h.deps, {
      token: TOKEN,
      ...signedRequest({ action: "opened" }),
    });
    expect(res.status).toBe(202);
    expect(res.body).toEqual({ received: true });
    expect(res.delivery).toEqual({
      rowId: "row-claimed",
      endpointId: "ep-1",
      eventType: "pull_request",
      payload: { action: "opened" },
    });
    expect(h.calls).toEqual(["getEndpoint", "getSecret", "claim"]);
  });

  it("matches the allowlist case-sensitively on the exact event name", async () => {
    const h = harness();
    const res = await receiveWebhook(h.deps, {
      token: TOKEN,
      ...signedRequest({}, { "x-github-event": "Pull_Request" }),
    });
    expect(res.body).toMatchObject({ ignored: true, reason: "event_not_allowed" });
  });

  describe("responses and logs never carry secrets (AC9)", () => {
    it("never echoes the secret, signature, or payload", async () => {
      for (const opts of [{}, { claimConflicts: true }, { secret: "other" }]) {
        const h = harness(opts);
        const req = signedRequest({ token: "payload-value" });
        const sig = req.headers.get("x-hub-signature-256")!;
        const res = await receiveWebhook(h.deps, { token: TOKEN, ...req });
        const text = JSON.stringify([res.body, h.logs]);
        expect(text).not.toContain(SECRET);
        expect(text).not.toContain(sig.slice(7, 30));
        expect(text).not.toContain("payload-value");
      }
    });

    it("writes one structured log line per delivery", async () => {
      const h = harness();
      await receiveWebhook(h.deps, { token: TOKEN, ...signedRequest({}) });
      expect(h.logs).toEqual([
        expect.objectContaining({
          at: "webhook_delivery",
          endpoint_id: "ep-1",
          outcome: "received",
        }),
      ]);
    });
  });

  it("propagates a DB failure after verification (route answers 5xx so GitHub retries, EC-23)", async () => {
    const h = harness();
    vi.mocked(h.deps.claim).mockRejectedValueOnce(new Error("db down"));
    await expect(receiveWebhook(h.deps, { token: TOKEN, ...signedRequest({}) })).rejects.toThrow(
      "db down",
    );
  });
});
