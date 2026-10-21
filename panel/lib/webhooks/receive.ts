/**
 * S-169 (#314) — the inbound webhook receive core (spec §6.1 steps 1–5).
 *
 * Pure over injected deps, so the route stays thin and the ordering is unit
 * tested. Order is fixed and security-relevant:
 *
 *   1. token format    → 404, before any DB lookup (EC-8)
 *   2. endpoint lookup → 404 when unknown or disabled (no row)
 *   3. body size       → 413 (no row)
 *   4. signature       → 401, recorded `unauthorized` WITHOUT a dedup key (D-W16)
 *   5. dedup claim     → 200 `duplicate` on conflict (recorded, unclaimed)
 *   6. event + JSON    → 202 `ignored` (missing/not-allowlisted event, bad JSON)
 *   7. otherwise       → 202 `received`; routing is S-171.
 *
 * Nothing is parsed before the signature verifies (I-1). Responses and log
 * lines never carry the secret, the signature, or payload content (AC9).
 * A dependency failure after verification propagates, so the route answers
 * 5xx and GitHub retries with the same delivery id (EC-23); because the claim
 * and the outcome are written by the same request, a retry after a failed
 * claim is not a duplicate.
 */

import { deliveryDedupKey, verifyHmacSignature } from "@/lib/auth/webhook-signature";
import type { WebhookOutcome } from "@/lib/supabase/types";

/** 5 MiB. GitHub caps payloads at 25 MB but real events are far smaller. */
export const WEBHOOK_MAX_BODY_BYTES = 5 * 1024 * 1024;

/** The event-type header (GitHub's). Generic senders must send it too in v1. */
export const WEBHOOK_EVENT_HEADER = "x-github-event";

/** Matches `chk_webhook_endpoints_url_token` (S-165). */
const TOKEN_FORMAT = /^[A-Za-z0-9_-]{32,64}$/;

/** Column caps on webhook_deliveries (S-165). */
const DELIVERY_ID_MAX = 200;
const EVENT_TYPE_MAX = 100;

export interface ReceiveEndpoint {
  id: string;
  is_enabled: boolean;
  signature_header: string;
  delivery_id_header: string;
  event_allowlist: string[];
}

export interface DeliveryRowInput {
  endpoint_id: string;
  delivery_id: string | null;
  event_type: string | null;
  outcome: WebhookOutcome;
  reason: string | null;
}

export interface ReceiveDeps {
  getEndpoint(token: string): Promise<ReceiveEndpoint | null>;
  getSecret(endpointId: string): Promise<string | null>;
  /** Insert a `received` row claiming `dedup_key`; returns its id, or null on a dedup conflict. */
  claim(
    row: Omit<DeliveryRowInput, "outcome" | "reason"> & { dedup_key: string },
  ): Promise<string | null>;
  /** Insert a row with no dedup key (unauthorized / duplicate). */
  recordUnclaimed(row: DeliveryRowInput): Promise<string>;
  setOutcome(rowId: string, outcome: WebhookOutcome, reason: string | null): Promise<void>;
  log(fields: Record<string, unknown>): void;
}

export interface ReceiveInput {
  token: string;
  headers: Headers;
  /** The raw body bytes, or null when it exceeded WEBHOOK_MAX_BODY_BYTES. */
  readBody(): Promise<Uint8Array | null>;
}

export interface ReceivedDelivery {
  rowId: string;
  endpointId: string;
  eventType: string;
  payload: Record<string, unknown>;
}

export interface ReceiveResult {
  status: number;
  body: Record<string, unknown>;
  /** Present only for a verified, allowlisted, parseable delivery (input to routing, S-171). */
  delivery?: ReceivedDelivery;
}

function clip(value: string | null, max: number): string | null {
  if (value === null || value.length === 0) return null;
  return value.length > max ? value.slice(0, max) : value;
}

