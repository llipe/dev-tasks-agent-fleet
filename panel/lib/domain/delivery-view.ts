/**
 * S-178 (#323) — shape one `webhook_deliveries` row for the delivery log
 * (DESIGN.md §5.9.6). The log exists to answer "why didn't a run happen?", so
 * every outcome gets a label, a colour token and a plain-language reason, and
 * `fired` links to its run.
 *
 * `event_type`, `delivery_id` and unknown `reason` values come from the
 * sender's headers or our own pipeline and are UNTRUSTED. They are returned as
 * strings and the view renders them as text only, never as markup or links.
 */

import type { WebhookDeliveryRow, WebhookOutcome } from "@/lib/supabase/types";

export const DELIVERY_OUTCOME_META: Record<WebhookOutcome, { label: string; color: string }> = {
  received: { label: "received", color: "--muted" },
  unauthorized: { label: "unauthorized", color: "--st-fail" },
  duplicate: { label: "duplicate", color: "--muted" },
  ignored: { label: "ignored", color: "--faint" },
  no_match: { label: "no match", color: "--faint" },
  route_rejected: { label: "rejected", color: "--st-timeout" },
  skipped: { label: "skipped", color: "--st-timeout" },
  fired: { label: "fired", color: "--st-ok" },
};

/** Known reason codes → plain language. Anything else is shown as-is (capped). */
const REASONS: Record<string, string> = {
  event_not_allowed: "Event is not in this endpoint's events.",
  missing_event: "No event header on the delivery.",
  invalid_json: "Body is not valid JSON.",
  bot_author: "Sent by the fleet's own bot (self-trigger guard).",
  no_match: "No rule matched.",
  overlap: "A run is already running for this agent and repository.",
  open_pr: "The last run's open pull request is still waiting.",
  concurrency_cap: "The fleet-wide concurrency cap was reached.",
  repository_not_allowed: "The payload's repository is not a registered, enabled repository.",
  agent_unavailable: "The rule's agent is disabled or missing.",
  invalid_params: "The rule's parameters failed the agent's schema.",
  // signature verdicts (S-168)
  header_missing: "No signature header. Is a secret set on the sender?",
  header_malformed: "Signature header is not in the sha256=<hex> form.",
  signature_mismatch: "Signature doesn't match this endpoint's secret. Check or rotate it.",
  secret_not_configured: "This endpoint has no signing secret. Rotate it to set one.",
  body_invalid: "The body could not be read for verification.",
};

const DEFAULT_REASON: Partial<Record<WebhookOutcome, string>> = {
  unauthorized: "Signature missing or invalid. Check the secret on the sender.",
  duplicate: "Already received (same delivery id or body). No second run.",
  no_match: REASONS.no_match,
  received: "Received, still being processed.",
};

export const MAX_REASON_LENGTH = 200;

export interface DeliveryView {
  id: string;
  receivedAt: string;
  eventType: string | null;
  deliveryId: string | null;
  verification: "verified" | "signature failed";
  outcome: WebhookOutcome;
  outcomeLabel: string;
  color: string;
  reason: string | null;
  ruleLabel: string | null;
  runHref: string | null;
}

export function toDeliveryView(
  row: WebhookDeliveryRow,
  ruleNames: Map<string, string>,
): DeliveryView {
  const meta = DELIVERY_OUTCOME_META[row.outcome] ?? {
    label: String(row.outcome),
    color: "--muted",
  };
  const raw = row.reason?.trim() || null;
  const reason = raw
    ? (REASONS[raw] ?? raw.slice(0, MAX_REASON_LENGTH))
    : (DEFAULT_REASON[row.outcome] ?? null);

  let ruleLabel: string | null = null;
  if (row.matched_rule_id) {
    const name = ruleNames.get(row.matched_rule_id);
    ruleLabel =
      name === undefined ? "deleted rule" : name || `rule ${row.matched_rule_id.slice(0, 8)}`;
  }

  return {
    id: row.id,
    receivedAt: row.received_at ?? row.created_at,
    eventType: row.event_type,
    deliveryId: row.delivery_id,
    verification: row.outcome === "unauthorized" ? "signature failed" : "verified",
    outcome: row.outcome,
    outcomeLabel: meta.label,
    color: meta.color,
    reason,
    ruleLabel,
    runHref: row.outcome === "fired" && row.run_id ? `/runs/${row.run_id}` : null,
  };
}

// ---- keyset cursor for `?before=` (untrusted: validated strictly) ---------

const CURSOR_TS = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/;
const CURSOR_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function encodeDeliveryCursor(c: { createdAt: string; id: string }): string {
  return Buffer.from(`${c.createdAt}|${c.id}`).toString("base64url");
}

/** A cursor only if both halves are exactly a timestamp and a uuid, so nothing can reach the filter. */
export function decodeDeliveryCursor(
  raw: string | undefined,
): { createdAt: string; id: string } | null {
  if (
    typeof raw !== "string" ||
    raw.length === 0 ||
    raw.length > 200 ||
    !/^[A-Za-z0-9_-]+$/.test(raw)
  ) {
    return null;
  }
  const [createdAt, id, ...rest] = Buffer.from(raw, "base64url").toString("utf8").split("|");
  if (rest.length > 0 || !createdAt || !id || !CURSOR_TS.test(createdAt) || !CURSOR_ID.test(id))
    return null;
  return { createdAt, id };
}
