/**
 * S-168 (#313) — inbound webhook signature verification (D-W1, D-W15, spec §9.1).
 *
 * The signature scheme is FIXED in v1: HMAC-SHA256 over the exact raw request
 * bytes, presented as `sha256=<64 lowercase hex>` (GitHub's `X-Hub-Signature-256`
 * format). Only the header NAMES are configurable per endpoint; base64, bare hex,
 * uppercase hex and SHA-1 are rejected, not normalized.
 *
 * Raw bytes, not text: the caller passes the body as read with
 * `request.arrayBuffer()`. Decoding to a string first (`request.text()`) would
 * replace invalid UTF-8 with U+FFFD and verify against different bytes than the
 * sender signed (test plan EC-3/EC-4).
 *
 * Like `internal-secret.ts`: pure, constant-time on the digest comparison,
 * fail-closed on every negative case, never throws, and the `reason` is a fixed
 * token that never carries secret or signature material (AC9).
 */

import { createHash, createHmac, timingSafeEqual } from "node:crypto";

export type SignatureFailure =
  | "secret_not_configured"
  | "header_missing"
  | "header_malformed"
  | "body_invalid"
  | "signature_mismatch";

export type SignatureResult = { ok: true; reason: null } | { ok: false; reason: SignatureFailure };

/** `sha256=` followed by exactly 64 lowercase hex digits — nothing else. */
const SIGNATURE_FORMAT = /^sha256=[0-9a-f]{64}$/;

/**
 * Verify `presented` (the signature header value) against
 * HMAC-SHA256(secret, rawBody).
 *
 * @param rawBody the exact bytes received.
 * @param presented the configured signature header's value, or null/undefined.
 * @param secret the endpoint's signing secret from Vault, or null when unset.
 */
export function verifyHmacSignature(
  rawBody: Uint8Array,
  presented: string | null | undefined,
  secret: string | null | undefined,
): SignatureResult {
  if (typeof secret !== "string" || secret.length === 0) {
    return { ok: false, reason: "secret_not_configured" };
  }
  if (presented === null || presented === undefined || presented === "") {
    return { ok: false, reason: "header_missing" };
  }
  if (typeof presented !== "string" || !SIGNATURE_FORMAT.test(presented)) {
    return { ok: false, reason: "header_malformed" };
  }
  if (!(rawBody instanceof Uint8Array)) {
    return { ok: false, reason: "body_invalid" };
  }

  const expected = createHmac("sha256", secret).update(rawBody).digest();
  // Both sides are exactly 32 bytes here (the format check fixed the length),
  // so timingSafeEqual cannot throw on a length mismatch.
  const given = Buffer.from(presented.slice("sha256=".length), "hex");
  if (given.length !== expected.length || !timingSafeEqual(given, expected)) {
    return { ok: false, reason: "signature_mismatch" };
  }
  return { ok: true, reason: null };
}

/** `webhook_deliveries.dedup_key` is capped at 200 characters (S-165). */
const DEDUP_KEY_MAX = 200;
const ID_PREFIX = "id:";
const BODY_PREFIX = "body:";

/**
 * The dedup key a VERIFIED delivery claims (D-W16): the configured delivery-id
 * header's value, or a SHA-256 of the raw body when that header is absent, empty,
 * or too long to store. The two forms are namespaced (`id:` / `body:`) so a
 * presented header can never collide with another delivery's body-hash key.
 *
 * Only call this after `verifyHmacSignature` returned ok: unauthorized
 * deliveries never claim a key.
 */
export function deliveryDedupKey(
  headers: Headers,
  rawBody: Uint8Array,
  deliveryHeaderName: string,
): string {
  const value = headers.get(deliveryHeaderName);
  if (value && value.length > 0 && ID_PREFIX.length + value.length <= DEDUP_KEY_MAX) {
    return ID_PREFIX + value;
  }
  return BODY_PREFIX + createHash("sha256").update(rawBody).digest("hex");
}
