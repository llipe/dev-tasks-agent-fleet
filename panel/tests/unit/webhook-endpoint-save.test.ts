import { describe, expect, it, vi } from "vitest";
import {
  GITHUB_DEFAULT_HEADERS,
  resolveCreateEndpoint,
  resolveDeleteEndpoint,
  resolveRotateSecret,
  resolveToggleEndpoint,
  resolveUpdateEndpoint,
  validateEndpointSettings,
} from "@/lib/domain/webhook-endpoint-save";

// Layer 1 — S-176 (#321): pure, injectable cores behind the /webhooks Server
// Actions. Token and secret come from 32 random bytes each; the secret is
// returned exactly once (create / rotate) and never appears in an error.

const ID = "3f9b1c2e-8a4d-4c6b-9e1f-2a3b4c5d6e7f";
const bytes = (fill: number) => () => Buffer.alloc(32, fill);

const good = {
  name: "GitHub org",
  source: "github",
  eventAllowlist: ["issue_comment", "pull_request"],
  ignoreBotAuthor: true,
};

describe("validateEndpointSettings", () => {
  it("accepts a GitHub endpoint and pins the GitHub header names", () => {
    const r = validateEndpointSettings({
      ...good,
      signatureHeader: "x-evil",
      deliveryIdHeader: "x-evil",
    });
    expect(r).toEqual({
      ok: true,
      value: {
        name: "GitHub org",
        source: "github",
        eventAllowlist: ["issue_comment", "pull_request"],
        ignoreBotAuthor: true,
        ...GITHUB_DEFAULT_HEADERS,
      },
    });
  });

  it("lets a generic sender choose its header names (lower-cased) (D-W15)", () => {
    const r = validateEndpointSettings({
      ...good,
      source: "generic",
      signatureHeader: "X-Signature",
      deliveryIdHeader: "X-Request-Id",
    });
    expect(r.ok && r.value).toMatchObject({
      signatureHeader: "x-signature",
      deliveryIdHeader: "x-request-id",
    });
  });

  it("trims the name, dedupes events, and keeps their order", () => {
    const r = validateEndpointSettings({
      ...good,
      name: "  GH  ",
      eventAllowlist: ["push", "push", "issues"],
    });
    expect(r.ok && r.value).toMatchObject({ name: "GH", eventAllowlist: ["push", "issues"] });
  });

  it.each([
    ["an empty name", { name: "   " }, "name"],
    ["a name over 100 chars", { name: "x".repeat(101) }, "name"],
    ["an unknown source", { source: "gitlab" }, "source"],
    ["no events (everything would be ignored)", { eventAllowlist: [] }, "eventAllowlist"],
    ["a malformed event name", { eventAllowlist: ["Pull Request"] }, "eventAllowlist"],
    ["markup in an event name", { eventAllowlist: ["<script>"] }, "eventAllowlist"],
    [
      "more than 50 events",
      { eventAllowlist: Array.from({ length: 51 }, (_, i) => `e${i}`) },
      "eventAllowlist",
    ],
    ["a non-boolean bot toggle", { ignoreBotAuthor: "yes" }, "ignoreBotAuthor"],
  ])("rejects %s", (_label, patch, field) => {
    const r = validateEndpointSettings({ ...good, ...patch });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(Object.keys(r.fieldErrors)).toContain(field);
  });

  it.each(["", "x_sig", "a".repeat(65), "x sig"])("rejects generic header %j", (h) => {
    const r = validateEndpointSettings({
      ...good,
      source: "generic",
      signatureHeader: h,
      deliveryIdHeader: "x-id",
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.fieldErrors).toHaveProperty("signatureHeader");
  });

  it("is total over garbage input", () => {
    for (const raw of [null, undefined, 42, "x", []])
      expect(validateEndpointSettings(raw).ok).toBe(false);
  });
});

describe("resolveCreateEndpoint", () => {
  it("generates a 32-byte url token and secret, stores both, and returns the secret once", async () => {
    const create = vi.fn(async () => ID);
    const r = await resolveCreateEndpoint(good, { randomBytes: bytes(0xab), create });
    const token = Buffer.alloc(32, 0xab).toString("base64url");
    const secret = Buffer.alloc(32, 0xab).toString("hex");
    expect(r).toEqual({ ok: true, id: ID, urlToken: token, secret });
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ urlToken: token, secret, name: "GitHub org" }),
    );
    expect(token).toMatch(/^[A-Za-z0-9_-]{32,64}$/); // the DB token CHECK
    expect(secret).toHaveLength(64);
  });

  it("uses independent randomness for token and secret", async () => {
    let n = 0;
    const create = vi.fn(async () => ID);
    const r = await resolveCreateEndpoint(good, {
      randomBytes: () => Buffer.alloc(32, ++n),
      create,
    });
    expect(r.ok && r.secret).not.toBe(r.ok && Buffer.from(r.urlToken, "base64url").toString("hex"));
  });

  it("does not call the DB for invalid input", async () => {
    const create = vi.fn(async () => ID);
    const r = await resolveCreateEndpoint(
      { ...good, eventAllowlist: [] },
      { randomBytes: bytes(1), create },
    );
    expect(r).toMatchObject({ ok: false, code: "INVALID_INPUT" });
    expect(create).not.toHaveBeenCalled();
  });

  it("maps a DB failure to a generic error that never contains the secret", async () => {
    const secret = Buffer.alloc(32, 7).toString("hex");
    const create = vi.fn(async () => {
      throw new Error(`duplicate key ... ${secret}`);
    });
    const r = await resolveCreateEndpoint(good, { randomBytes: bytes(7), create });
    expect(r).toMatchObject({ ok: false, code: "DATABASE_ERROR" });
    expect(JSON.stringify(r)).not.toContain(secret);
  });
});

