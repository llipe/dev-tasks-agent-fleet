import { expect, test } from "@playwright/test";

import { getSeededIds } from "./fixtures/seed";
import { resetSchedules, seedSchedule } from "./fixtures/schedule-seed";

/**
 * E2E — agent-page scheduled indicator (S-164).
 *
 * The run-history header shows an "N schedules" link to the agent-filtered
 * schedules view; a zero-state when there are none. Link-only, no CRUD.
 */

test.describe("agent-page scheduled indicator", () => {
  test.beforeEach(async () => {
    await resetSchedules();
  });

  test("shows the schedule count and links to the agent-filtered schedules view", async ({
    page,
  }) => {
    const { agentSlug } = await getSeededIds();
    await seedSchedule();
    await seedSchedule({ cadenceKind: "weekly", cadenceWeekday: 2, cadenceHour: 5 });

    await page.goto(`/agents/${agentSlug}`);
    const link = page.getByRole("link", { name: "2 schedules" });
    await expect(link).toBeVisible();

    await link.click();
    await page.waitForURL(new RegExp(`/schedules\\?agent=${agentSlug}`));
    // The schedules screen renders its agent filter chip.
    await expect(page.getByText(`agent: ${agentSlug}`)).toBeVisible();
  });

  test("zero-state: 'No schedules' still links to the (empty) agent-filtered view", async ({
    page,
  }) => {
    const { agentSlug } = await getSeededIds();
    await page.goto(`/agents/${agentSlug}`);
    const link = page.getByRole("link", { name: "No schedules" });
    await expect(link).toBeVisible();
    await link.click();
    await page.waitForURL(new RegExp(`/schedules\\?agent=${agentSlug}`));
    await expect(page.getByText(`No schedules for ${agentSlug} yet.`)).toBeVisible();
  });
});