export async function receiveWebhook(
  deps: ReceiveDeps,
  input: ReceiveInput,
): Promise<ReceiveResult> {
  const finish = (
    result: ReceiveResult,
    fields: { endpoint_id?: string; row_id?: string; outcome: string; reason?: string | null },
  ): ReceiveResult => {
    deps.log({ at: "webhook_delivery", status: result.status, ...fields });
    return result;
  };

  // 1–2. Token and endpoint. An unknown token is not a delivery to us: no row.
  if (typeof input.token !== "string" || !TOKEN_FORMAT.test(input.token)) {
    return finish({ status: 404, body: { error: "NOT_FOUND" } }, { outcome: "not_found" });
  }
  const endpoint = await deps.getEndpoint(input.token);
  if (!endpoint || !endpoint.is_enabled) {
    return finish({ status: 404, body: { error: "NOT_FOUND" } }, { outcome: "not_found" });
  }

  // 3. Size cap, before reading the secret or touching the DB again.
  const raw = await input.readBody();
  if (raw === null) {
    return finish(
      { status: 413, body: { error: "PAYLOAD_TOO_LARGE" } },
      { endpoint_id: endpoint.id, outcome: "too_large" },
    );
  }

  const deliveryId = clip(input.headers.get(endpoint.delivery_id_header), DELIVERY_ID_MAX);
  const eventHeader = input.headers.get(WEBHOOK_EVENT_HEADER);
  const eventType = clip(eventHeader, EVENT_TYPE_MAX);

  // 4. Signature. Failures are recorded for troubleshooting but never claim the
  //    dedup key, so a forged request can't block the genuine one (D-W16).
  const secret = await deps.getSecret(endpoint.id);
  const verdict = verifyHmacSignature(raw, input.headers.get(endpoint.signature_header), secret);
  if (!verdict.ok) {
    const rowId = await deps.recordUnclaimed({
      endpoint_id: endpoint.id,
      delivery_id: deliveryId,
      event_type: eventType,
      outcome: "unauthorized",
      reason: verdict.reason,
    });
    return finish(
      { status: 401, body: { error: "UNAUTHORIZED" } },
      { endpoint_id: endpoint.id, row_id: rowId, outcome: "unauthorized", reason: verdict.reason },
    );
  }

  // 5. Dedup claim (verified deliveries only).
  const rowId = await deps.claim({
    endpoint_id: endpoint.id,
    delivery_id: deliveryId,
    event_type: eventType,
    dedup_key: deliveryDedupKey(input.headers, raw, endpoint.delivery_id_header),
  });
  if (rowId === null) {
    const dupId = await deps.recordUnclaimed({
      endpoint_id: endpoint.id,
      delivery_id: deliveryId,
      event_type: eventType,
      outcome: "duplicate",
      reason: null,
    });
    return finish(
      { status: 200, body: { duplicate: true } },
      { endpoint_id: endpoint.id, row_id: dupId, outcome: "duplicate" },
    );
  }

  // 6. Event type and body. 202 so GitHub doesn't retry a deliberate ignore.
  const ignore = async (reason: string): Promise<ReceiveResult> => {
    await deps.setOutcome(rowId, "ignored", reason);
    return finish(
      { status: 202, body: { ignored: true, reason } },
      { endpoint_id: endpoint.id, row_id: rowId, outcome: "ignored", reason },
    );
  };
  if (!eventType) return ignore("missing_event");
  if (!endpoint.event_allowlist.includes(eventHeader!)) return ignore("event_not_allowed");

  let payload: unknown;
  try {
    payload = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
  } catch {
    return ignore("invalid_json");
  }
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    return ignore("invalid_json");
  }

  // 7. Received. Routing (S-171) consumes `delivery`.
  return finish(
    {
      status: 202,
      body: { received: true },
      delivery: {
        rowId,
        endpointId: endpoint.id,
        eventType: eventHeader!,
        payload: payload as Record<string, unknown>,
      },
    },
    { endpoint_id: endpoint.id, row_id: rowId, outcome: "received" },
  );
}
