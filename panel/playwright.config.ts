import { defineConfig, devices } from "@playwright/test";

import { AGENTCORE_STUB_ENDPOINT } from "./tests/e2e/fixtures/stub-port";
import { OPERATOR_STORAGE_STATE } from "./tests/e2e/fixtures/storage";

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

/**
 * Forward a Supabase env var to the spawned dev server ONLY when a non-empty
 * value is resolvable at config-load time (CI-fix for #170).
 *
 * Why "only when non-empty": Playwright merges `webServer.env` ON TOP OF the
 * inherited `process.env` for the child, with `webServer.env` winning. In CI
 * the values are present at config-load (exported to `$GITHUB_ENV` before the
 * E2E step), so forwarding is authoritative. Locally they are resolved by
 * `global-setup.ts` AFTER this config loads and written onto `process.env`,
 * which the child still inherits — so here we must NOT emit an empty string,
 * or we would clobber that later-set inherited value. Omitting the key leaves
 * inheritance intact.
 */
function forwardEnv(pairs: Record<string, string | undefined>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(pairs)) {
    if (value && value.length > 0) out[key] = value;
  }
  return out;
}

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
      // Auth setup (S-119): signs the test operator in through the real /login
      // flow ONCE and saves the session so the protected-route specs run
      // authenticated. Matches only the setup file.
      name: "setup",
      testMatch: /auth\.setup\.ts$/,
      use: {
        ...devices["Desktop Chrome"],
        ...(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {}),
      },
    },
    {
      name: "chromium",
      // The setup project runs first; the saved operator session authenticates
      // every scenario. Individual unauthenticated scenarios (auth.spec.ts)
      // override with an empty storageState via `test.use`.
      dependencies: ["setup"],
      testMatch: /.*\.spec\.ts$/,
      use: {
        ...devices["Desktop Chrome"],
        storageState: OPERATOR_STORAGE_STATE,
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
   * with a developer's `pnpm dev` on 3000. The AgentCore stub endpoint + fixed
   * test AWS credentials let the REAL local credential branch + SDK signing run
   * without needing SSO/a real profile (the stub ignores the signature).
   *
   * Supabase env forwarding (CI-fix for #170, run 34406811655):
   *   The auth clients (S-116) read the `NEXT_PUBLIC_*` anon pair; the data path
   *   reads the server-only names. Previously this config relied on the spawned
   *   dev server IMPLICITLY inheriting `process.env` (server-only names exported
   *   at the CI job level; NEXT_PUBLIC_* set only on global-setup's in-process
   *   `process.env`). That inheritance is not reliable for the NEXT_PUBLIC_*
   *   pair in CI, so `/login` 500'd with AuthConfigError and the setup project
   *   timed out. We now forward the vars EXPLICITLY via `webServer.env` and the
   *   CI workflow also exports the NEXT_PUBLIC_* pair to `$GITHUB_ENV`.
   *
   *   Timing note: Playwright constructs this `env` object when the config
   *   module LOADS — before `globalSetup` runs. So in CI the AUTHORITATIVE fix
   *   is the `$GITHUB_ENV` export (present at config-load); locally, global-setup
   *   also writes these onto `process.env`, and the spawned server still
   *   inherits `process.env`, so the forward + inheritance together cover both
   *   paths. The `?? "" ` fallbacks guarantee this never throws at config-load
   *   when a value is not yet resolved.
   *
   * The dev server is used deliberately rather than `next build && next start`:
   * these scenarios assert runtime behavior, and `next dev` exercises the same
   * runtime the scenarios drive. (Historical note: a production `next build`
   * once failed Next's route-export type validation on a non-standard export in
   * the S-110 SSE route (`parseAfterSeq`); S-115 moved that export into
   * `lib/sse/cursor.ts`, so `next build` is now green — but this suite still runs
   * against `next dev` because that is what the scenarios need.)
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
      // Supabase config forwarded EXPLICITLY (CI-fix for #170) so the dev server
      // no longer relies on implicit process.env inheritance. The auth clients
      // (S-116, #172) need the NEXT_PUBLIC_* client pair; prefer the publishable
      // name, fall back to the legacy anon name, then the server-only names so a
      // single resolved source populates all. Only non-empty values are
      // forwarded (see `forwardEnv`) so we never clobber a value that
      // global-setup sets onto process.env after this config loads (local path).
      // SD2: only the URL + publishable/anon client key are ever NEXT_PUBLIC_* —
      // the service-role key is NEVER given a NEXT_PUBLIC_ twin.
      ...forwardEnv({
        NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL ?? process.env.SUPABASE_URL,
        NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY:
          process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ??
          process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ??
          process.env.SUPABASE_ANON_KEY,
        // Legacy anon name still forwarded for one release (deprecated fallback).
        NEXT_PUBLIC_SUPABASE_ANON_KEY:
          process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? process.env.SUPABASE_ANON_KEY,
        // Server-only names forwarded explicitly too (data path — SD2 names).
        SUPABASE_URL: process.env.SUPABASE_URL,
        SUPABASE_ANON_KEY: process.env.SUPABASE_ANON_KEY,
        SUPABASE_SERVICE_ROLE_KEY: process.env.SUPABASE_SERVICE_ROLE_KEY,
      }),
    },
  },
});
