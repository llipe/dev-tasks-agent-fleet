/**
 * S-169 (#314) — `POST /api/webhooks/[token]`, the public inbound webhook
 * endpoint (D-W2). Classified `internal` by the route policy, so the session
 * gate is skipped; the HMAC signature check in `receiveWebhook` is the
 * authorization. This file only adapts HTTP to the pure core
 * (`lib/webhooks/receive.ts`) and wires the real queries.
 *
 * The body is read as raw bytes with a hard limit (D-W3, corrected in S-168):
 * `Content-Length` over the cap is refused up front, and the stream is cut off
 * at the cap when the header is absent or wrong (EC-29).
 *
 * Only POST is exported; other methods get Next's 405.
 * Route-segment config inline (S-104 audit D4 / §12): never cached.
 */

import { NextResponse } from "next/server";

import { createServerClient } from "@/lib/supabase/server";
import {
  claimWebhookDelivery,
  getEndpointSecret,
  getWebhookEndpointByToken,
  insertUnclaimedWebhookDelivery,
  setWebhookDeliveryOutcome,
} from "@/lib/supabase/queries";
import { readBodyWithLimit } from "@/lib/webhooks/read-body";
import { receiveWebhook, WEBHOOK_MAX_BODY_BYTES, type ReceiveDeps } from "@/lib/webhooks/receive";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";
export const runtime = "nodejs";

function deps(): ReceiveDeps {
  const client = createServerClient();
  return {
    getEndpoint: (token) => getWebhookEndpointByToken(client, token),
    getSecret: (endpointId) => getEndpointSecret(client, endpointId),
    claim: (row) => claimWebhookDelivery(client, row),
    recordUnclaimed: (row) => insertUnclaimedWebhookDelivery(client, row),
    setOutcome: (rowId, outcome, reason) =>
      setWebhookDeliveryOutcome(client, rowId, outcome, reason),
    log: (fields) => console.info(JSON.stringify(fields)),
  };
}

export async function POST(
  request: Request,
  context: { params: Promise<{ token: string }> },
): Promise<NextResponse> {
  const { token } = await context.params;
  try {
    const result = await receiveWebhook(deps(), {
      token,
      headers: request.headers,
      readBody: () => readBodyWithLimit(request, WEBHOOK_MAX_BODY_BYTES),
    });
    return NextResponse.json(result.body, { status: result.status });
  } catch (err) {
    // Never log the error message: it may carry Postgres detail. The name is
    // enough to correlate; GitHub retries the 5xx with the same delivery id.
    console.error(
      JSON.stringify({
        at: "webhook_delivery",
        status: 500,
        outcome: "error",
        error_name: err instanceof Error ? err.name : "unknown",
      }),
    );
    return NextResponse.json({ error: "INTERNAL_ERROR" }, { status: 500 });
  }
}
