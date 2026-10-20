/**
 * S-171 (#316) — route resolution: a matched rule becomes a concrete, validated
 * (agent, repository, params), or a rejection with a fixed reason (D-W8, D-W9,
 * FR12–FR14). Pure over injected lookups.
 *
 * Safety rules:
 *  - the agent must exist and be enabled;
 *  - the repository (fixed id, or `owner/name` read from the payload) must
 *    already be registered, enabled, and not archived. A payload can never
 *    create one (I-4);
 *  - params = `static` overlaid with `from_payload` values, but only for keys
 *    the agent's params_schema declares (I-5). An undeclared key is dropped and
 *    reported, never sent. Only scalar payload values are interpolated. The
 *    result is validated with the same Ajv path as manual invoke and schedules.
 */

import type { AnySchema } from "ajv";
import { selectField } from "@/lib/domain/webhook-routing";
import { validateParams } from "@/lib/schema/validate";
import type {
  AgentRow,
  Json,
  RepositoryRow,
  WebhookRuleParams,
  WebhookRepoMode,
} from "@/lib/supabase/types";

/** GitHub `owner/name`: one slash, each side a safe identifier (EC-7). */
const FULL_NAME = /^[A-Za-z0-9_.-]{1,100}\/[A-Za-z0-9_.-]{1,100}$/;

export type ResolveFailure = "agent_unavailable" | "repository_not_allowed" | "invalid_params";

export type ResolveResult =
  | {
      ok: true;
      agent: AgentRow;
      repository: RepositoryRow | null;
      params: Record<string, unknown>;
      /** from_payload keys the agent schema doesn't declare; dropped, never sent. */
      droppedKeys: string[];
    }
  | { ok: false; reason: ResolveFailure };

export interface ResolvableRule {
  id: string;
  agent_id: string;
  repo_mode: WebhookRepoMode;
  repository_id: string | null;
  repo_payload_field: string | null;
  params: WebhookRuleParams;
}

export interface ResolveDeps {
  getAgent(id: string): Promise<AgentRow | null>;
  getRepositoryById(id: string): Promise<RepositoryRow | null>;
  getRepositoryByFullName(fullName: string): Promise<RepositoryRow | null>;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function usable(repo: RepositoryRow | null): repo is RepositoryRow {
  return repo !== null && repo.is_enabled && repo.archived_at === null;
}

function declaredKeys(schema: unknown): Set<string> {
  const props = isPlainObject(schema) ? schema.properties : undefined;
  return new Set(isPlainObject(props) ? Object.keys(props) : []);
}

async function resolveRepository(
  deps: ResolveDeps,
  rule: ResolvableRule,
  payload: unknown,
): Promise<RepositoryRow | null> {
  if (rule.repo_mode === "fixed") {
    return rule.repository_id ? deps.getRepositoryById(rule.repository_id) : null;
  }
  const name = rule.repo_payload_field ? selectField(payload, rule.repo_payload_field) : undefined;
  if (typeof name !== "string" || !FULL_NAME.test(name)) return null;
  return deps.getRepositoryByFullName(name);
}

export async function resolveRoute(
  deps: ResolveDeps,
  rule: ResolvableRule,
  payload: unknown,
): Promise<ResolveResult> {
  const agent = await deps.getAgent(rule.agent_id);
  if (!agent || !agent.is_enabled) return { ok: false, reason: "agent_unavailable" };

  let repository: RepositoryRow | null = null;
  if (agent.requires_repository) {
    const found = await resolveRepository(deps, rule, payload);
    if (!usable(found)) return { ok: false, reason: "repository_not_allowed" };
    repository = found;
  }

  const params = rule.params as unknown;
  if (!isPlainObject(params)) return { ok: false, reason: "invalid_params" };
  const staticParams = params.static ?? {};
  const fromPayload = params.from_payload ?? {};
  if (!isPlainObject(staticParams) || !isPlainObject(fromPayload)) {
    return { ok: false, reason: "invalid_params" };
  }

  const declared = declaredKeys(agent.params_schema);
  const merged: Record<string, unknown> = { ...staticParams };
  const droppedKeys: string[] = [];
  for (const [key, path] of Object.entries(fromPayload)) {
    if (!declared.has(key)) {
      droppedKeys.push(key);
      continue;
    }
    if (typeof path !== "string") return { ok: false, reason: "invalid_params" };
    const value = selectField(payload, path);
    if (value === undefined) continue;
    if (value !== null && typeof value === "object") return { ok: false, reason: "invalid_params" };
    merged[key] = value as Json;
  }

  const validation = validateParams(agent.id, agent.params_schema as AnySchema, merged);
  if (!validation.valid) return { ok: false, reason: "invalid_params" };

  return { ok: true, agent, repository, params: validation.params, droppedKeys };
}
