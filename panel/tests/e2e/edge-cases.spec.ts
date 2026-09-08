import { expect, test } from "@playwright/test";

import { resetRuns, seedRun, seedEvent, setSeededAgentEnabled } from "./fixtures/seed";

/**
 * E2E — edge-case matrix (S-114 task 1.16).
 *
 *  - empty database (no enabled agents) → dashboard empty state, not a crash;
 *  - a run with zero events → detail opens without a stream error;
 *  - two browser contexts tailing the same run → both receive the live line;
 *  - CI cold start is handled by `global-setup.ts` readiness polling (explicit
 *    wait, not a flake); this file asserts the app is reachable, closing the
 *    loop that the wait actually produced a ready system.
 */

test.describe("edge cases", () => {
  test.afterEach(async () => {
    // Always restore the seeded agent so no test leaks a disabled fleet.
    await setSeededAgentEnabled(true);
    await resetRuns();
  });

  test("empty fleet renders the dashboard 'no agents configured' state (EC-19)", async ({
    page,
  }) => {
    await resetRuns();
    await setSeededAgentEnabled(false);

    await page.goto("/");
    await expect(page.getByText(/no agents configured/i)).toBeVisible();
  });

  test("a run with zero events opens the detail page without a stream error", async ({ page }) => {
    await setSeededAgentEnabled(true);
    await resetRuns();
    // A terminal run with no events — the static log viewer shows the empty log
    // state; nothing throws.
    const runId = await seedRun({
      status: "succeeded",
      startedAgoSecs: 120,
      finishedAgoSecs: 30,
      outcome: "no_vulnerabilities",
    });

    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));

    await page.goto(`/runs/${runId}`);
    await expect(page.getByRole("region", { name: /^Run / })).toBeVisible();
    await expect(page.getByText(/no log events for this run/i)).toBeVisible();
    expect(errors, `no uncaught page errors: ${errors.join("; ")}`).toEqual([]);
  });

  test("two browser contexts tailing the same run both receive a live line", async ({
    browser,
  }) => {
    await setSeededAgentEnabled(true);
    await resetRuns();
    const runId = await seedRun({ status: "running", startedAgoSecs: 30 });

    const ctxA = await browser.newContext();
    const ctxB = await browser.newContext();
    const pageA = await ctxA.newPage();
    const pageB = await ctxB.newPage();
    try {
      await pageA.goto(`/runs/${runId}`);
      await pageB.goto(`/runs/${runId}`);
      const logA = pageA.locator('[data-sse-mount="run-log"]');
      const logB = pageB.locator('[data-sse-mount="run-log"]');
      await expect(logA).toBeVisible();
      await expect(logB).toBeVisible();

      const marker = `multi-${Date.now()}`;
      await seedEvent(runId, 1, marker);

      await expect(logA.getByText(marker)).toBeVisible({ timeout: 20_000 });
      await expect(logB.getByText(marker)).toBeVisible({ timeout: 20_000 });
    } finally {
      await ctxA.close();
      await ctxB.close();
    }
  });
});
