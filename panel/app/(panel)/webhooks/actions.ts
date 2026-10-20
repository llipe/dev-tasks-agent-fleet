"use server";

import { randomBytes } from "node:crypto";

import { createServerClient } from "@/lib/supabase/server";
import {
  createWebhookEndpoint,
  deleteWebhookEndpoint,
  rotateWebhookEndpointSecret,
  setWebhookEndpointEnabled,
  updateWebhookEndpoint,
} from "@/lib/supabase/queries";
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
