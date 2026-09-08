import { expect, test } from "@playwright/test";

import { resetRuns, seedArtifact, seedRun } from "./fixtures/seed";

/**
 * E2E — stale run + artifact on a failed run (S-114, PRD AC10 + AC14).
 *
 * Both scenarios assert what a human sees on the run-detail screen, backed by
 * seeded rows with explicit clocks. Neither depends on the reaper running — AC10
 * is precisely about the READ-TIME derivation (`v_runs.effective_status` / SD4)
 * telling the truth even when the reaper has not yet materialized it.
 */

test.describe("stale run and artifacts", () => {
  test.beforeEach(async () => {
    await resetRuns();
  });

  /**
   * Scenario 4 (PRD AC10): a `running` run whose clock is past its threshold
   * displays `timed_out` with the reaper NOT running. The raw column stays
   * `running`; the view derives `timed_out`, and the detail page (which derives
   * status through the shared `effectiveStatus`) shows the timed-out pill and a
   * terminal-state banner (DESIGN §8.3). A terminal effective status renders the
   * static log viewer, not the live one.
   */
  test("Scenario 4 — a stale running run reads timed_out at read time, reaper off (AC10)", async ({
    page,
  }) => {
    // started 3800s ago; threshold = max_runtime(3600) + grace(120) = 3720 <
    // 3800, so effective_status = timed_out even though status is still running.
    const runId = await seedRun({
      status: "running",
      startedAgoSecs: 3800,
      maxRuntimeSeconds: 3600,
      graceSeconds: 120,
      errorMessage: null,
    });

    await page.goto(`/runs/${runId}`);

    // The status pill reads "timed out" (status-meta label), derived at read
    // time — the reaper never ran in this test.
    await expect(page.getByText("timed out", { exact: true }).first()).toBeVisible();

    // A terminal effective status renders the server log viewer (with a
    // "load earlier" affordance surface), NOT the live-tail mount.
    await expect(page.locator('[data-sse-mount="run-log"]')).toHaveCount(0);
  });

  /**
   * Scenario 7 (PRD AC14): a seeded `failed` run that produced a `pull_request`
   * artifact shows the link. Artifacts render regardless of run status — a red
   * run still surfaces its PR.
   */
  test("Scenario 7 — a failed run still shows its pull_request artifact link (AC14)", async ({
    page,
  }) => {
    const runId = await seedRun({
      status: "failed",
      startedAgoSecs: 300,
      finishedAgoSecs: 10,
    });
    const prUrl = "https://github.com/llipe/memo-cli/pull/42";
    await seedArtifact(runId, "pull_request", "chore: bump lodash", prUrl);

    await page.goto(`/runs/${runId}`);

    // The failed pill is visible.
    await expect(page.getByText("failed", { exact: true }).first()).toBeVisible();

    // The artifact renders as a real https link (security guard #5 permits
    // https), pointing at the seeded PR url and opening in a new tab.
    const link = page.getByRole("link", { name: "chore: bump lodash" });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", prUrl);
    await expect(link).toHaveAttribute("rel", /noopener/);
  });
});
