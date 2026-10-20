/**
 * S-170 (#315) — the deterministic webhook routing engine (D-W7, D-W12, FR9–FR11,
 * FR15, FR19).
 *
 * A bounded, declarative matcher over an untrusted, already-parsed payload:
 *  - paths are dotted keys with `[n]` indexes, at most MAX_PATH_DEPTH segments;
 *  - only OWN properties are read, and `__proto__` / `constructor` / `prototype`
 *    are never traversed, so a hostile payload can't reach inherited values;
 *  - a fixed set of string ops, no regex and no code, strings capped at
 *    MAX_STRING_LENGTH; values are never coerced (a number is not "3");
 *  - evaluation is O(rules × conditions × depth) with no recursion over the
 *    payload, so deep or huge payloads can't blow the stack or the time budget.
 *
 * Everything here is pure and never throws on hostile input.
 */

import Ajv from "ajv";
import type { WebhookCondition, WebhookConditionOp } from "@/lib/supabase/types";

export const MAX_PATH_DEPTH = 16;
export const MAX_PATH_LENGTH = 200;
export const MAX_STRING_LENGTH = 1024;
export const MAX_CONDITIONS = 50;
export const MAX_IN_VALUES = 50;

const FORBIDDEN_KEYS = new Set(["__proto__", "constructor", "prototype"]);
/** One segment: a key (no dots/brackets/whitespace) followed by zero or more `[n]`. */
const KEY = /^[A-Za-z0-9_\-:@$]+$/;
const INDEX = /^\[(0|[1-9][0-9]{0,5})\]/;

/**
 * Parse `a.b[0].c` into ["a","b",0,"c"]. Returns null for any malformed path
 * (empty segment, negative/non-numeric/wildcard index, whitespace, too deep,
 * forbidden key).
 */
export function parsePath(path: string): (string | number)[] | null {
  if (typeof path !== "string" || path.length === 0 || path.length > MAX_PATH_LENGTH) return null;
  const out: (string | number)[] = [];
  for (const segment of path.split(".")) {
    const bracket = segment.indexOf("[");
    const key = bracket === -1 ? segment : segment.slice(0, bracket);
    if (!KEY.test(key) || FORBIDDEN_KEYS.has(key)) return null;
    out.push(key);
    let rest = bracket === -1 ? "" : segment.slice(bracket);
    while (rest.length > 0) {
      const m = INDEX.exec(rest);
      if (!m) return null;
      out.push(Number(m[1]));
      rest = rest.slice(m[0].length);
    }
    if (out.length > MAX_PATH_DEPTH) return null;
  }
  return out;
}

/** Resolve `path` against `payload`; `undefined` for a missing or invalid path. */
export function selectField(payload: unknown, path: string): unknown {
  const steps = parsePath(path);
  if (!steps) return undefined;
  let cur: unknown = payload;
  for (const step of steps) {
    if (typeof step === "number") {
      if (!Array.isArray(cur) || step >= cur.length) return undefined;
      cur = cur[step];
    } else {
      if (cur === null || typeof cur !== "object" || Array.isArray(cur)) return undefined;
      if (!Object.prototype.hasOwnProperty.call(cur, step)) return undefined;
      cur = (cur as Record<string, unknown>)[step];
    }
  }
  return cur;
}

function isCappedString(v: unknown): v is string {
  return typeof v === "string" && v.length <= MAX_STRING_LENGTH;
}

/** Evaluate one condition. False (never throws) for anything malformed. */
export function evaluateCondition(
  payload: unknown,
  eventType: string,
  cond: WebhookCondition,
): boolean {
  if (cond === null || typeof cond !== "object") return false;
  const { op, value } = cond as { op: WebhookConditionOp; value?: unknown };

  if (op === "matches_event") return isCappedString(value) && value === eventType;

  const field = selectField(payload, cond.field);
  switch (op) {
    case "exists":
      return field !== undefined && field !== null;
    case "in":
      return (
        isCappedString(field) &&
        Array.isArray(value) &&
        value.length <= MAX_IN_VALUES &&
        value.some((v) => isCappedString(v) && v === field)
      );
    case "equals":
    case "not_equals":
    case "contains":
    case "prefix":
    case "suffix": {
      if (!isCappedString(field) || !isCappedString(value)) return false;
      if (op === "equals") return field === value;
      if (op === "not_equals") return field !== value;
      if (op === "contains") return field.includes(value);
      if (op === "prefix") return field.startsWith(value);
      return field.endsWith(value);
    }
    default:
      return false;
  }
}

