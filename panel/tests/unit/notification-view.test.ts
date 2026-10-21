import { describe, expect, it } from "vitest";
import {
  groupNotifications,
  toNotificationViewModel,
  KIND_DOT_COLOR,
} from "@/lib/domain/notification-view";
import type { NotificationRow } from "@/lib/supabase/types";

// Layer 1 — S-163 (#275): the notifications feed view helper (pure).

const NOW = Date.UTC(2026, 9, 13, 15, 0, 0);

function notif(overrides: Partial<NotificationRow> = {}): NotificationRow {
  return {
    id: overrides.id ?? "n1",
    kind: overrides.kind ?? "run_failed",
    schedule_id: "schedule_id" in overrides ? overrides.schedule_id! : "s1",
    webhook_rule_id: "webhook_rule_id" in overrides ? overrides.webhook_rule_id! : null,
    agent_id: "a1",
    repository_id: "rp1",
    run_id: "run_id" in overrides ? overrides.run_id! : "r1",
    title: overrides.title ?? "security-analyst run failed",
    detail: overrides.detail ?? "INVOCATION_FAILED",
    data: {},
    read_at: overrides.read_at ?? null,
    emailed_at: null,
    created_at: overrides.created_at ?? new Date(NOW - 3600_000).toISOString(),
  };
}

describe("toNotificationViewModel", () => {
  it("maps kind → dot color and read_at → unread", () => {
    const vm = toNotificationViewModel(notif({ kind: "pr_opened", read_at: null }));
    expect(vm.dotColor).toBe(KIND_DOT_COLOR.pr_opened);
    expect(vm.unread).toBe(true);
    const read = toNotificationViewModel(notif({ read_at: new Date(NOW).toISOString() }));
    expect(read.unread).toBe(false);
  });

  it("derives links ONLY from structured ids, never the untrusted detail", () => {
    const vm = toNotificationViewModel(
      notif({ run_id: "r9", schedule_id: "s9", detail: "<a href=evil>x</a>" }),
    );
    expect(vm.links).toEqual([
      { label: "Open run ▸", href: "/runs/r9" },
      { label: "View schedule ▸", href: "/schedules" },
    ]);
    // the untrusted detail is carried verbatim as text, never turned into a link
    expect(vm.detail).toBe("<a href=evil>x</a>");
    expect(vm.links.some((l) => l.href.includes("evil"))).toBe(false);
  });

  it("omits a run link when there is no run_id (e.g. auto-pause)", () => {
    const vm = toNotificationViewModel(
      notif({ kind: "schedule_auto_paused", run_id: null, schedule_id: "s1" }),
    );
    expect(vm.links).toEqual([{ label: "View schedule ▸", href: "/schedules" }]);
  });
});

describe("webhook-origin notifications (S-173/S-174)", () => {
  it("gives every DB notification kind a dot color, including webhook_rule_auto_disabled", () => {
    expect(KIND_DOT_COLOR.webhook_rule_auto_disabled).toBe("--st-timeout");
    const vm = toNotificationViewModel(
      notif({
        kind: "webhook_rule_auto_disabled",
        run_id: null,
        schedule_id: null,
        webhook_rule_id: "w1",
      }),
    );
    expect(vm.dotColor).toBe("--st-timeout");
  });

  it("links a webhook run to the run and the webhooks page, never to schedules", () => {
    const vm = toNotificationViewModel(
      notif({ run_id: "r9", schedule_id: null, webhook_rule_id: "w1" }),
    );
    expect(vm.links).toEqual([
      { label: "Open run ▸", href: "/runs/r9" },
      { label: "View webhooks ▸", href: "/webhooks" },
    ]);
  });

  it("shows only the run link when the schedule or rule was deleted (#302)", () => {
    const vm = toNotificationViewModel(
      notif({ run_id: "r9", schedule_id: null, webhook_rule_id: null }),
    );
    expect(vm.links).toEqual([{ label: "Open run ▸", href: "/runs/r9" }]);
  });
});

describe("groupNotifications", () => {
  it("splits into Today / Earlier newest-first and omits empty groups", () => {
    const rows = [
      notif({ id: "today1", created_at: new Date(NOW - 2 * 3600_000).toISOString() }),
      notif({ id: "old1", created_at: new Date(NOW - 48 * 3600_000).toISOString() }),
    ];
    const groups = groupNotifications(rows, NOW);
    expect(groups.map((g) => g.label)).toEqual(["Today", "Earlier"]);
    expect(groups[0]!.items[0]!.id).toBe("today1");
    expect(groups[1]!.items[0]!.id).toBe("old1");
  });

  it("returns a single group when all rows are same-day", () => {
    const groups = groupNotifications([notif({ id: "t" })], NOW);
    expect(groups).toHaveLength(1);
    expect(groups[0]!.label).toBe("Today");
  });

  it("returns [] for an empty feed", () => {
    expect(groupNotifications([], NOW)).toEqual([]);
  });
});
