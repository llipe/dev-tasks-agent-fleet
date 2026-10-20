/**
 * S-176 (#321) — pure, injectable cores for the `/webhooks` endpoint Server
 * Actions. They live outside the `"use server"` module (which may only export
 * async functions), the same split as `schedule-save.ts`.
 *
 * Token and secret are 32 random bytes each (base64url token, hex secret). The
 * secret is returned exactly once, from create or rotate, for the show-once
 * panel. It is never re-read, and no failure result ever contains it: every
 * DB error maps to a generic `DATABASE_ERROR` with no detail.
 *
 * The DB stays the final authority (token/header CHECKs, unique token); these
 * cores fail fast so a bad submit never round-trips.
 */

import type { WebhookSource } from "@/lib/supabase/types";
import type { WebhookEndpointCreateInput, WebhookEndpointSettings } from "@/lib/supabase/queries";

/** GitHub's header names are fixed; only a generic sender may choose its own (D-W15). */
export const GITHUB_DEFAULT_HEADERS = {
  signatureHeader: "x-hub-signature-256",
  deliveryIdHeader: "x-github-delivery",
} as const;

/** Common GitHub events offered as checkboxes; any valid name may be added. */
export const GITHUB_EVENT_OPTIONS = [
  "issue_comment",
  "pull_request",
  "pull_request_review",
  "pull_request_review_comment",
  "push",
  "issues",
  "check_suite",
  "workflow_run",
  "release",
] as const;

