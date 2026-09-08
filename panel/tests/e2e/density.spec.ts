import { expect, test } from "@playwright/test";

import { resetRuns, seedRun } from "./fixtures/seed";

/**
 * E2E — density toggle persistence (S-114, PRD AC9).
 *
 * The dashboard density variant (Rows / Cards / Ledger) is persisted to
 * `localStorage` under the closed vocabulary from S-107 (`panel.dashboard.density`).
 * Selecting a variant and reloading must preserve the choice — the reconciliation
 * happens in a mount effect (the hydration contract), so after reload the chosen
 * variant is active.
 */

test.describe("density toggle", () => {
  test.beforeEach(async () => {
    await resetRuns();
    // At least one run so the dashboard renders variant content, not the empty
    // state (the toggle is present regardless, but this keeps the screen real).
    await seedRun({
      status: "succeeded",
      startedAgoSecs: 120,
      finishedAgoSecs: 30,
      outcome: "no_vulnerabilities",
    });
  });

  test("Scenario 6 — the chosen density variant survives a reload (AC9)", async ({ page }) => {
    await page.goto("/");

    const group = page.getByRole("group", { name: "Density" });
    await expect(group).toBeVisible();

    // Default is "Rows" (dense). Switch to "Cards".
    const cards = group.getByRole("button", { name: "Cards" });
    await cards.click();
    await expect(cards).toHaveAttribute("aria-pressed", "true");

    // Persisted to localStorage under the S-107 key.
    await expect
      .poll(async () => await page.evaluate(() => localStorage.getItem("panel.dashboard.density")))
      .toBe("cards");

    // Reload — the selection must survive (reconciled from storage after mount).
    await page.reload();

    const groupAfter = page.getByRole("group", { name: "Density" });
    await expect(groupAfter.getByRole("button", { name: "Cards" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
