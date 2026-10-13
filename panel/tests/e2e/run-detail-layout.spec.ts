import { expect, test } from "@playwright/test";

import { resetRuns, seedArtifact, seedRun } from "./fixtures/seed";

/**
 * E2E — run-detail layout under a large audit report (issue #245).
 *
 * A large `audit_report` must not push the steps panel, log toolbar, and log
 * viewer off screen (/DESIGN.md §4.2 "no outer scroll", §5.3). The findings
 * table lives in a native `<details>`/`<summary>` (D-02): open by default at
 * ≤10 RENDERED rows (D-12), closed above, capped at 40vh when open, with the
 * log section floored at 240px (D-07).
 *
 * All scenarios run at 1280×720 (AC1). State is reset per scenario; each seeds a
 * TERMINAL run (so the static viewer renders, not the live tail) with an
 * `audit_report` carrying findings in `metadata` (seedArtifact's F-2 param).
 */

const VIEWPORT = { width: 1280, height: 720 };

/** Build an `audit_report` metadata payload with exactly `n` findings. */
function auditReport(n: number): Record<string, unknown> {
  const findings = Array.from({ length: n }, (_, i) => ({
    tool: "semgrep",
    bucket: "mechanical",
    rule_id: `rule-${i}`,
    severity: i % 3 === 0 ? "high" : "low",
    file_path: `src/file-${i}.ts`,
    line_start: i + 1,
    line_end: i + 1,
    message: `Finding number ${i} — a representative scanner message`,
    cwe_or_category: "CWE-000",
  }));
  return {
    total_findings: n,
    by_bucket: { mechanical: findings, manual: [], unscannable: [] },
    by_tool: { semgrep: n },
    by_severity: {},
  };
}

async function seedTerminalRunWithReport(n: number): Promise<string> {
  const runId = await seedRun({ status: "succeeded", startedAgoSecs: 300, finishedAgoSecs: 10 });
  await seedArtifact(runId, "audit_report", "Security scan findings", null, auditReport(n));
  return runId;
}

test.describe("run-detail layout with a large audit report (#245)", () => {
  test.beforeEach(async ({ page }) => {
    await resetRuns();
    await page.setViewportSize(VIEWPORT);
  });

  /**
   * SC-245-1: 50 findings, disclosure closed by default. The findings summary
   * line, log toolbar, and log viewer are all within the viewport, and there is
   * no outer page scroll.
   */
  test("SC-245-1 — 50 findings: closed disclosure, log section usable (AC1, AC3)", async ({
    page,
  }) => {
    const runId = await seedTerminalRunWithReport(50);
    await page.goto(`/runs/${runId}`);

    // The summary line is always visible, inside <summary>.
    await expect(page.getByText(/50 findings/).first()).toBeVisible();

    // Disclosure closed by default at > 10 rows.
    const details = page.locator("details").first();
    await expect(details).not.toHaveAttribute("open", /.*/);

    // The log toolbar (level filter) and the log viewer are present and in view.
    await expect(page.getByLabel(/log level/i)).toBeInViewport();
    await expect(page.getByRole("log", { name: /run log/i })).toBeInViewport();

    // No outer page scroll: the scrolling element is not taller than the viewport.
    const noOuterScroll = await page.evaluate(() => {
      const el = document.scrollingElement as HTMLElement;
      return el.scrollHeight <= window.innerHeight + 1;
    });
    expect(noOuterScroll).toBe(true);
  });

  /**
   * SC-245-1b: open the disclosure. The log viewer stays visible, the toolbar
   * stays in the viewport, and there is still no outer page scroll (the table
   * scrolls within its own 40vh-capped body).
   */
  test("SC-245-1b — opening the disclosure keeps the log section usable, no outer scroll (AC1, AC3)", async ({
    page,
  }) => {
    const runId = await seedTerminalRunWithReport(50);
    await page.goto(`/runs/${runId}`);

    const summary = page.locator("summary").first();
    await summary.click();
    const details = page.locator("details").first();
    await expect(details).toHaveAttribute("open", /.*/);

    // A visible log viewer with the table open proves the 240px floor holds.
    const logRegion = page.getByRole("log", { name: /run log/i });
    await expect(logRegion).toBeVisible();
    const box = await logRegion.boundingBox();
    expect(box).not.toBeNull();

    // Toolbar still in the viewport with the table open.
    await expect(page.getByLabel(/log level/i)).toBeInViewport();

    // Still no outer page scroll.
    const noOuterScroll = await page.evaluate(() => {
      const el = document.scrollingElement as HTMLElement;
      return el.scrollHeight <= window.innerHeight + 1;
    });
    expect(noOuterScroll).toBe(true);
  });

  /**
   * SC-245-2: keyboard operability. Focus the summary, toggle with Enter twice;
   * the native `open` attribute reflects each toggle.
   */
  test("SC-245-2 — keyboard toggles the disclosure (AC2)", async ({ page }) => {
    const runId = await seedTerminalRunWithReport(50);
    await page.goto(`/runs/${runId}`);

    const summary = page.locator("summary").first();
    const details = page.locator("details").first();
    await summary.focus();
    await expect(summary).toBeFocused();

    await page.keyboard.press("Enter");
    await expect(details).toHaveAttribute("open", /.*/);

    await page.keyboard.press("Enter");
    await expect(details).not.toHaveAttribute("open", /.*/);
  });

  /**
   * SC-245-3: 3 findings open by default; the summary line is visible with no
   * interaction.
   */
  test("SC-245-3 — ≤10 findings open by default (AC3)", async ({ page }) => {
    const runId = await seedTerminalRunWithReport(3);
    await page.goto(`/runs/${runId}`);

    const details = page.locator("details").first();
    await expect(details).toHaveAttribute("open", /.*/);
    await expect(page.getByText(/3 findings/).first()).toBeVisible();
  });

  /**
   * SC-245-3N: zero findings. The "No findings." empty state renders and there
   * is no `<details>` element at all.
   */
  test("SC-245-3N — zero findings: empty state, no disclosure (AC4)", async ({ page }) => {
    const runId = await seedTerminalRunWithReport(0);
    await page.goto(`/runs/${runId}`);

    await expect(page.getByText(/no findings/i)).toBeVisible();
    await expect(page.locator("details")).toHaveCount(0);
  });
});
