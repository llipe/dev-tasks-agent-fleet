/**
 * S-177 (#322) — save-time validation for a webhook rule (FR22, D-W7, D-W9).
 *
 * The runtime can only reject a broken rule when a delivery arrives
 * (`route_rejected`). This core runs the same checks before the rule is
 * stored, so the editor can flag it instead:
 *  - conditions: the S-170 stored-shape validator (fixed operators, no regex,
 *    unknown keys rejected per B-2, paths that parse and avoid forbidden segments);
 *  - events: non-empty and within the endpoint's allowlist (an event outside
 *    it is ignored at receive, so the rule could never match);
 *  - agent: exists and is enabled;
 *  - repository: a usable fixed repository, or a payload path that parses;
 *  - params: static values satisfy the agent schema, and every `from_payload`
 *    key is declared, scalar-typed, and mapped to a parseable path. A required
 *    key may be filled from the payload instead of statically.
 * A default rule ignores events and conditions at runtime, so they are cleared.
 *
 * Pure apart from the Ajv validator cache; total (never throws).
 */

import type { AnySchema } from "ajv";

import { parsePath, validateConditions } from "@/lib/domain/webhook-routing";
import { validateParams } from "@/lib/schema/validate";
import type {
  Json,
  WebhookCondition,
  WebhookRepoMode,
  WebhookRuleParams,
} from "@/lib/supabase/types";

export interface RuleAgentInfo {
  id: string;
  isEnabled: boolean;
  requiresRepository: boolean;
  paramsSchema: unknown;
}

export interface RuleValidationContext {
  /** The endpoint's event allowlist. */
  endpointEvents: string[];
  agents: Map<string, RuleAgentInfo>;
  /** Enabled, unarchived repositories. */
  usableRepositoryIds: Set<string>;
  /** Another rule on this endpoint that is already the default, if any. */
  otherDefaultRuleId: string | null;
}

export interface RuleWriteInput {
  name: string;
  eventTypes: string[];
  conditions: WebhookCondition[];
  isDefault: boolean;
  agentId: string;
  repoMode: WebhookRepoMode;
  repositoryId: string | null;
  repoPayloadField: string | null;
  params: Required<WebhookRuleParams>;
  autoDisableThreshold: number;
  notifyOnSuccess: boolean;
  isEnabled: boolean;
}

export type RuleField =
  | "name"
  | "eventTypes"
  | "conditions"
  | "isDefault"
  | "agentId"
  | "repoMode"
  | "repositoryId"
  | "repoPayloadField"
  | "params"
  | "autoDisableThreshold"
  | "notifyOnSuccess"
  | "isEnabled";

export type RuleFieldErrors = Partial<Record<RuleField, string>>;

export type RuleValidationResult =
  | { ok: true; value: RuleWriteInput }
  | { ok: false; fieldErrors: RuleFieldErrors };

export const MAX_AUTO_DISABLE_THRESHOLD = 100;
const SCALAR_TYPES = new Set(["string", "number", "integer", "boolean"]);

