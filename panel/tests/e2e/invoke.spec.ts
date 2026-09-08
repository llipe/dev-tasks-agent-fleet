import { expect, test } from "@playwright/test";

import { countRuns, getSeededIds, latestRunId, readRun, resetRuns } from "./fixtures/seed";

/**
 * E2E — invoke path (S-114, PRD AC12 + AC13).
 *
 * These scenarios drive the schema-driven invoke form (S-113) through the
 * browser and assert on the REAL database, never on internal function calls.
 * The AgentCore invocation is intercepted at the HTTP boundary by the stub
 * (`global-setup.ts`), so the panel runs its real credential branch + SDK
 * signing but no request reaches AWS.
 */

test.describe("invoke", () => {
  test.beforeEach(async () => {
    await resetRuns();
  });

  /**
   * Scenario 1 (PRD AC12): fill the form, submit, land on `/runs/[id]`; the
   * `runs` row exists with `status='queued'` (the stub accepts, so the run is
   * not marked failed_to_start) and all three timeout snapshots are non-null
   * (D1 / OQ3 — the snapshot the reaper relies on).
   */
  test("Scenario 1 — a valid invoke creates a queued run and navigates to its detail (AC12)", async ({
    page,
  }) => {
    const { agentSlug } = await getSeededIds();
    expect(await countRuns()).toBe(0);

    await page.goto(`/agents/${agentSlug}/invoke`);

    // The dialog renders from params_schema. Select a repository (required) and
    // leave fix_mode at its default (audit_only) — a valid submission.
    await page.locator("#repository").selectOption({ index: 1 });
    await expect(page.getByRole("button", { name: "Run" })).toBeEnabled();
    await page.getByRole("button", { name: "Run" }).click();

    // Navigation to /runs/[id]; the success state carries the run id.
    await page.waitForURL(/\/runs\/[0-9a-f-]{36}$/);
    const runId = page.url().split("/runs/")[1];

    // The DB is the source of truth: exactly one queued run with non-null
    // timeout snapshots.
    await expect
      .poll(async () => await countRuns(), { message: "exactly one run inserted" })
      .toBe(1);
    const row = await readRun(runId);
    expect(row).not.toBeNull();
    expect(row!.status).toBe("queued");
    expect(row!.max_runtime_seconds).not.toBeNull();
    expect(row!.grace_seconds).not.toBeNull();
    expect(row!.start_timeout_seconds).not.toBeNull();

    // The run-detail page rendered for this id (the outer run region names the
    // short run id; scope to the first match — RunSummary adds a nested region).
    await expect(page.getByRole("region", { name: /^Run [0-9A-F]/ }).first()).toBeVisible();
  });

  /**
   * Scenario 5 (PRD AC13): an invalid parameter submission is blocked and NO
   * `runs` row is created — the server is authoritative and rejects before any
   * insert. We force invalidity by removing the required repository selection
   * (the seeded agent requires a repository), which the client blocks with an
   * inline message and never POSTs; and, independently, by posting an invalid
   * param directly to the API to prove the server rejects with zero rows.
   */
  test("Scenario 5 — an invalid submission is blocked and writes no run (AC13)", async ({
    page,
    request,
  }) => {
    const { agentSlug } = await getSeededIds();
    expect(await countRuns()).toBe(0);

    await page.goto(`/agents/${agentSlug}/invoke`);

    // With no repository selected, Run is disabled (client guard) — the form
    // cannot even submit an incomplete invocation.
    await expect(page.getByRole("button", { name: "Run" })).toBeDisabled();

    // Server authority: POST an invalid fix_mode directly. The server must
    // reject (4xx) and insert nothing (validation precedes run_id + insert).
    const res = await request.post(`/api/agents/${agentSlug}/invoke`, {
      data: {
        repository_id: (await getSeededIds()).repositoryId,
        params: { fix_mode: "not_a_valid_enum_value" },
      },
    });
    expect(res.status()).toBeGreaterThanOrEqual(400);
    expect(res.status()).toBeLessThan(500);

    // The DB proves no run was created by the rejected invocation.
    expect(await countRuns()).toBe(0);
    expect(await latestRunId()).toBeNull();
  });
});
