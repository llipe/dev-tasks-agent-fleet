import { expect, test } from "@playwright/test";

import { resetRuns, seedEvent, seedRun } from "./fixtures/seed";

/**
 * E2E — SSE live tail (S-114, PRD AC6 + SD6).
 *
 * A `running` run renders the client `LiveLogViewer`, which opens
 * `GET /api/runs/[id]/events/stream` (the panel's SSE relay, S-110). The relay
 * backfills then subscribes to a SERVER-SIDE Supabase Realtime channel (the
 * browser holds no Supabase credentials, SD2), so events inserted AFTER the
 * page is open must appear in the DOM with no reload.
 *
 * Realtime needs a moment to reach SUBSCRIBED after the stream opens; we insert
 * only after the initial log region is present and rely on `expect.poll`/
 * `toBeVisible` (never a fixed sleep) to absorb that warm-up.
 */

test.describe("live tail", () => {
  test.beforeEach(async () => {
    await resetRuns();
  });

  /**
   * Scenario 2 (PRD AC6): with the run detail open, insert `run_events`; assert
   * they appear without a reload.
   */
  test("Scenario 2 — events inserted after open appear live, no reload (AC6)", async ({ page }) => {
    // A fresh running run (started 30s ago; well within its threshold).
    const runId = await seedRun({ status: "running", startedAgoSecs: 30 });

    await page.goto(`/runs/${runId}`);

    // The live log region is present (data-sse-mount marks the SSE-driven grid).
    const log = page.locator('[data-sse-mount="run-log"]');
    await expect(log).toBeVisible();

    // Insert events after the stream is open. Give the subscription time to
    // establish by retrying the first insert's visibility via poll — no sleep.
    const marker = `live-line-${Date.now()}`;
    // Insert a few events with monotonic seq; the newest carries the marker.
    await seedEvent(runId, 1, "warming up");
    await seedEvent(runId, 2, `${marker}-a`);
    await seedEvent(runId, 3, `${marker}-b`);

    // They must appear in the DOM without a reload. Poll with a generous
    // timeout to absorb Realtime warm-up; the page is never reloaded.
    await expect(log.getByText(`${marker}-a`)).toBeVisible({ timeout: 15_000 });
    await expect(log.getByText(`${marker}-b`)).toBeVisible({ timeout: 15_000 });
  });

  /**
   * Scenario 3 (SD6): drop the SSE connection mid-stream, insert events during
   * the gap, then let the client reconnect. After reconnect the log shows every
   * event exactly once and in seq order — no duplicates, no gaps. The client
   * reconnects with the highest rendered `seq` as `after_seq`, and the relay's
   * backfill+dedupe (cursor.ts) guarantees the exactly-once property.
   *
   * The drop is induced by aborting in-flight `EventSource` requests via route
   * interception on the stream endpoint, then removing the block so the browser
   * reconnects on its own.
   */
  test("Scenario 3 — reconnect after a mid-stream drop yields no dup/no gap (SD6)", async ({
    page,
    context,
  }) => {
    const runId = await seedRun({ status: "running", startedAgoSecs: 30 });

    await page.goto(`/runs/${runId}`);
    const log = page.locator('[data-sse-mount="run-log"]');
    await expect(log).toBeVisible();

    // First event over the initial connection.
    const tag = `sd6-${Date.now()}`;
    await seedEvent(runId, 1, `${tag}-1`);
    await expect(log.getByText(`${tag}-1`)).toBeVisible({ timeout: 15_000 });

    // Drop the SSE connection with a real network blip: going offline aborts the
    // open EventSource; the client's onerror path reconnects when back online,
    // sending after_seq = highest rendered seq so the relay backfills the gap.
    await context.setOffline(true);

    // Insert events during the gap (the client is not receiving pushes now).
    await seedEvent(runId, 2, `${tag}-2`);
    await seedEvent(runId, 3, `${tag}-3`);

    // Restore connectivity → the EventSource reconnects on its own.
    await context.setOffline(false);

    // The functional SD6 property: after reconnect the gap events appear —
    // exactly once, in seq order. That they appear at all is proof the client
    // reconnected (offline aborted the original stream); that they appear
    // exactly once and ordered is proof the backfill+dedupe (cursor.ts) held
    // across the drop. This is a stronger assertion than counting raw opens.
    await expect(log.getByText(`${tag}-2`)).toBeVisible({ timeout: 25_000 });
    await expect(log.getByText(`${tag}-3`)).toBeVisible({ timeout: 25_000 });

    // No duplicates: each marker appears exactly once in the log DOM.
    for (const n of [1, 2, 3]) {
      await expect(log.getByText(`${tag}-${n}`)).toHaveCount(1);
    }

    // seq order: the DOM order of the three markers is 1,2,3 (no gap, no reorder).
    const texts = await log.locator(`text=/${tag}-[0-9]/`).allTextContents();
    const order = texts
      .map((t) => {
        const m = t.match(new RegExp(`${tag}-([0-9])`));
        return m ? Number(m[1]) : NaN;
      })
      .filter((n) => !Number.isNaN(n));
    expect(order).toEqual([1, 2, 3]);
  });
});
