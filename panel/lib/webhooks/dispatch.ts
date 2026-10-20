/**
 * S-171 (#316) — dispatch a `received` delivery: route it (S-170), resolve the
 * chosen rule (S-171), and record the outcome on the delivery row. Pure over
 * injected deps.
 *
 * Outcomes (all 202, so GitHub never retries a routing decision):
 *   bot_author        → `ignored`, reason `bot_author` (FR19)
 *   no_match          → `no_match` (FR15)
 *   resolve rejected  → `route_rejected` + reason + matched rule (FR13/FR14)
 *   resolved          → handed to `onResolved`. S-172 makes that invoke the
 *                       agent; until then the row stays `received`, reason
 *                       `resolved`, with the matched rule recorded.
 */

import { routeDelivery } from "@/lib/domain/webhook-routing";
import type { ResolveResult } from "@/lib/domain/webhook-resolve";
import type { ReceivedDelivery } from "@/lib/webhooks/receive";
import type { WebhookOutcome, WebhookRuleRow } from "@/lib/supabase/types";

const REASON_MAX = 500;

export interface DispatchResult {
  status: number;
  body: Record<string, unknown>;
}

export interface DispatchDeps {
  getEndpointRouting(endpointId: string): Promise<{ ignore_bot_author: boolean }>;
  getBotLogin(): Promise<string | null>;
  getRules(endpointId: string): Promise<WebhookRuleRow[]>;
  resolve(rule: WebhookRuleRow, payload: unknown): Promise<ResolveResult>;
  setRoute(
    rowId: string,
    outcome: WebhookOutcome,
    reason: string | null,
    ruleId: string | null,
  ): Promise<void>;
  onResolved(
    rule: WebhookRuleRow,
    resolved: Extract<ResolveResult, { ok: true }>,
    delivery: ReceivedDelivery,
  ): Promise<DispatchResult>;
}

function capped(reason: string): string {
  return reason.length > REASON_MAX ? reason.slice(0, REASON_MAX) : reason;
}

export async function dispatchDelivery(
  deps: DispatchDeps,
  delivery: ReceivedDelivery,
): Promise<DispatchResult> {
  const [routing, botLogin, rules] = await Promise.all([
    deps.getEndpointRouting(delivery.endpointId),
    deps.getBotLogin(),
    deps.getRules(delivery.endpointId),
  ]);

  const decision = routeDelivery(
    delivery.payload,
    delivery.eventType,
    { ignore_bot_author: routing.ignore_bot_author, bot_login: botLogin },
    rules,
  );

  if (decision.kind === "bot_author") {
    await deps.setRoute(delivery.rowId, "ignored", "bot_author", null);
    return { status: 202, body: { ignored: true, reason: "bot_author" } };
  }
  if (decision.kind === "no_match") {
    await deps.setRoute(delivery.rowId, "no_match", null, null);
    return { status: 202, body: { skipped: true, reason: "no_match" } };
  }

  const rule = rules.find((r) => r.id === decision.ruleId)!;
  const resolved = await deps.resolve(rule, delivery.payload);
  if (!resolved.ok) {
    await deps.setRoute(delivery.rowId, "route_rejected", resolved.reason, rule.id);
    return { status: 202, body: { skipped: true, reason: resolved.reason } };
  }

  const note = resolved.droppedKeys.length
    ? `resolved; dropped undeclared params: ${resolved.droppedKeys.join(",")}`
    : "resolved";
  await deps.setRoute(delivery.rowId, "received", capped(note), rule.id);
  return deps.onResolved(rule, resolved, delivery);
}
