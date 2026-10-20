import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DeliveryLog } from "@/components/webhooks/DeliveryLog";
import type { WebhookDeliveryRow, WebhookOutcome } from "@/lib/supabase/types";

/**
 * S-178 (#323) — the delivery log (Layer 2, jsdom), DESIGN.md §5.9.6.
 *  - every outcome renders with its label and reason;
 *  - fired links to /runs/<id>; nothing else links;
 *  - untrusted header/reason values containing markup render inert, as text;
 *  - empty state; "Older" link carries the keyset cursor; retention is stated.
 */

const NOW = Date.parse("2026-10-20T15:05:00Z");

function row(i: number, over: Partial<WebhookDeliveryRow> = {}): WebhookDeliveryRow {
  return {
    id: `0000000${i}-0000-4000-8000-000000000000`,
    endpoint_id: "e1",
    delivery_id: `gh-${i}`,
    dedup_key: `id:gh-${i}`,
    event_type: "issue_comment",
    outcome: "fired",
    matched_rule_id: "r1",
    run_id: `run-${i}`,
    reason: null,
    received_at: "2026-10-20T15:00:00Z",
    created_at: "2026-10-20T15:00:00Z",
    updated_at: "2026-10-20T15:00:01Z",
    ...over,
  };
}

function renderLog(rows: WebhookDeliveryRow[], olderHref: string | null = null) {
  return render(
    <DeliveryLog
      rows={rows}
      ruleNames={new Map([["r1", "comment → audit"]])}
      olderHref={olderHref}
      newestHref={null}
      retentionDays={30}
      nowMs={NOW}
    />,
  );
}

describe("DeliveryLog", () => {
  it("renders every outcome with its label", () => {
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
    renderLog(
      outcomes.map((o, i) =>
        row(i, {
          outcome: o,
          run_id: o === "fired" ? `run-${i}` : null,
          reason: o === "skipped" ? "overlap" : null,
        }),
      ),
    );
    const table = screen.getByRole("table", { name: /deliveries/i });
    const body = within(table).getAllByRole("row").slice(1);
    expect(body).toHaveLength(8);
    for (const label of [
      "received",
      "unauthorized",
      "duplicate",
      "ignored",
      "no match",
      "rejected",
      "skipped",
      "fired",
    ]) {
      expect(within(table).getByText(label)).toBeInTheDocument();
    }
    expect(within(table).getByText(/already running/i)).toBeInTheDocument();
    expect(within(table).getByText("signature failed")).toBeInTheDocument();
  });

  it("links only a fired delivery, to its run", () => {
    renderLog([row(1), row(2, { outcome: "skipped", reason: "overlap", run_id: "run-2" })]);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/runs/run-1");
    expect(screen.getAllByText("comment → audit")).toHaveLength(2);
  });

  it("renders markup in untrusted fields as inert text (security-negative)", () => {
    const { container } = renderLog([
      row(1, {
        outcome: "skipped",
        run_id: null,
        event_type: "<img src=x onerror=alert(1)>",
        delivery_id: "<script>alert(1)</script>",
        reason: '<a href="javascript:alert(1)">click</a>',
      }),
    ]);
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
    expect(screen.getByText('<a href="javascript:alert(1)">click</a>')).toBeInTheDocument();
    expect(container.querySelector("img, script, a[href^='javascript']")).toBeNull();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });

  it("shows relative and absolute times", () => {
    renderLog([row(1)]);
    expect(screen.getByText(/5 min ago/)).toBeInTheDocument();
    expect(screen.getByRole("table")).toHaveTextContent("2026-10-20");
  });

  it("shows an empty state that explains what lands here", () => {
    renderLog([]);
    expect(screen.getByRole("status")).toHaveTextContent(/no deliveries yet/i);
  });

  it("offers older pages through the cursor link and states the retention", () => {
    renderLog([row(1)], "/webhooks/e1?before=abc");
    expect(screen.getByRole("link", { name: /older/i })).toHaveAttribute(
      "href",
      "/webhooks/e1?before=abc",
    );
    expect(screen.getByText(/kept for 30 days/i)).toBeInTheDocument();
  });
});
