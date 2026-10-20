/**
 * S-172/S-173 — fire a resolved webhook route.
 *
 *  1. Guardrails (S-173, D-W10): G1 overlap, G5 open PR, G4 shared cap, decided
 *     by `public.webhook_guardrail` with the scheduler's own predicates. A skip
 *     records the delivery as `skipped:<reason>` and creates no run (AC6).
 *  2. Invoke through the shared core (S-172, D-W6) with the
 *     `webhook:<endpoint_id>:<rule_id>` trigger (D-W5), and record `fired` + the
 *     run id (AC1). A run that fails to start is still a visible
 *     `failed_to_start` row, so the delivery is still `fired`, answered 202.
 *  3. Report the outcome to G3 per rule: a start failure counts toward
 *     auto-disable; a clean start resets the counter.
 */

import type { InvokeCoreInput, InvokeCoreResult } from "@/lib/domain/invoke-resolved-run";
import type { ResolveResult } from "@/lib/domain/webhook-resolve";
import type { DispatchResult } from "@/lib/webhooks/dispatch";
import type { ReceivedDelivery } from "@/lib/webhooks/receive";
import type { WebhookRuleRow } from "@/lib/supabase/types";

export interface FireDeps {
  /** null = allowed; otherwise the skip reason (overlap / open_pr / concurrency_cap). */
  checkGuardrail(agentId: string, repositoryId: string | null): Promise<string | null>;
  invoke(input: InvokeCoreInput): Promise<InvokeCoreResult>;
  recordFired(rowId: string, runId: string, ruleId: string, reason: string | null): Promise<void>;
  recordSkipped(rowId: string, reason: string, ruleId: string): Promise<void>;
  recordRuleResult(ruleId: string, ok: boolean, errorCode: string | null): Promise<void>;
  log(fields: Record<string, unknown>): void;
}

export async function fireResolvedRoute(
  deps: FireDeps,
  rule: WebhookRuleRow,
  resolved: Extract<ResolveResult, { ok: true }>,
  delivery: ReceivedDelivery,
): Promise<DispatchResult> {
  const base = {
    at: "webhook_delivery",
    endpoint_id: delivery.endpointId,
    row_id: delivery.rowId,
    rule_id: rule.id,
  };

  const blocked = await deps.checkGuardrail(resolved.agent.id, resolved.repository?.id ?? null);
  if (blocked) {
    await deps.recordSkipped(delivery.rowId, blocked, rule.id);
    deps.log({ ...base, outcome: "skipped", reason: blocked });
    return { status: 202, body: { skipped: true, reason: blocked } };
  }

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
  await deps.recordRuleResult(rule.id, outcome.ok, outcome.ok ? null : outcome.errorCode);

  deps.log({
    ...base,
    run_id: outcome.runId,
    outcome: "fired",
    ...(outcome.ok ? {} : { error_code: outcome.errorCode }),
  });

  return {
    status: 202,
    body: { run_id: outcome.runId, status: outcome.ok ? "queued" : "failed_to_start" },
  };
}