/** The rule fields routing reads (a subset of WebhookRuleRow). */
export interface RoutableRule {
  id: string;
  position: number;
  event_types: string[];
  conditions: WebhookCondition[];
  is_default: boolean;
  is_enabled: boolean;
}

export interface RoutingEndpoint {
  ignore_bot_author: boolean;
  /** `<app_slug>[bot]` from webhook.config, or null when unset. */
  bot_login: string | null;
}

export type RouteDecision =
  | { kind: "match"; ruleId: string }
  | { kind: "default"; ruleId: string }
  | { kind: "no_match" }
  | { kind: "bot_author" };

/** True when the event's sender is the fleet's own GitHub App bot (FR19). */
function isOwnBot(payload: unknown, botLogin: string | null): boolean {
  if (!botLogin) return false;
  return (
    selectField(payload, "sender.login") === botLogin &&
    selectField(payload, "sender.type") === "Bot"
  );
}

/**
 * Decide which rule a delivery fires (FR9): the bot-author guard first, then the
 * enabled non-default rules in `position` order (first match wins), then the
 * enabled default rule if any (FR15).
 */
export function routeDelivery(
  payload: unknown,
  eventType: string,
  endpoint: RoutingEndpoint,
  rules: RoutableRule[],
): RouteDecision {
  if (endpoint.ignore_bot_author && isOwnBot(payload, endpoint.bot_login)) {
    return { kind: "bot_author" };
  }
  const ordered = [...rules].sort((a, b) => a.position - b.position);
  for (const rule of ordered) {
    if (!rule.is_enabled || rule.is_default) continue;
    if (!rule.event_types.includes(eventType)) continue;
    if (rule.conditions.every((c) => evaluateCondition(payload, eventType, c))) {
      return { kind: "match", ruleId: rule.id };
    }
  }
  const fallback = ordered.find((r) => r.is_enabled && r.is_default);
  return fallback ? { kind: "default", ruleId: fallback.id } : { kind: "no_match" };
}

// ---------------------------------------------------------------------------
// Stored-shape validation for webhook_rules.conditions (CT-4). Used at save by
// the rule editor (S-177). Unknown keys are rejected (B-2): a stray key is
// usually a typo that would silently change what a rule matches.
// ---------------------------------------------------------------------------

const STRING_OPS = ["equals", "not_equals", "contains", "prefix", "suffix", "matches_event"];

const conditionsSchema = {
  type: "array",
  maxItems: MAX_CONDITIONS,
  items: {
    type: "object",
    additionalProperties: false,
    required: ["field", "op"],
    properties: {
      field: { type: "string", maxLength: MAX_PATH_LENGTH },
      op: { enum: [...STRING_OPS, "in", "exists"] },
      value: {
        anyOf: [
          { type: "string", maxLength: MAX_STRING_LENGTH },
          {
            type: "array",
            maxItems: MAX_IN_VALUES,
            items: { type: "string", maxLength: MAX_STRING_LENGTH },
          },
        ],
      },
    },
    allOf: [
      {
        if: { properties: { op: { enum: STRING_OPS } } },
        then: { required: ["value"], properties: { value: { type: "string" } } },
      },
      {
        if: { properties: { op: { const: "in" } } },
        then: { required: ["value"], properties: { value: { type: "array", minItems: 1 } } },
      },
      { if: { properties: { op: { const: "exists" } } }, then: { not: { required: ["value"] } } },
    ],
  },
} as const;

const validateShape = new Ajv({ allErrors: true, strict: false }).compile(conditionsSchema);

export interface ConditionsValidation {
  valid: boolean;
  errors: string[];
}

/** Validate a stored conditions list: Ajv shape, then each path parses (matches_event takes no path). */
export function validateConditions(input: unknown): ConditionsValidation {
  if (!validateShape(input)) {
    return {
      valid: false,
      errors: (validateShape.errors ?? []).map(
        (e) => `${e.instancePath || "/"} ${e.message ?? "is invalid"}`,
      ),
    };
  }
  const errors: string[] = [];
  (input as WebhookCondition[]).forEach((c, i) => {
    if (c.op !== "matches_event" && parsePath(c.field) === null)
      errors.push(`/${i}/field is not a valid path`);
  });
  return { valid: errors.length === 0, errors };
}
