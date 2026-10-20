import { render, screen, fireEvent, act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Mock the actions module (pulls server-only chains) and next/navigation.
const markOne = vi.fn().mockResolvedValue({ ok: true });
const markAll = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(panel)/notifications/actions", () => ({
  markNotificationReadAction: (...a: unknown[]) => markOne(...a),
  markAllNotificationsReadAction: (...a: unknown[]) => markAll(...a),
}));
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

import { NotificationsFeed } from "@/components/notifications/NotificationsFeed";
import type { NotificationRow } from "@/lib/supabase/types";

/**
 * S-163 (#275) — NotificationsFeed component suite (Layer 2, jsdom), DESIGN.md
 * §5.8: grouped feed, unread treatment, untrusted detail as text only, mark-one
 * + mark-all, the digest footer, and the empty state.
 */

function notif(overrides: Partial<NotificationRow> = {}): NotificationRow {
  return {
    id: overrides.id ?? "n1",
    kind: overrides.kind ?? "run_failed",
    schedule_id: "s1",
    webhook_rule_id: null,
    agent_id: "a1",
    repository_id: "rp1",
    run_id: overrides.run_id ?? "r1",
    title: overrides.title ?? "security-analyst run failed",
    detail: overrides.detail ?? "INVOCATION_FAILED",
    data: {},
    read_at: overrides.read_at ?? null,
    emailed_at: null,
    created_at: overrides.created_at ?? new Date().toISOString(),
  };
}

afterEach(() => vi.clearAllMocks());

describe("NotificationsFeed", () => {
  it("renders the heading, stat line, and the digest footer", () => {
    render(<NotificationsFeed rows={[notif()]} unread={1} total={3} />);
    expect(screen.getByRole("heading", { name: "Notifications" })).toBeTruthy();
    expect(screen.getByText(/1 unread · 3 total · newest first/)).toBeTruthy();
    expect(
      screen.getByText("A daily email digest of these is sent at 08:00 America/Santiago."),
    ).toBeTruthy();
  });

  it("renders the untrusted detail as text (never as markup)", () => {
    render(
      <NotificationsFeed
        rows={[notif({ detail: "<img src=x onerror=1>" })]}
        unread={1}
        total={1}
      />,
    );
    expect(screen.getByText("<img src=x onerror=1>")).toBeTruthy();
    // no <img> element was injected
    expect(document.querySelector("img")).toBeNull();
  });

  it("clicking an unread item marks it read", async () => {
    render(<NotificationsFeed rows={[notif({ id: "n9" })]} unread={1} total={1} />);
    await act(async () => {
      fireEvent.click(screen.getByText("security-analyst run failed").closest("button")!);
    });
    expect(markOne).toHaveBeenCalledWith("n9");
  });

  it("Mark all read is disabled at zero unread and fires when unread>0", async () => {
    const { rerender } = render(<NotificationsFeed rows={[notif()]} unread={0} total={1} />);
    const btn = screen.getByRole("button", { name: "Mark all read" });
    expect(btn.getAttribute("aria-disabled")).toBe("true");

    rerender(<NotificationsFeed rows={[notif()]} unread={2} total={2} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Mark all read" }));
    });
    expect(markAll).toHaveBeenCalled();
  });

  it("shows the empty state when there are no notifications", () => {
    render(<NotificationsFeed rows={[]} unread={0} total={0} />);
    expect(screen.getByText("No notifications.")).toBeTruthy();
  });

  it("renders run/schedule links derived from ids", () => {
    render(<NotificationsFeed rows={[notif({ run_id: "r7" })]} unread={1} total={1} />);
    const runLink = screen.getByRole("link", { name: "Open run ▸" });
    expect(runLink.getAttribute("href")).toBe("/runs/r7");
    expect(screen.getByRole("link", { name: "View schedule ▸" }).getAttribute("href")).toBe(
      "/schedules",
    );
  });
});
