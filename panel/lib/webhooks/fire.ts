/**
 * S-172 (#317) — fire a resolved webhook route through the shared invoke core
 * (D-W6) with the `webhook:<endpoint_id>:<rule_id>` trigger descriptor (D-W5),
 * then record the delivery as `fired` with the run id (AC1, FR16).
 *
 * A run that fails to start is still a real, visible `failed_to_start` row
 * (the core marks it), so the delivery is still `fired` and links to it. The
 * route answers 202 either way: the run row is where the failure is visible,
 * and a 5xx would only make GitHub redeliver a delivery that already has a run.
 * Guardrails (S-173) and the per-rule G3 counter hook in here.
 */

import type { InvokeCoreInput, InvokeCoreResult } from "@/lib/domain/invoke-resolved-run";
import type { ResolveResult } from "@/lib/domain/webhook-resolve";
import type { DispatchResult } from "@/lib/webhooks/dispatch";
import type { ReceivedDelivery } from "@/lib/webhooks/receive";
import type { WebhookRuleRow } from "@/lib/supabase/types";

export interface FireDeps {
  invoke(input: InvokeCoreInput): Promise<InvokeCoreResult>;
  recordFired(rowId: string, runId: string, ruleId: string, reason: string | null): Promise<void>;
  log(fields: Record<string, unknown>): void;
}

export async function fireResolvedRoute(
  deps: FireDeps,
  rule: WebhookRuleRow,
  resolved: Extract<ResolveResult, { ok: true }>,
  delivery: ReceivedDelivery,
): Promise<DispatchResult> {
  const outcome = await deps.invoke({
    agent: resolved.agent,
    repository: resolved.repository,
    params: resolved.params,
    trigger: { triggerType: "webhook", triggeredBy: `webhook:${delivery.endpointId}:${rule.id}` },
  });

  // Keep the dropped-undeclared-params note (D-W9) on the fired row.
  const note = resolved.droppedKeys.length
    ? `dropped undeclared params: ${resolved.droppedKeys.join(",")}`.slice(0, 500)
    : null;
  await deps.recordFired(delivery.rowId, outcome.runId, rule.id, note);
  deps.log({
    at: "webhook_delivery",
    endpoint_id: delivery.endpointId,
    row_id: delivery.rowId,
    rule_id: rule.id,
    run_id: outcome.runId,
    outcome: "fired",
    ...(outcome.ok ? {} : { error_code: outcome.errorCode }),
  });

  return {
    status: 202,
    body: { run_id: outcome.runId, status: outcome.ok ? "queued" : "failed_to_start" },
  };
}