function obj(v: unknown): Record<string, unknown> | null {
  return v !== null && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

function schemaProperties(schema: unknown): Record<string, unknown> {
  return obj(obj(schema)?.properties) ?? {};
}

/** A declared property that a payload scalar can fill. */
function isScalarProperty(prop: unknown): boolean {
  const p = obj(prop);
  if (!p) return false;
  const t = p.type;
  if (typeof t === "string") return SCALAR_TYPES.has(t);
  if (Array.isArray(t))
    return t.length > 0 && t.every((x) => x === "null" || SCALAR_TYPES.has(String(x)));
  if (Array.isArray(p.enum)) return p.enum.every((x) => x === null || typeof x !== "object");
  return false;
}

/** "/1/field is not a valid path" → "Condition 2: field is not a valid path". */
function conditionMessage(raw: string): string {
  const m = /^\/(\d+)(?:\/(\S+))?\s*(.*)$/.exec(raw);
  if (!m) return raw.replace(/^\/\s*/, "");
  const n = Number(m[1]) + 1;
  return `Condition ${n}: ${[m[2], m[3]].filter(Boolean).join(" ")}`.trim();
}

export function validateRuleInput(raw: unknown, ctx: RuleValidationContext): RuleValidationResult {
  const r = obj(raw);
  if (!r) return { ok: false, fieldErrors: { name: "Invalid rule." } };
  const errors: RuleFieldErrors = {};

  // ---- name, flags --------------------------------------------------------
  const name = typeof r.name === "string" ? r.name.trim() : "";
  if (name.length > 100) errors.name = "Name must be 100 characters or fewer.";
  for (const f of ["isDefault", "notifyOnSuccess", "isEnabled"] as const) {
    if (typeof r[f] !== "boolean") errors[f] = "Invalid value.";
  }
  const isDefault = r.isDefault === true;
  if (isDefault && ctx.otherDefaultRuleId) {
    errors.isDefault = "This endpoint already has a default rule. Turn that one off first.";
  }

  const threshold = r.autoDisableThreshold;
  if (
    typeof threshold !== "number" ||
    !Number.isInteger(threshold) ||
    threshold < 1 ||
    threshold > MAX_AUTO_DISABLE_THRESHOLD
  ) {
    errors.autoDisableThreshold = `Use a whole number from 1 to ${MAX_AUTO_DISABLE_THRESHOLD}.`;
  }

  // ---- events + conditions (ignored for the default rule) -----------------
  let eventTypes: string[] = [];
  let conditions: WebhookCondition[] = [];
  if (!isDefault) {
    if (!Array.isArray(r.eventTypes) || r.eventTypes.some((e) => typeof e !== "string")) {
      errors.eventTypes = "Choose at least one event.";
    } else {
      eventTypes = [...new Set(r.eventTypes as string[])];
      const outside = eventTypes.filter((e) => !ctx.endpointEvents.includes(e));
      if (eventTypes.length === 0)
        errors.eventTypes = "Choose at least one event, or make this the default rule.";
      else if (outside.length > 0) {
        errors.eventTypes = `This endpoint ignores ${outside.join(", ")}. Add it to the endpoint's events first.`;
      }
    }
    const cv = validateConditions(r.conditions ?? []);
    if (!cv.valid) errors.conditions = cv.errors.map(conditionMessage).join("; ");
    else conditions = (r.conditions ?? []) as WebhookCondition[];
  }

  // ---- agent ----------------------------------------------------------------
  const agentId = typeof r.agentId === "string" ? r.agentId : "";
  const agent = ctx.agents.get(agentId);
  if (!agent) errors.agentId = "Choose an agent.";
  else if (!agent.isEnabled) errors.agentId = "This agent is disabled.";

  // ---- repository -----------------------------------------------------------
  const repoMode: WebhookRepoMode | null =
    r.repoMode === "fixed" || r.repoMode === "payload_field" ? r.repoMode : null;
  let repositoryId: string | null = null;
  let repoPayloadField: string | null = null;
  if (!repoMode) errors.repoMode = "Choose how the repository is picked.";
  else if (repoMode === "fixed") {
    repositoryId = typeof r.repositoryId === "string" ? r.repositoryId : null;
    if (!repositoryId) errors.repositoryId = "Choose a repository.";
    else if (!ctx.usableRepositoryIds.has(repositoryId)) {
      errors.repositoryId = "That repository is disabled or archived.";
    }
  } else {
    repoPayloadField = typeof r.repoPayloadField === "string" ? r.repoPayloadField.trim() : "";
    if (repoPayloadField === "")
      errors.repoPayloadField = "Enter the payload path to the repository full name.";
    else if (repoPayloadField.length > 200 || parsePath(repoPayloadField) === null) {
      errors.repoPayloadField = "Not a valid path (e.g. repository.full_name).";
    }
  }

  // ---- params ---------------------------------------------------------------
  const params = obj(r.params ?? {});
  const staticIn = params ? obj(params.static ?? {}) : null;
  const fromIn = params ? obj(params.from_payload ?? {}) : null;
  const staticParams: Record<string, Json> = {};
  const fromPayload: Record<string, string> = {};
  if (!params || !staticIn || !fromIn) {
    errors.params = "Invalid parameters.";
  } else if (agent) {
    const props = schemaProperties(agent.paramsSchema);
    const problems: string[] = [];

    for (const [k, v] of Object.entries(staticIn)) {
      if (v === "" || v === null || v === undefined) continue;
      if (!(k in props)) problems.push(`${k} is not a parameter of this agent`);
      staticParams[k] = v as Json;
    }
    Object.entries(fromIn).forEach(([k, path], i) => {
      const label = k === "" ? `Payload value ${i + 1}` : k;
      if (k === "") problems.push(`${label}: choose a parameter`);
      else if (!(k in props)) problems.push(`${k} is not a parameter of this agent`);
      else if (!isScalarProperty(props[k]))
        problems.push(`${k} can't be filled from the payload (not a single value)`);
      if (typeof path !== "string" || parsePath(path.trim()) === null) {
        problems.push(`${label}: not a valid payload path`);
      } else fromPayload[k] = path.trim();
    });

    if (problems.length === 0) {
      const v = validateParams(agent.id, agent.paramsSchema as AnySchema, staticParams);
      if (!v.valid) {
        for (const e of v.errors) {
          const missing = e.keyword === "required" ? /'([^']+)'/.exec(e.message)?.[1] : undefined;
          if (missing && missing in fromPayload) continue; // filled from the payload at run time
          problems.push(`${e.instancePath.replace(/^\//, "") || "params"} ${e.message}`);
        }
      }
    }
    if (problems.length > 0) errors.params = problems.join("; ");
  }

  if (Object.keys(errors).length > 0) return { ok: false, fieldErrors: errors };
  return {
    ok: true,
    value: {
      name,
      eventTypes,
      conditions,
      isDefault,
      agentId,
      repoMode: repoMode!,
      repositoryId,
      repoPayloadField,
      params: { static: staticParams, from_payload: fromPayload },
      autoDisableThreshold: threshold as number,
      notifyOnSuccess: r.notifyOnSuccess as boolean,
      isEnabled: r.isEnabled as boolean,
    },
  };
}

