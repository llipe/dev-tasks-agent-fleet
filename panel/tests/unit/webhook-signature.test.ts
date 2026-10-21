import { createHash, createHmac } from "node:crypto";
import { describe, expect, it } from "vitest";
import { deliveryDedupKey, verifyHmacSignature } from "@/lib/auth/webhook-signature";
import { mulberry32, testSeed } from "../helpers/prng";

// Layer 1 — S-168 (#313): webhook signature verification (D-W1, D-W15, spec §9.1).
//
// The scheme is fixed: HMAC-SHA256 over the exact raw body bytes, presented as
// `sha256=<64 lowercase hex>`. The verifier is pure, constant-time, fail-closed,
// never throws, and never puts secret material in its reason.
//
// The first vector is GitHub's published example ("Validating webhook
// deliveries"), so the implementation is checked against an independent
// reference rather than only against itself.

const enc = new TextEncoder();
const GH_SECRET = "It's a Secret to Everybody";
const GH_BODY = enc.encode("Hello, World!");
const GH_SIG = "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17";

function sign(secret: string, body: Uint8Array): string {
  return "sha256=" + createHmac("sha256", secret).update(body).digest("hex");
}

describe("verifyHmacSignature", () => {
  it("accepts GitHub's published reference vector", () => {
    expect(verifyHmacSignature(GH_BODY, GH_SIG, GH_SECRET)).toEqual({ ok: true, reason: null });
  });

  it("accepts a freshly computed signature", () => {
    const body = enc.encode('{"action":"opened"}');
    expect(verifyHmacSignature(body, sign("s", body), "s").ok).toBe(true);
  });

  it("rejects the wrong secret", () => {
    expect(verifyHmacSignature(GH_BODY, GH_SIG, GH_SECRET + "x")).toEqual({
      ok: false,
      reason: "signature_mismatch",
    });
  });

  it("rejects a one-byte body change", () => {
    expect(verifyHmacSignature(enc.encode("Hello, World?"), GH_SIG, GH_SECRET).ok).toBe(false);
  });

  // EC-3: the HMAC covers the raw bytes, not a normalized form.
  it.each([
    ["a trailing newline", "Hello, World!\n"],
    ["CRLF instead of LF", "a\r\nb"],
  ])("rejects a signature made over the body without %s", (_label, text) => {
    const signedOver = enc.encode(text.replace(/\r\n/g, "\n").replace(/\n$/, ""));
    expect(verifyHmacSignature(enc.encode(text), sign("s", signedOver), "s").ok).toBe(false);
  });

  // EC-4: multibyte UTF-8 and non-UTF-8 bytes verify exactly as signed.
  it("verifies multibyte UTF-8 exactly as signed", () => {
    const body = enc.encode('{"comment":{"body":"looks good 👍 — ñ"}}');
    expect(verifyHmacSignature(body, sign("s", body), "s").ok).toBe(true);
  });

  it("verifies a body that is not valid UTF-8", () => {
    const body = new Uint8Array([0x7b, 0xff, 0xfe, 0x80, 0x7d]);
    expect(verifyHmacSignature(body, sign("s", body), "s").ok).toBe(true);
  });

  it.each([
    ["missing (null)", null],
    ["missing (undefined)", undefined],
    ["empty", ""],
  ])("rejects a %s header", (_label, header) => {
    expect(verifyHmacSignature(GH_BODY, header, GH_SECRET)).toEqual({
      ok: false,
      reason: "header_missing",
    });
  });

  it.each([
    ["uppercase hex", "sha256=" + GH_SIG.slice(7).toUpperCase()],
    ["a sha1= prefix", "sha1=" + "a".repeat(40)],
    ["no prefix (bare hex)", GH_SIG.slice("sha256=".length)],
    ["base64", "sha256=" + Buffer.from(GH_SIG.slice(7), "hex").toString("base64")],
    ["one hex char too many", GH_SIG + "0"],
    ["one hex char too few", GH_SIG.slice(0, -1)],
    ["a non-hex character", GH_SIG.slice(0, -1) + "g"],
    // EC-1: no trimming or splitting before the comparison.
    ["leading whitespace", " " + GH_SIG],
    ["trailing whitespace", GH_SIG + " "],
    ["two comma-joined values", `${GH_SIG},${GH_SIG}`],
  ])("rejects %s as malformed", (_label, header) => {
    expect(verifyHmacSignature(GH_BODY, header, GH_SECRET)).toEqual({
      ok: false,
      reason: "header_malformed",
    });
  });

  it.each([
    ["null", null],
    ["undefined", undefined],
    ["empty", ""],
  ])("fails closed when the secret is %s", (_label, secret) => {
    expect(verifyHmacSignature(GH_BODY, GH_SIG, secret)).toEqual({
      ok: false,
      reason: "secret_not_configured",
    });
  });

  // An empty body is still signed by GitHub; it must verify like any other.
  it("verifies an empty body", () => {
    const body = new Uint8Array(0);
    expect(verifyHmacSignature(body, sign("s", body), "s").ok).toBe(true);
  });

  it("never puts secret or signature material in the reason", () => {
    const results = [
      verifyHmacSignature(GH_BODY, GH_SIG, "other-secret"),
      verifyHmacSignature(GH_BODY, "garbage", GH_SECRET),
      verifyHmacSignature(GH_BODY, null, GH_SECRET),
      verifyHmacSignature(GH_BODY, GH_SIG, ""),
    ];
    for (const r of results) {
      expect(r.reason).toMatch(/^[a-z_]+$/);
      expect(r.reason).not.toContain(GH_SECRET);
      expect(r.reason).not.toContain(GH_SIG.slice(7, 20));
    }
  });

  it("never throws on hostile input types", () => {
    const hostile: unknown[] = [123, {}, [], Symbol("x"), () => 1, NaN];
    for (const h of hostile) {
      expect(() => verifyHmacSignature(GH_BODY, h as unknown as string, GH_SECRET)).not.toThrow();
      expect(verifyHmacSignature(GH_BODY, h as unknown as string, GH_SECRET).ok).toBe(false);
      expect(() =>
        verifyHmacSignature(h as unknown as Uint8Array, GH_SIG, GH_SECRET),
      ).not.toThrow();
      expect(verifyHmacSignature(h as unknown as Uint8Array, GH_SIG, GH_SECRET).ok).toBe(false);
    }
  });

  // RT-1 (test plan §6): random bodies and secrets; only the exact header verifies,
  // and any single-bit flip in the body or the presented digest rejects.
  it("RT-1: only the exact signature verifies; any single-bit flip rejects (seed 309001)", () => {
    const seed = testSeed(309001);
    const rand = mulberry32(seed);
    for (let i = 0; i < 2000; i++) {
      const len = Math.floor(rand() * 4096);
      const body = new Uint8Array(len);
      for (let j = 0; j < len; j++) body[j] = Math.floor(rand() * 256);
      const secret = Math.floor(rand() * 1e12).toString(36) + "k";
      const sig = sign(secret, body);
      expect(verifyHmacSignature(body, sig, secret).ok, `iter ${i} seed ${seed}`).toBe(true);

      if (len > 0) {
        const flipped = body.slice();
        const at = Math.floor(rand() * len);
        flipped[at] = flipped[at]! ^ (1 << Math.floor(rand() * 8));
        expect(
          verifyHmacSignature(flipped, sig, secret).ok,
          `body flip iter ${i} seed ${seed}`,
        ).toBe(false);
      }

      const pos = 7 + Math.floor(rand() * 64);
      const c = sig[pos]!;
      const swapped = c === "0" ? "1" : "0";
      const badSig = sig.slice(0, pos) + swapped + sig.slice(pos + 1);
      expect(
        verifyHmacSignature(body, badSig, secret).ok,
        `digest flip iter ${i} seed ${seed}`,
      ).toBe(false);
    }
  });
});

