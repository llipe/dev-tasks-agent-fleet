import { describe, expect, it } from "vitest";
import { toDeliveryView, DELIVERY_OUTCOME_META } from "@/lib/domain/delivery-view";
import type { WebhookDeliveryRow, WebhookOutcome } from "@/lib/supabase/types";

// Layer 1 — S-178 (#323): one delivery row → what the log shows. The point of
// the log is "why didn't a run happen?", so every outcome gets a label, a
// colour, and a plain-language reason; `fired` links to its run.

function row(over: Partial<WebhookDeliveryRow> = {}): WebhookDeliveryRow {
  return {
    id: "d1",
    endpoint_id: "e1",
    delivery_id: "72d3162e-cc78-11e3-81ab-4c9367dc0958",
    dedup_key: "id:72d3162e-cc78-11e3-81ab-4c9367dc0958",
    event_type: "issue_comment",
    outcome: "fired",
    matched_rule_id: "r1",
    run_id: "run-1",
    reason: null,
    received_at: "2026-10-20T15:00:00Z",
    created_at: "2026-10-20T15:00:00Z",
    updated_at: "2026-10-20T15:00:01Z",
    ...over,
  };
}
const rules = new Map([["r1", "comment → audit"]]);

describe("toDeliveryView", () => {
  it("gives every outcome a label and a colour token", () => {
    const outcomes: WebhookOutcome[] = [
      "received",
      "unauthorized",
      "duplicate",
      "ignored",
      "no_match",
      "route_rejected",
      "skipped",
      "fired",
    ];
    for (const o of outcomes) {
      const meta = DELIVERY_OUTCOME_META[o];
      expect(meta.label, o).toBeTruthy();
      expect(meta.color, o).toMatch(/^--/);
    }
  });

  it("links a fired delivery to its run and names the rule", () => {
    const v = toDeliveryView(row(), rules);
    expect(v).toMatchObject({
      outcomeLabel: "fired",
      color: "--st-ok",
      runHref: "/runs/run-1",
      ruleLabel: "comment → audit",
      verification: "verified",
      eventType: "issue_comment",
      deliveryId: "72d3162e-cc78-11e3-81ab-4c9367dc0958",
      reason: null,
    });
  });

  it("shows a fired delivery's dropped-params note as its reason", () => {
    expect(toDeliveryView(row({ reason: "dropped undeclared params: token" }), rules).reason).toBe(
      "dropped undeclared params: token",
    );
  });

  it("marks an unauthorized delivery as a failed signature with no rule or run", () => {
    const v = toDeliveryView(
      row({ outcome: "unauthorized", dedup_key: null, matched_rule_id: null, run_id: null }),
      rules,
    );
    expect(v).toMatchObject({
      verification: "signature failed",
      color: "--st-fail",
      runHref: null,
      ruleLabel: null,
    });
    expect(v.reason).toMatch(/signature/i);
  });

  it.each<[WebhookOutcome, string, RegExp]>([
    ["ignored", "event_not_allowed", /not in this endpoint.s events/i],
    ["ignored", "missing_event", /no event header/i],
    ["ignored", "invalid_json", /not valid json/i],
    ["ignored", "bot_author", /fleet.s own bot/i],
    ["no_match", "no_match", /no rule matched/i],
    ["skipped", "overlap", /already running/i],
    ["skipped", "open_pr", /open pull request/i],
    ["skipped", "concurrency_cap", /concurrency cap/i],
    ["route_rejected", "repository_not_allowed", /not a registered, enabled repository/i],
    ["route_rejected", "agent_unavailable", /agent is disabled or missing/i],
    ["route_rejected", "invalid_params", /parameters failed/i],
    ["duplicate", "", /already received/i],
    ["unauthorized", "header_missing", /no signature header/i],
    ["unauthorized", "header_malformed", /not in the sha256=<hex> form/i],
    ["unauthorized", "signature_mismatch", /doesn.t match this endpoint.s secret/i],
    ["unauthorized", "secret_not_configured", /no signing secret/i],
    ["unauthorized", "body_invalid", /body could not be read/i],
  ])("explains %s / %s", (outcome, reason, re) => {
    expect(
      toDeliveryView(row({ outcome, reason: reason || null, run_id: null }), rules).reason,
    ).toMatch(re);
  });

  it("passes an unknown reason through as plain text, capped", () => {
    const v = toDeliveryView(
      row({ outcome: "skipped", reason: "x".repeat(400), run_id: null }),
      rules,
    );
    expect(v.reason!.length).toBeLessThanOrEqual(200);
  });

  it("keeps untrusted header values as strings (the view renders them as text)", () => {
    const v = toDeliveryView(
      row({ event_type: "<img src=x onerror=alert(1)>", delivery_id: "<script>alert(1)</script>" }),
      rules,
    );
    expect(v.eventType).toBe("<img src=x onerror=alert(1)>");
    expect(v.deliveryId).toBe("<script>alert(1)</script>");
  });

  it("labels a missing event or delivery id, and a deleted rule", () => {
    const v = toDeliveryView(
      row({ event_type: null, delivery_id: null, matched_rule_id: "gone" }),
      rules,
    );
    expect(v).toMatchObject({ eventType: null, deliveryId: null, ruleLabel: "deleted rule" });
  });

  it("names an unnamed rule by its id prefix", () => {
    expect(toDeliveryView(row({ matched_rule_id: "r2" }), new Map([["r2", ""]])).ruleLabel).toBe(
      "rule r2",
    );
  });

  it("never links a run for a non-fired outcome", () => {
    expect(
      toDeliveryView(row({ outcome: "skipped", run_id: "run-1", reason: "overlap" }), rules)
        .runHref,
    ).toBeNull();
  });
});

import { decodeDeliveryCursor, encodeDeliveryCursor } from "@/lib/domain/delivery-view";

describe("delivery cursor (URL ?before=)", () => {
  const c = {
    createdAt: "2026-10-20T12:00:00.123456+00:00",
    id: "3f9b1c2e-8a4d-4c6b-9e1f-2a3b4c5d6e7f",
  };

  it("round-trips a cursor through a URL-safe string", () => {
    const s = encodeDeliveryCursor(c);
    expect(s).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(decodeDeliveryCursor(s)).toEqual(c);
  });

  it.each([
    undefined,
    "",
    "!!!",
    Buffer.from("not-a-cursor").toString("base64url"),
    Buffer.from(`2026-10-20T12:00:00+00:00|not-a-uuid`).toString("base64url"),
    Buffer.from(`yesterday|${c.id}`).toString("base64url"),
    Buffer.from(`2026-10-20T12:00:00+00:00,id.gt.0|${c.id}`).toString("base64url"),
    ["a", "b"],
  ])("rejects %j (filter injection included)", (v) => {
    expect(decodeDeliveryCursor(v as string | undefined)).toBeNull();
  });
});