export const MAX_ENDPOINT_EVENTS = 50;
const EVENT_NAME = /^[a-z][a-z0-9_.-]{0,63}$/;
const HEADER_NAME = /^[a-z0-9-]{1,64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type EndpointFieldErrors = Partial<
  Record<
    | "name"
    | "source"
    | "eventAllowlist"
    | "ignoreBotAuthor"
    | "signatureHeader"
    | "deliveryIdHeader"
    | "isEnabled",
    string
  >
>;

export interface ValidatedEndpointSettings extends WebhookEndpointSettings {
  source: WebhookSource;
}

export type ValidateResult =
  | { ok: true; value: ValidatedEndpointSettings }
  | { ok: false; fieldErrors: EndpointFieldErrors };

export type EndpointFailure =
  | { ok: false; code: "INVALID_INPUT"; message: string; fieldErrors: EndpointFieldErrors }
  | { ok: false; code: "INVALID_ID" | "DATABASE_ERROR"; message: string };

export type EndpointActionResult = { ok: true } | EndpointFailure;
export type CreateEndpointResult =
  | { ok: true; id: string; urlToken: string; secret: string }
  | EndpointFailure;
export type RotateSecretResult = { ok: true; secret: string } | EndpointFailure;

type RandomBytes = (n: number) => Uint8Array;

function rec(raw: unknown): Record<string, unknown> | null {
  return raw && typeof raw === "object" && !Array.isArray(raw)
    ? (raw as Record<string, unknown>)
    : null;
}

/** Validate and normalize the endpoint form. Total: never throws. */
export function validateEndpointSettings(raw: unknown): ValidateResult {
  const r = rec(raw);
  if (!r) return { ok: false, fieldErrors: { name: "Invalid form." } };
  const errors: EndpointFieldErrors = {};

  const name = typeof r.name === "string" ? r.name.trim() : "";
  if (name === "") errors.name = "Name is required.";
  else if (name.length > 100) errors.name = "Name must be 100 characters or fewer.";

  const source = r.source === "github" || r.source === "generic" ? r.source : null;
  if (!source) errors.source = "Choose GitHub or Generic.";

  const events: string[] = [];
  if (!Array.isArray(r.eventAllowlist)) {
    errors.eventAllowlist = "Choose at least one event.";
  } else {
    for (const e of r.eventAllowlist) {
      if (typeof e !== "string" || !EVENT_NAME.test(e)) {
        errors.eventAllowlist = "Event names are lowercase letters, digits, and _ . -";
        break;
      }
      if (!events.includes(e)) events.push(e);
    }
    if (!errors.eventAllowlist) {
      if (events.length === 0)
        errors.eventAllowlist = "Choose at least one event. Others are ignored.";
      else if (events.length > MAX_ENDPOINT_EVENTS) {
        errors.eventAllowlist = `At most ${MAX_ENDPOINT_EVENTS} events.`;
      }
    }
  }

  if (typeof r.ignoreBotAuthor !== "boolean") errors.ignoreBotAuthor = "Invalid value.";

  let headers: { signatureHeader: string; deliveryIdHeader: string } = {
    ...GITHUB_DEFAULT_HEADERS,
  };
  if (source === "generic") {
    const sig = typeof r.signatureHeader === "string" ? r.signatureHeader.trim().toLowerCase() : "";
    const del =
      typeof r.deliveryIdHeader === "string" ? r.deliveryIdHeader.trim().toLowerCase() : "";
    if (!HEADER_NAME.test(sig)) errors.signatureHeader = "Use 1–64 of a-z, 0-9 and -.";
    if (!HEADER_NAME.test(del)) errors.deliveryIdHeader = "Use 1–64 of a-z, 0-9 and -.";
    headers = { signatureHeader: sig, deliveryIdHeader: del };
  }

  if (Object.keys(errors).length > 0) return { ok: false, fieldErrors: errors };
  return {
    ok: true,
    value: {
      name,
      source: source!,
      eventAllowlist: events,
      ignoreBotAuthor: r.ignoreBotAuthor as boolean,
      ...headers,
    },
  };
}

function invalidInput(fieldErrors: EndpointFieldErrors): EndpointFailure {
  return { ok: false, code: "INVALID_INPUT", message: "Fix the highlighted fields.", fieldErrors };
}
const invalidId = (): EndpointFailure => ({
  ok: false,
  code: "INVALID_ID",
  message: "Unknown endpoint.",
});
const dbError = (message: string): EndpointFailure => ({
  ok: false,
  code: "DATABASE_ERROR",
  message,
});

function idOf(raw: unknown): string | null {
  return typeof raw === "string" && UUID.test(raw.trim()) ? raw.trim() : null;
}

const toToken = (b: Uint8Array) => Buffer.from(b).toString("base64url");
const toSecret = (b: Uint8Array) => Buffer.from(b).toString("hex");

export async function resolveCreateEndpoint(
  raw: unknown,
  deps: {
    randomBytes: RandomBytes;
    create: (input: WebhookEndpointCreateInput) => Promise<string>;
  },
): Promise<CreateEndpointResult> {
  const v = validateEndpointSettings(raw);
  if (!v.ok) return invalidInput(v.fieldErrors);
  const urlToken = toToken(deps.randomBytes(32));
  const secret = toSecret(deps.randomBytes(32));
  try {
    const id = await deps.create({ ...v.value, urlToken, secret });
    return { ok: true, id, urlToken, secret };
  } catch {
    return dbError("Could not create the endpoint. Try again.");
  }
}

export async function resolveUpdateEndpoint(
  rawId: unknown,
  raw: unknown,
  deps: {
    update: (id: string, input: WebhookEndpointSettings & { isEnabled: boolean }) => Promise<void>;
  },
): Promise<EndpointActionResult> {
  const id = idOf(rawId);
  if (!id) return invalidId();
  const v = validateEndpointSettings(raw);
  const enabled = rec(raw)?.isEnabled;
  if (!v.ok || typeof enabled !== "boolean") {
    return invalidInput({
      ...(v.ok ? {} : v.fieldErrors),
      ...(typeof enabled === "boolean" ? {} : { isEnabled: "Invalid value." }),
    });
  }
  // The source is fixed after creation; only settings are sent.
  const { name, eventAllowlist, ignoreBotAuthor, signatureHeader, deliveryIdHeader } = v.value;
  try {
    await deps.update(id, {
      name,
      eventAllowlist,
      ignoreBotAuthor,
      signatureHeader,
      deliveryIdHeader,
      isEnabled: enabled,
    });
    return { ok: true };
  } catch {
    return dbError("Could not save the endpoint. Try again.");
  }
}

export async function resolveRotateSecret(
  rawId: unknown,
  deps: { randomBytes: RandomBytes; rotate: (id: string, secret: string) => Promise<void> },
): Promise<RotateSecretResult> {
  const id = idOf(rawId);
  if (!id) return invalidId();
  const secret = toSecret(deps.randomBytes(32));
  try {
    await deps.rotate(id, secret);
    return { ok: true, secret };
  } catch {
    return dbError("Could not rotate the secret. The old secret is still active.");
  }
}

export async function resolveDeleteEndpoint(
  rawId: unknown,
  deps: { remove: (id: string) => Promise<void> },
): Promise<EndpointActionResult> {
  const id = idOf(rawId);
  if (!id) return invalidId();
  try {
    await deps.remove(id);
    return { ok: true };
  } catch {
    return dbError("Could not delete the endpoint. Try again.");
  }
}

export async function resolveToggleEndpoint(
  rawId: unknown,
  enabled: unknown,
  deps: { setEnabled: (id: string, enabled: boolean) => Promise<void> },
): Promise<EndpointActionResult> {
  const id = idOf(rawId);
  if (!id) return invalidId();
  if (typeof enabled !== "boolean") return invalidInput({ isEnabled: "Invalid value." });
  try {
    await deps.setEnabled(id, enabled);
    return { ok: true };
  } catch {
    return dbError("Could not update the endpoint. Try again.");
  }
}
