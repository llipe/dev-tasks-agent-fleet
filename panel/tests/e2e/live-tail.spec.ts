import { expect, test } from "@playwright/test";

import { resetRuns, seedArtifact, seedEvent, seedRun, setRunTerminal } from "./fixtures/seed";

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

  /**
   * SC-244-1 (issue #244, AC1). Open a `running` run, wait for the live log,
   * then drive it to terminal with artifacts (a `pull_request` and a 3-finding
   * `audit_report`). The SSE relay sends `closed` once the run is terminal; the
   * live viewer debounces 500ms and calls `router.refresh()` ONCE, so the
   * server-rendered summary re-reads WITHOUT a `page.reload()`.
   *
   * We assert the findings SUMMARY LINE ("3 findings"), not table rows: after
   * #245 the >10-row disclosure may be closed, but the summary line inside
   * `<summary>` is always visible regardless of the open/closed state.
   */
  test("Scenario 4 — live run reaches terminal: summary updates within 5s, no reload (#244 AC1)", async ({
    page,
  }) => {
    const runId = await seedRun({ status: "running", startedAgoSecs: 30 });

    await page.goto(`/runs/${runId}`);
    const log = page.locator('[data-sse-mount="run-log"]');
    await expect(log).toBeVisible();

    // While live, there is no terminal "Finished" clock value and no artifacts.
    const summary = page.getByRole("region", { name: /run summary/i });
    await expect(summary).toBeVisible();

    // Seed artifacts FIRST so the refreshed server render reads them, then drive
    // the run terminal. The audit_report carries 3 findings in its metadata.
    const auditMetadata = {
      total_findings: 3,
      by_bucket: {
        mechanical: [],
        manual: [],
        unscannable: [
          {
            tool: "gitleaks",
            bucket: "unscannable",
            rule_id: "generic-api-key",
            severity: "critical",
            file_path: "src/a.ts",
            line_start: 10,
            line_end: 10,
            message: "finding one",
            cwe_or_category: "generic-api-key",
          },
          {
            tool: "semgrep",
            bucket: "unscannable",
            rule_id: "rule-2",
            severity: "high",
            file_path: "src/b.ts",
            line_start: 20,
            line_end: 20,
            message: "finding two",
            cwe_or_category: "rule-2",
          },
          {
            tool: "trivy",
            bucket: "unscannable",
            rule_id: "rule-3",
            severity: "medium",
            file_path: "src/c.ts",
            line_start: 30,
            line_end: 30,
            message: "finding three",
            cwe_or_category: "rule-3",
          },
        ],
      },
      by_tool: { gitleaks: 1, semgrep: 1, trivy: 1 },
      by_severity: { critical: 1, high: 1, medium: 1 },
    };
    await seedArtifact(runId, "pull_request", "Bump lodash", "https://github.com/llipe/x/pull/42");
    await seedArtifact(runId, "audit_report", "Security scan findings", null, auditMetadata);
    // A succeeded run carrying an audit report WITH findings resolves to the
    // `needs_review` outcome; the panel renders its tag as "NEEDS REVIEW"
    // (lib/domain/run-row.ts → outcomeLabel). "success" is not a run_outcome
    // enum value — the type now rejects it, matching the DB enum.
    await setRunTerminal(runId, "succeeded", "needs_review");

    // Within 5s, WITHOUT reloading, the terminal summary appears: the succeeded
    // pill, the outcome tag, the Finished metadata (a real clock, not "—"), the
    // artifact pill, and the findings summary line.
    await expect(summary.getByText("succeeded")).toBeVisible({ timeout: 5_000 });
    await expect(summary.getByText("NEEDS REVIEW")).toBeVisible({ timeout: 5_000 });
    const finished = summary.locator("dd").filter({ hasText: /:/ });
    await expect(finished.first()).toBeVisible({ timeout: 5_000 });
    await expect(summary.getByRole("link", { name: /bump lodash/i })).toBeVisible({
      timeout: 5_000,
    });
    // The findings summary line — assert the line, not the table rows (the
    // disclosure state is irrelevant; 3 findings keeps it open, but the line is
    // always inside <summary> regardless).
    await expect(summary.getByText("3 findings")).toBeVisible({ timeout: 5_000 });
  });

  /**
   * SC-244-1b (issue #244, AC5 / D-03). The step + level filter selected while
   * the run is live is still applied after the terminal refresh swaps the live
   * viewer for the server-rendered `LogViewer`. `RunDetailLogSection` owns the
   * filter in `useState` and stays mounted across `router.refresh()`, so the
   * selection must persist.
   */
  test("Scenario 5 — the log-level filter persists across the terminal refresh (#244 AC5)", async ({
    page,
  }) => {
    const runId = await seedRun({ status: "running", startedAgoSecs: 30 });

    await page.goto(`/runs/${runId}`);
    const log = page.locator('[data-sse-mount="run-log"]');
    await expect(log).toBeVisible();

    // Insert one info and one error line, then select "Errors only".
    const tag = `f-${Date.now()}`;
    await seedEvent(runId, 1, `${tag}-info`, "info");
    await seedEvent(runId, 2, `${tag}-error`, "error");
    await expect(log.getByText(`${tag}-error`)).toBeVisible({ timeout: 15_000 });

    await page.getByLabel(/log level/i).selectOption("error");
    await expect(log.getByText(`${tag}-info`)).toBeHidden();
    await expect(log.getByText(`${tag}-error`)).toBeVisible();

    // Drive terminal → the viewer swaps to the terminal LogViewer after refresh.
    // `needs_review` is a valid run_outcome; "success" is not (type-rejected).
    await setRunTerminal(runId, "succeeded", "needs_review");
    await expect(
      page.getByRole("region", { name: /run summary/i }).getByText("succeeded"),
    ).toBeVisible({ timeout: 5_000 });

    // The filter is still "Errors only": the info line stays hidden, the error
    // line stays visible — no re-selection by the user.
    await expect(page.getByLabel(/log level/i)).toHaveValue("error");
    await expect(log.getByText(`${tag}-info`)).toBeHidden();
    await expect(log.getByText(`${tag}-error`)).toBeVisible();
  });
});
