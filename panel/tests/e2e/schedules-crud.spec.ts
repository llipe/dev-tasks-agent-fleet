import { expect, test } from "@playwright/test";

import { countRuns, seedRun } from "./fixtures/seed";
import {
  countSchedules,
  readSchedule,
  resetSchedules,
  seedSchedule,
} from "./fixtures/schedule-seed";

/**
 * E2E — /schedules list + CRUD (S-161, PRD AC14).
 *
 * Drives the Schedules screen through the browser against the REAL local
 * Supabase stack: list rendering, the pause/resume toggle and delete confirm
 * Server Actions, and the auth boundary. Asserts on the DB, never on internals.
 */

test.describe("schedules — list + CRUD", () => {
  test.beforeEach(async () => {
    await resetSchedules();
  });

  test("the list renders seeded schedules with their state + cadence", async ({ page }) => {
    await seedSchedule({ cadenceKind: "daily", cadenceHour: 7, cadenceMinute: 0 });
    await seedSchedule({
      state: "paused",
      blockReason: "manual_pause",
      cadenceKind: "weekly",
      cadenceWeekday: 1,
      cadenceHour: 4,
    });

    await page.goto("/schedules");

    await expect(page.getByRole("heading", { name: "Schedules" })).toBeVisible();
    const table = page.getByRole("table", { name: "Schedules" });
    await expect(table).toBeVisible();
    await expect(page.getByText("Daily · 07:00")).toBeVisible();
    await expect(page.getByText("Weekly · Mon 04:00")).toBeVisible();
    // State pills: one active, one paused.
    await expect(page.getByText("active", { exact: true })).toBeVisible();
    await expect(page.getByText("paused", { exact: true })).toBeVisible();
  });

  test("pause then resume an active schedule (Server Action → DB)", async ({ page }) => {
    const id = await seedSchedule({
      state: "active",
      nextRunAtIso: new Date(Date.now() + 3600_000).toISOString(),
    });
    await page.goto("/schedules");

    await page.getByRole("button", { name: /Pause/ }).click();
    await expect
      .poll(async () => (await readSchedule(id))?.state, { message: "paused in DB" })
      .toBe("paused");

    await page.getByRole("button", { name: /Resume/ }).click();
    await expect
      .poll(async () => (await readSchedule(id))?.state, { message: "active in DB" })
      .toBe("active");
  });

  test("delete a schedule via the confirm dialog; its produced runs are kept (AC: on delete set null)", async ({
    page,
  }) => {
    const id = await seedSchedule();
    // A run that this schedule 'produced' — deleting the schedule must NOT delete it.
    await seedRun({
      status: "failed",
      outcome: "needs_review",
      startedAgoSecs: 120,
      finishedAgoSecs: 30,
    });
    expect(await countSchedules()).toBe(1);
    const runsBefore = await countRuns();

    await page.goto("/schedules");
    await page.getByRole("button", { name: "Delete schedule" }).click();

    // The alertdialog confirms, naming the destructive action.
    const dialog = page.getByRole("alertdialog", { name: "Delete schedule" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Delete schedule" }).click();

    await expect.poll(async () => await countSchedules(), { message: "schedule deleted" }).toBe(0);
    // History preserved: the produced run survives (on delete set null).
    expect(await countRuns()).toBe(runsBefore);
    await expect(page.getByText("No schedules yet.")).toBeVisible();
    void id;
  });

  test("the empty state renders the New schedule CTA when there are no schedules", async ({
    page,
  }) => {
    await page.goto("/schedules");
    await expect(page.getByText("No schedules yet.")).toBeVisible();
    await expect(page.getByRole("button", { name: /New schedule/ }).first()).toBeVisible();
  });
});

/**
 * AC14 — the Schedules screen is behind the auth gate. Unauthenticated: the
 * page redirects to /login, and the internal fire endpoint is NOT an open hole.
 */
test.describe("schedules — auth boundary (AC14)", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("unauthenticated /schedules redirects to /login", async ({ page }) => {
    await page.goto("/schedules");
    await page.waitForURL(/\/login(\?|$)/);
    expect(new URL(page.url()).pathname).toBe("/login");
    expect(new URL(page.url()).searchParams.get("redirect")).toBe("/schedules");
  });

  test("the internal fire endpoint rejects an unauthenticated POST with 401 (not an open invoke hole)", async ({
    request,
  }) => {
    const res = await request.post(
      "/api/internal/schedules/00000000-0000-0000-0000-000000000000/fire",
      { data: {} },
    );
    expect(res.status()).toBe(401);
  });
});
