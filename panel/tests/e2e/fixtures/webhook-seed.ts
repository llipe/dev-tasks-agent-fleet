import type { APIRequestContext } from "@playwright/test";
import { createHmac, randomBytes } from "node:crypto";

import { withDb } from "./seed";

/**
 * S-179 (#324) — webhook E2E fixtures. Every endpoint a spec creates is named
 * `E2E …`, so the reset removes exactly those (rules and deliveries cascade)
 * plus their Vault secrets and the runs they fired. The seeded sample
 * endpoint is never touched.
 */

export const E2E_PREFIX = "E2E ";

export async function resetWebhooks(): Promise<void> {
  await withDb(async (c) => {
    await c.query(
      `delete from vault.secrets where name in (
         select 'webhook_endpoint_' || id from webhook_endpoints where name like 'E2E %')`,
    );
    await c.query(`delete from webhook_endpoints where name like 'E2E %'`);
    await c.query(
      `delete from notifications where run_id in (select id from runs where triggered_by like 'webhook:%')`,
    );
    await c.query(
      `delete from run_events where run_id in (select id from runs where triggered_by like 'webhook:%')`,
    );
    await c.query(`delete from runs where triggered_by like 'webhook:%'`);
  });
}

export interface SeededEndpoint {
  id: string;
  token: string;
  secret: string;
  ruleIds: string[];
}

/** An enabled endpoint with a secret and the given rules (all security-analyst, repo from the payload). */
export async function seedWebhookEndpoint(spec: {
  name?: string;
  events?: string[];
  rules?: { name: string; events: string[]; conditions: unknown[] }[];
}): Promise<SeededEndpoint> {
  const token = randomBytes(32).toString("base64url");
  const secret = randomBytes(32).toString("hex");
  return withDb(async (c) => {
    const id = await c
      .query<{
        id: string;
      }>(
        `insert into webhook_endpoints (name, url_token, event_allowlist) values ($1, $2, $3) returning id`,
        [
          E2E_PREFIX + (spec.name ?? "endpoint"),
          token,
          spec.events ?? ["issue_comment", "pull_request_review_comment"],
        ],
      )
      .then((r) => r.rows[0]!.id);
    await c.query(`select webhook.set_endpoint_secret($1, $2)`, [id, secret]);
    const ruleIds: string[] = [];
    for (const [i, r] of (spec.rules ?? []).entries()) {
      ruleIds.push(
        await c
          .query<{ id: string }>(
            `insert into webhook_rules (endpoint_id, position, name, event_types, conditions, agent_id,
                                        repo_mode, repo_payload_field, params)
             select $1, $2, $3, $4, $5::jsonb, a.id, 'payload_field', 'repository.full_name',
                    '{"static":{"mode":"audit_only"}}'::jsonb
               from agents a where a.slug = 'security-analyst'
             returning id`,
            [id, i, r.name, r.events, JSON.stringify(r.conditions)],
          )
          .then((x) => x.rows[0]!.id),
      );
    }
    return { id, token, secret, ruleIds };
  });
}

export const E2E_REPO = "llipe/memo-cli"; // an enabled seeded repository

export function commentPayload(
  body: string,
  over: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    action: "created",
    comment: { body, user: { login: "operator" } },
    issue: { number: 7 },
    repository: { full_name: E2E_REPO },
    sender: { login: "operator", type: "User" },
    ...over,
  };
}

export function sign(secret: string, body: string): string {
  return "sha256=" + createHmac("sha256", secret).update(body).digest("hex");
}

/** POST a delivery the way GitHub does. `secret: null` sends it unsigned. */
export async function postDelivery(
  request: APIRequestContext,
  token: string,
  opts: { event: string; deliveryId: string; payload: unknown; secret: string | null },
): Promise<{ status: number; json: unknown }> {
  const body = JSON.stringify(opts.payload);
  const headers: Record<string, string> = {
    "content-type": "application/json",
    "x-github-event": opts.event,
    "x-github-delivery": opts.deliveryId,
  };
  if (opts.secret) headers["x-hub-signature-256"] = sign(opts.secret, body);
  const res = await request.post(`/api/webhooks/${token}`, { data: body, headers });
  return { status: res.status(), json: await res.json().catch(() => null) };
}

export async function deliveriesFor(endpointId: string) {
  return withDb((c) =>
    c
      .query<{
        outcome: string;
        reason: string | null;
        run_id: string | null;
        matched_rule_id: string | null;
        delivery_id: string | null;
      }>(
        `select outcome::text, reason, run_id, matched_rule_id, delivery_id
           from webhook_deliveries where endpoint_id = $1 order by created_at, id`,
        [endpointId],
      )
      .then((r) => r.rows),
  );
}

export async function webhookRuns(endpointId: string) {
  return withDb((c) =>
    c
      .query<{
        id: string;
        trigger_type: string;
        triggered_by: string;
        status: string;
        repository: string | null;
      }>(
        `select r.id, r.trigger_type::text, r.triggered_by, r.status::text, rp.full_name repository
           from runs r left join repositories rp on rp.id = r.repository_id
          where r.triggered_by like $1 order by r.created_at`,
        [`webhook:${endpointId}:%`],
      )
      .then((r) => r.rows),
  );
}
