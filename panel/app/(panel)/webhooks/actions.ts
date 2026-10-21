"use server";

import { randomBytes } from "node:crypto";

import { createServerClient } from "@/lib/supabase/server";
import {
  createWebhookEndpoint,
  createWebhookRule,
  deleteWebhookEndpoint,
  deleteWebhookRule,
  getEnabledAgents,
  getEnabledRepositories,
  getWebhookEndpointById,
  getWebhookRulesForEndpoint,
  reorderWebhookRules,
  rotateWebhookEndpointSecret,
  setWebhookEndpointEnabled,
  setWebhookRuleEnabled,
  updateWebhookEndpoint,
  updateWebhookRule,
} from "@/lib/supabase/queries";
import {
  resolveReorderRules,
  resolveRuleMutation,
  resolveSaveRule,
  type RuleActionResult,
  type SaveRuleResult,
} from "@/lib/domain/webhook-rule-save";
import {
  resolveCreateEndpoint,
  resolveDeleteEndpoint,
  resolveRotateSecret,
  resolveToggleEndpoint,
  resolveUpdateEndpoint,
  type CreateEndpointResult,
  type EndpointActionResult,
  type RotateSecretResult,
} from "@/lib/domain/webhook-endpoint-save";

/**
 * S-176 (#321) — the `/webhooks` endpoint Server Actions (FR20/FR21). Thin
 * `"use server"` wrappers over the pure cores in
 * `lib/domain/webhook-endpoint-save.ts`. They write through the service-role
 * client (RLS deny-all) and are reachable only with a session, because
 * `/webhooks` is a `ui` route behind the auth chokepoint.
 *
 * Create and rotate return the new secret ONCE, for the show-once panel. Nothing
 * else ever returns it.
 */

export async function createEndpointAction(raw: unknown): Promise<CreateEndpointResult> {
  const client = createServerClient();
  return resolveCreateEndpoint(raw, {
    randomBytes,
    create: (input) => createWebhookEndpoint(client, input),
  });
}

export async function updateEndpointAction(
  id: unknown,
  raw: unknown,
): Promise<EndpointActionResult> {
  const client = createServerClient();
  return resolveUpdateEndpoint(id, raw, {
    update: (endpointId, input) => updateWebhookEndpoint(client, endpointId, input),
  });
}

export async function rotateSecretAction(id: unknown): Promise<RotateSecretResult> {
  const client = createServerClient();
  return resolveRotateSecret(id, {
    randomBytes,
    rotate: (endpointId, secret) => rotateWebhookEndpointSecret(client, endpointId, secret),
  });
}

export async function deleteEndpointAction(id: unknown): Promise<EndpointActionResult> {
  const client = createServerClient();
  return resolveDeleteEndpoint(id, {
    remove: (endpointId) => deleteWebhookEndpoint(client, endpointId),
  });
}

export async function toggleEndpointAction(
  id: unknown,
  enabled: unknown,
): Promise<EndpointActionResult> {
  const client = createServerClient();
  return resolveToggleEndpoint(id, enabled, {
    setEnabled: (endpointId, next) => setWebhookEndpointEnabled(client, endpointId, next),
  });
}

// ---- S-177 (#322): rule editor -------------------------------------------

/** Create (`ruleId` null) or update a rule. Validated against live agents/repos/rules first. */
export async function saveRuleAction(
  endpointId: unknown,
  ruleId: unknown,
  raw: unknown,
): Promise<SaveRuleResult> {
  const client = createServerClient();
  return resolveSaveRule(endpointId, ruleId, raw, {
    getEndpoint: (id) => getWebhookEndpointById(client, id),
    getAgents: () => getEnabledAgents(client),
    getRepositoryIds: async () => (await getEnabledRepositories(client)).map((r) => r.id),
    getRules: (id) => getWebhookRulesForEndpoint(client, id),
    create: (id, input) => createWebhookRule(client, id, input),
    update: (id, input) => updateWebhookRule(client, id, input),
  });
}

export async function deleteRuleAction(ruleId: unknown): Promise<RuleActionResult> {
  const client = createServerClient();
  return resolveRuleMutation(
    ruleId,
    (id) => deleteWebhookRule(client, id),
    "Could not delete the rule. Try again.",
  );
}

export async function toggleRuleAction(
  ruleId: unknown,
  enabled: unknown,
): Promise<RuleActionResult> {
  const client = createServerClient();
  if (typeof enabled !== "boolean") {
    return { ok: false, code: "INVALID_ID", message: "Invalid value." };
  }
  return resolveRuleMutation(
    ruleId,
    (id) => setWebhookRuleEnabled(client, id, enabled),
    "Could not update the rule. Try again.",
  );
}

export async function reorderRulesAction(
  endpointId: unknown,
  orderedIds: unknown,
): Promise<RuleActionResult> {
  const client = createServerClient();
  return resolveReorderRules(endpointId, orderedIds, {
    reorder: (id, ids) => reorderWebhookRules(client, id, ids),
  });
}
