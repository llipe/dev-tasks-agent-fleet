import { expect, test } from "@playwright/test";

import {
  resetSchedules,
  seedNotification,
  unreadNotificationCount,
} from "./fixtures/schedule-seed";

/**
 * E2E — notifications feed + top-bar bell (S-163, PRD AC11).
 *
 * Drives the feed and the bell through the browser against the REAL local
 * stack: the grouped feed renders, clicking an item marks it read, the bell
 * badge reflects the unread count, and "Mark all read" clears it. Asserts on
 * the DB for the read-state mutations.
 */

test.describe("notifications — feed + bell", () => {
  test.beforeEach(async () => {
    await resetSchedules();
  });

  test("the feed renders notifications and the digest footer; the untrusted detail is text", async ({
    page,
  }) => {
    await seedNotification({
      kind: "run_failed",
      title: "security-analyst run failed on llipe/memo-cli",
      detail: "<b>AUDIT_FINDINGS</b>",
    });

    await page.goto("/notifications");
    await expect(page.getByRole("heading", { name: "Notifications" })).toBeVisible();
    await expect(page.getByText("security-analyst run failed on llipe/memo-cli")).toBeVisible();
    // Untrusted detail is rendered as text only — the literal angle brackets
    // appear and no <b> element is injected into the DOM.
    await expect(page.getByText("<b>AUDIT_FINDINGS</b>")).toBeVisible();
    await expect(page.locator(".content b")).toHaveCount(0);
    await expect(
      page.getByText("A daily email digest of these is sent at 08:00 America/Santiago."),
    ).toBeVisible();
  });

  test("clicking an unread item marks it read (feed → DB)", async ({ page }) => {
    await seedNotification({
      kind: "pr_opened",
      title: "dependency-update opened a PR",
      read: false,
    });
    expect(await unreadNotificationCount()).toBe(1);

    await page.goto("/notifications");
    await page.getByText("dependency-update opened a PR").click();

    await expect
      .poll(async () => await unreadNotificationCount(), { message: "marked read" })
      .toBe(0);
  });

  test("Mark all read clears every unread notification (AC11)", async ({ page }) => {
    await seedNotification({ kind: "run_failed", title: "run A failed", read: false });
    await seedNotification({
      kind: "schedule_auto_paused",
      title: "schedule auto-paused",
      read: false,
    });
    expect(await unreadNotificationCount()).toBe(2);

    await page.goto("/notifications");
    await page.getByRole("button", { name: "Mark all read" }).click();

    await expect.poll(async () => await unreadNotificationCount(), { message: "all read" }).toBe(0);
  });

  test("the top-bar bell shows the unread badge and opens the popover", async ({ page }) => {
    await seedNotification({ kind: "run_failed", title: "bell badge run failed", read: false });

    await page.goto("/schedules"); // the bell lives in the shell on every authed page
    const bell = page.getByRole("button", { name: /Notifications \(1 unread\)/ });
    await expect(bell).toBeVisible();

    await bell.click();
    const popover = page.getByRole("dialog", { name: "Notifications" });
    await expect(popover).toBeVisible();
    await expect(popover.getByText("bell badge run failed")).toBeVisible();
    // The popover footer links to the full feed.
    await expect(popover.getByRole("link", { name: /View all/ })).toBeVisible();
  });

  test("empty feed shows the Inbox empty state", async ({ page }) => {
    await page.goto("/notifications");
    await expect(page.getByText("No notifications.")).toBeVisible();
  });
});
