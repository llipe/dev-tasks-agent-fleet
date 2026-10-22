import { expect, test } from "@playwright/test";

import { countSchedules, resetSchedules } from "./fixtures/schedule-seed";
import { withDb } from "./fixtures/seed";

/**
 * E2E — new/edit schedule dialog (S-162, PRD AC13).
 *
 * Drives the schema-driven create dialog through the browser against the REAL
 * local stack: the agent/repo selects, the schema-derived param controls, the
 * cadence picker + the live "Next 3 runs" preview (sourced from the DB RPC),
 * and the create Server Action persisting a correct row.
 */

test.describe("schedules — new/edit dialog", () => {
  test.beforeEach(async () => {
    await resetSchedules();
  });

  test("create a daily schedule for the seeded agent (schema-driven form, AC13)", async ({
    page,
  }) => {
    expect(await countSchedules()).toBe(0);
    await page.goto("/schedules");

    await page
      .getByRole("button", { name: /New schedule/ })
      .first()
      .click();

    const dialog = page.getByRole("dialog", { name: "New schedule" });
    await expect(dialog).toBeVisible();

    // Pick the agent explicitly: the select is name-ordered and defaults to the
    // first enabled agent, which is "Code Review" since S-204 seeded it.
    await dialog.locator("#sch-agent").selectOption({ label: "Dependency Update" });

    // Repository is required for dependency-update — pick the first real option.
    await dialog.locator("#sch-repo").selectOption({ index: 1 });

    // Schema-driven param: fix_mode is a required enum (select). Choose audit_only.
    await dialog.getByLabel("Fix mode").selectOption("audit_only");

    // Cadence: Daily is the default kind; set 07:00 and keep America/Santiago.
    await dialog.getByRole("tab", { name: "Daily" }).click();

    // The live preview renders a human summary + next-3 from the authoritative RPC.
    await expect(dialog.getByText(/Runs daily at/)).toBeVisible();
    await expect(dialog.getByText("Next 3 runs")).toBeVisible();

    await dialog.getByRole("button", { name: "Create schedule" }).click();

    // The dialog closes and the DB has exactly one schedule with a seeded cursor.
    await expect
      .poll(async () => await countSchedules(), { message: "one schedule created" })
      .toBe(1);
    const row = await withDb((c) =>
      c
        .query(
          `select cadence_kind, next_run_at, state, (params->>'fix_mode') fix_mode
             from schedules order by created_at desc limit 1`,
        )
        .then((r) => r.rows[0]),
    );
    expect(row.cadence_kind).toBe("daily");
    expect(row.state).toBe("active");
    expect(row.fix_mode).toBe("audit_only");
    // next_run_at was seeded by the BEFORE-INSERT trigger (never null for active).
    expect(row.next_run_at).not.toBeNull();

    // The new row appears in the list on refresh (server-refetch-is-truth).
    await expect(page.getByText("Daily · 07:00")).toBeVisible();
  });

  test("creating an every-N-hours schedule persists the interval + a future cursor", async ({
    page,
  }) => {
    await page.goto("/schedules");
    await page
      .getByRole("button", { name: /New schedule/ })
      .first()
      .click();
    const dialog = page.getByRole("dialog", { name: "New schedule" });

    await dialog.locator("#sch-agent").selectOption({ label: "Dependency Update" });
    await dialog.locator("#sch-repo").selectOption({ index: 1 });
    await dialog.getByLabel("Fix mode").selectOption("audit_only");
    await dialog.getByRole("tab", { name: "Every N hours" }).click();
    await dialog.getByLabel(/Every N hours/).fill("6");

    await expect(dialog.getByText(/Runs every 6 hours/)).toBeVisible();
    await dialog.getByRole("button", { name: "Create schedule" }).click();

    await expect.poll(async () => await countSchedules()).toBe(1);
    const row = await withDb((c) =>
      c
        .query(
          `select cadence_kind, cadence_interval_hours, next_run_at
             from schedules order by created_at desc limit 1`,
        )
        .then((r) => r.rows[0]),
    );
    expect(row.cadence_kind).toBe("every_n_hours");
    expect(row.cadence_interval_hours).toBe(6);
    expect(new Date(row.next_run_at).getTime()).toBeGreaterThan(Date.now());
  });
});
