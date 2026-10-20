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
import { randomUUID } from "node:crypto";
import type { SupabaseClient } from "@supabase/supabase-js";

import { createServerClient } from "@/lib/supabase/server";
import {
  claimWebhookDelivery,
  getAgentById,
  getEndpointSecret,
  getRepositoryByFullName,
  getRepositoryById,
  getWebhookBotLogin,
  getWebhookEndpointByToken,
  getWebhookEndpointRouting,
  getWebhookRulesForEndpoint,
  insertQueuedRun,
  insertUnclaimedWebhookDelivery,
  markRunFailedToStart,
  recordWebhookDeliveryFired,
  setWebhookDeliveryOutcome,
  setWebhookDeliveryRoute,
} from "@/lib/supabase/queries";
import { invokeAgentRuntime } from "@/lib/aws/invoke";
import { invokeResolvedRun } from "@/lib/domain/invoke-resolved-run";
import { resolveRoute, type ResolveDeps } from "@/lib/domain/webhook-resolve";
import { fireResolvedRoute } from "@/lib/webhooks/fire";
import { dispatchDelivery, type DispatchDeps } from "@/lib/webhooks/dispatch";
import { readBodyWithLimit } from "@/lib/webhooks/read-body";
import { receiveWebhook, WEBHOOK_MAX_BODY_BYTES, type ReceiveDeps } from "@/lib/webhooks/receive";

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";
export const runtime = "nodejs";

/**
 * Ceiling on the AgentCore invoke from a webhook (S-172, task 8.8). GitHub
 * abandons a delivery after 10 s. Observed run-start latency in production is
 * p95 3.2 s / max 4.1 s (30 days, includes agent boot), so 8 s leaves headroom
 * for the DB writes. On expiry the run is a visible failed_to_start and the
 * delivery is still acknowledged.
 */
const WEBHOOK_INVOKE_TIMEOUT_MS = 8000;

function deps(client: SupabaseClient): ReceiveDeps {
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

function dispatchDeps(client: SupabaseClient): DispatchDeps {
  const resolveDeps: ResolveDeps = {
    getAgent: (id) => getAgentById(client, id),
    getRepositoryById: (id) => getRepositoryById(client, id),
    getRepositoryByFullName: (name) => getRepositoryByFullName(client, name),
  };
  return {
    getEndpointRouting: (endpointId) => getWebhookEndpointRouting(client, endpointId),
    getBotLogin: () => getWebhookBotLogin(client),
    getRules: (endpointId) => getWebhookRulesForEndpoint(client, endpointId),
    resolve: (rule, payload) => resolveRoute(resolveDeps, rule, payload),
    setRoute: (rowId, outcome, reason, ruleId) =>
      setWebhookDeliveryRoute(client, rowId, outcome, reason, ruleId),
    // S-172: invoke through the shared core (same path as the schedule fire route).
    onResolved: (rule, resolved, delivery) =>
      fireResolvedRoute(
        {
          invoke: (input) =>
            invokeResolvedRun(
              {
                newRunId: randomUUID,
                insertQueuedRun: (insert) => insertQueuedRun(client, insert),
                invokeAgentRuntime: (target, req) =>
                  invokeAgentRuntime(target, { ...req, timeoutMs: WEBHOOK_INVOKE_TIMEOUT_MS }),
                markRunFailedToStart: (runId, code, message) =>
                  markRunFailedToStart(client, runId, code, message),
              },
              input,
            ),
          recordFired: (rowId, runId, ruleId, reason) =>
            recordWebhookDeliveryFired(client, rowId, runId, ruleId, reason),
          log: (fields) => console.info(JSON.stringify(fields)),
        },
        rule,
        resolved,
        delivery,
      ),
  };
}

export async function POST(
  request: Request,
  context: { params: Promise<{ token: string }> },
): Promise<NextResponse> {
  const { token } = await context.params;
  try {
    const client = createServerClient();
    const result = await receiveWebhook(deps(client), {
      token,
      headers: request.headers,
      readBody: () => readBodyWithLimit(request, WEBHOOK_MAX_BODY_BYTES),
    });
    if (!result.delivery) {
      return NextResponse.json(result.body, { status: result.status });
    }
    const routed = await dispatchDelivery(dispatchDeps(client), result.delivery);
    return NextResponse.json(routed.body, { status: routed.status });
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