// ---------------------------------------------------------------------------
// Server Action cores (injectable). They build the validation context from the
// DB, so the check runs against current agents, repositories and rules.
// ---------------------------------------------------------------------------

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const isUuid = (v: unknown): v is string => typeof v === "string" && UUID.test(v);

export type RuleActionFailure =
  | { ok: false; code: "INVALID_INPUT"; message: string; fieldErrors: RuleFieldErrors }
  | { ok: false; code: "INVALID_ID" | "DATABASE_ERROR"; message: string };
export type SaveRuleResult = { ok: true; id: string } | RuleActionFailure;
export type RuleActionResult = { ok: true } | RuleActionFailure;

export interface SaveRuleDeps {
  getEndpoint: (id: string) => Promise<{ id: string; event_allowlist: string[] } | null>;
  getAgents: () => Promise<
    { id: string; is_enabled: boolean; requires_repository: boolean; params_schema: unknown }[]
  >;
  /** Ids of enabled, unarchived repositories. */
  getRepositoryIds: () => Promise<string[]>;
  getRules: (endpointId: string) => Promise<{ id: string; is_default: boolean }[]>;
  create: (endpointId: string, input: RuleWriteInput) => Promise<string>;
  update: (ruleId: string, input: RuleWriteInput) => Promise<void>;
}

const badId = (message = "Unknown rule or endpoint."): RuleActionFailure => ({
  ok: false,
  code: "INVALID_ID",
  message,
});
const dbFail = (message: string): RuleActionFailure => ({
  ok: false,
  code: "DATABASE_ERROR",
  message,
});

/** Create (`ruleId` null) or update a rule on an endpoint. Never throws. */
export async function resolveSaveRule(
  endpointId: unknown,
  ruleId: unknown,
  raw: unknown,
  deps: SaveRuleDeps,
): Promise<SaveRuleResult> {
  if (!isUuid(endpointId)) return badId();
  if (ruleId !== null && !isUuid(ruleId)) return badId();
  let ctx: RuleValidationContext;
  try {
    const [endpoint, agents, repoIds, rules] = await Promise.all([
      deps.getEndpoint(endpointId),
      deps.getAgents(),
      deps.getRepositoryIds(),
      deps.getRules(endpointId),
    ]);
    if (!endpoint) return badId("Unknown endpoint.");
    if (ruleId !== null && !rules.some((r) => r.id === ruleId)) return badId("Unknown rule.");
    ctx = {
      endpointEvents: endpoint.event_allowlist,
      agents: new Map(
        agents.map((a) => [
          a.id,
          {
            id: a.id,
            isEnabled: a.is_enabled,
            requiresRepository: a.requires_repository,
            paramsSchema: a.params_schema,
          },
        ]),
      ),
      usableRepositoryIds: new Set(repoIds),
      otherDefaultRuleId: rules.find((r) => r.is_default && r.id !== ruleId)?.id ?? null,
    };
  } catch {
    return dbFail("Could not load the endpoint. Try again.");
  }

  const v = validateRuleInput(raw, ctx);
  if (!v.ok) {
    return {
      ok: false,
      code: "INVALID_INPUT",
      message: "Fix the highlighted fields.",
      fieldErrors: v.fieldErrors,
    };
  }
  try {
    if (ruleId === null) return { ok: true, id: await deps.create(endpointId, v.value) };
    await deps.update(ruleId, v.value);
    return { ok: true, id: ruleId };
  } catch {
    return dbFail("Could not save the rule. Try again.");
  }
}

export async function resolveReorderRules(
  endpointId: unknown,
  orderedIds: unknown,
  deps: { reorder: (endpointId: string, ids: string[]) => Promise<void> },
): Promise<RuleActionResult> {
  if (!isUuid(endpointId) || !Array.isArray(orderedIds) || !orderedIds.every(isUuid))
    return badId();
  try {
    await deps.reorder(endpointId, orderedIds);
    return { ok: true };
  } catch {
    return dbFail("Could not reorder the rules. Reload and try again.");
  }
}

export async function resolveRuleMutation(
  ruleId: unknown,
  mutate: (id: string) => Promise<void>,
  failMessage: string,
): Promise<RuleActionResult> {
  if (!isUuid(ruleId)) return badId("Unknown rule.");
  try {
    await mutate(ruleId);
    return { ok: true };
  } catch {
    return dbFail(failMessage);
  }
}