describe("deliveryDedupKey", () => {
  const body = enc.encode('{"x":1}');
  const bodyKey = "body:" + createHash("sha256").update(body).digest("hex");

  it("returns the namespaced delivery header value when present", () => {
    const h = new Headers({ "X-GitHub-Delivery": "72d3162e-cc78-11e3-81ab-4c9367dc0958" });
    expect(deliveryDedupKey(h, body, "x-github-delivery")).toBe(
      "id:72d3162e-cc78-11e3-81ab-4c9367dc0958",
    );
  });

  it("matches the configured header name case-insensitively", () => {
    const h = new Headers({ "X-Idempotency-Key": "abc" });
    expect(deliveryDedupKey(h, body, "x-idempotency-key")).toBe("id:abc");
  });

  it('accepts a header value of exactly 197 characters ("id:" + 197 = the 200 cap)', () => {
    const h = new Headers({ "x-github-delivery": "a".repeat(197) });
    expect(deliveryDedupKey(h, body, "x-github-delivery")).toBe("id:" + "a".repeat(197));
  });

  it.each([
    ["absent", new Headers()],
    ["empty", new Headers({ "x-github-delivery": "" })],
    ["198 characters (one past the cap)", new Headers({ "x-github-delivery": "a".repeat(198) })],
  ])("falls back to a body hash when the header is %s", (_label, h) => {
    expect(deliveryDedupKey(h, body, "x-github-delivery")).toBe(bodyKey);
  });

  it("keeps the body-hash key within the 200-character column cap", () => {
    expect(deliveryDedupKey(new Headers(), body, "x-github-delivery").length).toBeLessThanOrEqual(
      200,
    );
  });

  it("gives different bodies different fallback keys", () => {
    const other = deliveryDedupKey(new Headers(), enc.encode('{"x":2}'), "x-github-delivery");
    expect(other).not.toBe(bodyKey);
  });

  // A header value that happens to look like a body-hash key must not collide
  // with a real body-hash key for a different delivery.
  it("never lets a presented header impersonate a body-hash key", () => {
    const h = new Headers({ "x-github-delivery": bodyKey });
    expect(deliveryDedupKey(h, enc.encode("different"), "x-github-delivery")).not.toBe(bodyKey);
  });
});