describe("resolveRotateSecret", () => {
  it("stores a new 32-byte secret and returns it once", async () => {
    const rotate = vi.fn(async () => {});
    const r = await resolveRotateSecret(ID, { randomBytes: bytes(0xcd), rotate });
    const secret = Buffer.alloc(32, 0xcd).toString("hex");
    expect(r).toEqual({ ok: true, secret });
    expect(rotate).toHaveBeenCalledWith(ID, secret);
  });

  it("rejects a non-uuid id without touching the DB", async () => {
    const rotate = vi.fn(async () => {});
    expect(await resolveRotateSecret("1; drop", { randomBytes: bytes(1), rotate })).toMatchObject({
      ok: false,
      code: "INVALID_ID",
    });
    expect(rotate).not.toHaveBeenCalled();
  });

  it("never leaks the secret in a DB error", async () => {
    const secret = Buffer.alloc(32, 9).toString("hex");
    const r = await resolveRotateSecret(ID, {
      randomBytes: bytes(9),
      rotate: async () => {
        throw new Error(secret);
      },
    });
    expect(r.ok).toBe(false);
    expect(JSON.stringify(r)).not.toContain(secret);
  });
});

describe("resolveUpdateEndpoint", () => {
  it("updates settings + enabled flag, and never sends a token or secret", async () => {
    const update = vi.fn(async () => {});
    const r = await resolveUpdateEndpoint(ID, { ...good, isEnabled: false }, { update });
    expect(r).toEqual({ ok: true });
    const [, input] = update.mock.calls[0] as unknown as [string, Record<string, unknown>];
    expect(input).toMatchObject({
      name: "GitHub org",
      isEnabled: false,
      ...GITHUB_DEFAULT_HEADERS,
    });
    expect(Object.keys(input)).not.toEqual(expect.arrayContaining(["urlToken"]));
    expect(Object.keys(input)).not.toEqual(expect.arrayContaining(["secret"]));
  });

  it("requires a boolean enabled flag", async () => {
    const update = vi.fn(async () => {});
    expect((await resolveUpdateEndpoint(ID, { ...good, isEnabled: "no" }, { update })).ok).toBe(
      false,
    );
    expect(update).not.toHaveBeenCalled();
  });

  it("rejects a bad id", async () => {
    const update = vi.fn(async () => {});
    expect(await resolveUpdateEndpoint("", good, { update })).toMatchObject({
      ok: false,
      code: "INVALID_ID",
    });
  });
});

describe("resolveDeleteEndpoint / resolveToggleEndpoint", () => {
  it("deletes by id", async () => {
    const remove = vi.fn(async () => {});
    expect(await resolveDeleteEndpoint(ID, { remove })).toEqual({ ok: true });
    expect(remove).toHaveBeenCalledWith(ID);
  });

  it("toggles enabled by id with a strict boolean", async () => {
    const setEnabled = vi.fn(async () => {});
    expect(await resolveToggleEndpoint(ID, false, { setEnabled })).toEqual({ ok: true });
    expect(setEnabled).toHaveBeenCalledWith(ID, false);
    expect((await resolveToggleEndpoint(ID, "false", { setEnabled })).ok).toBe(false);
  });

  it("maps DB failures to DATABASE_ERROR", async () => {
    const r = await resolveDeleteEndpoint(ID, {
      remove: async () => {
        throw new Error("boom");
      },
    });
    expect(r).toMatchObject({ ok: false, code: "DATABASE_ERROR" });
  });
});
