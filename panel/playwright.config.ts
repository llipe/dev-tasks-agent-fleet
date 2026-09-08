import { defineConfig, devices } from "@playwright/test";

import { AGENTCORE_STUB_ENDPOINT } from "./tests/e2e/fixtures/stub-port";

/**
 * E2E config (S-114, #127). Playwright drives the panel end to end against the
 * REAL local Supabase stack (never a mock at the data layer) with AgentCore
 * stubbed at the HTTP boundary (`AWS_ENDPOINT_URL_BEDROCK_AGENTCORE` points at
 * the fixed-port stub started in `global-setup.ts`).
 *
 * Determinism is a hard requirement (story Business Rules):
 *   - `retries: 0` — a scenario that only passes on retry is a flake to fix,
 *     not to paper over.
 *   - `fullyParallel: false` + one worker — every scenario mutates the ONE
 *     shared local database (and toggles the reaper / inserts events with
 *     explicit clocks), so parallel scenarios would race. This mirrors the
 *     Vitest `integration` project's single-fork decision.
 *   - Seeded fixtures + explicit waits (`expect.poll` / `toBeVisible`), no
 *     machine-tuned sleeps; state is reset between scenarios by the specs.
 */

const isCI = process.env.CI === "true" || process.env.CI === "1";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: /.*\.spec\.ts$/,
  // Shared DB → serialize. One worker, no parallelism.
  fullyParallel: false,
  workers: 1,
  forbidOnly: isCI,
  retries: 0,
  reporter: isCI ? [["list"], ["html", { open: "never" }]] : "list",
  timeout: 30_000,
  expect: { timeout: 10_000 },

  globalSetup: "./tests/e2e/global-setup.ts",
  globalTeardown: "./tests/e2e/global-teardown.ts",

  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: isCI ? "retain-on-failure" : "on-first-retry",
    // Headed locally for the mandated manual pass (task 1.20); headless in CI.
    headless: isCI ? true : undefined,
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Default: Playwright's bundled chromium (CI installs it via
        // `playwright install --with-deps chromium`). Locally, when the bundled
        // browser cannot be provisioned, set `PW_CHANNEL=chrome` to run against
        // an installed Google Chrome — functionally equivalent for these
        // scenarios. Unset in CI so the pinned bundled build is used.
        ...(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {}),
      },
    },
  ],

  /**
   * Launch the panel under test on a dedicated port (3100) so it never collides
   * with a developer's `pnpm dev` on 3000. The Supabase env is populated into
   * `process.env` by `global-setup.ts` (which runs before this server starts)
   * and inherited here; we only add the AgentCore stub endpoint and fixed test
   * AWS credentials so the REAL local credential branch + SDK signing runs
   * without needing SSO/a real profile (the stub ignores the signature).
   *
   * The dev server is used deliberately rather than `next build && next start`:
   * a production `next build` runs Next's route-export type validation, which
   * currently rejects a non-standard export in the S-110 SSE route
   * (`parseAfterSeq`) — a pre-existing latent defect unrelated to S-114 (the
   * panel is a pre-deploy scaffold that has never been production-built; CI runs
   * typecheck + tests, not `next build`). Fixing that route export is product
   * code outside this test story; it is flagged to product-engineer as drift.
   * `next dev` exercises the same runtime behavior the scenarios assert.
   */
  webServer: {
    command: "pnpm exec next dev --port 3100",
    port: 3100,
    reuseExistingServer: !isCI,
    timeout: 180_000,
    stdout: "pipe",
    stderr: "pipe",
    env: {
      // AgentCore stubbed at the network boundary (Context Note).
      AWS_ENDPOINT_URL_BEDROCK_AGENTCORE: AGENTCORE_STUB_ENDPOINT,
      // Fixed test creds so `fromNodeProviderChain` resolves deterministically
      // (the stub never validates the signature — no real AWS call is made).
      AWS_ACCESS_KEY_ID: "test",
      AWS_SECRET_ACCESS_KEY: "test",
      AWS_REGION: "us-east-1",
    },
  },
});
