import { expect, test as setup } from "@playwright/test";

import { TEST_OPERATOR_EMAIL, TEST_OPERATOR_PASSWORD } from "./fixtures/auth";
import { OPERATOR_STORAGE_STATE } from "./fixtures/storage";

/**
 * Playwright auth setup project (S-119).
 *
 * The auth gate (S-117) is active in E2E, so every protected-route scenario
 * (invoke, live-tail, density, stale/artifact, edge-cases) needs an
 * authenticated browser context. This setup runs ONCE, signs the test operator
 * in through the REAL `/login` flow, and saves the resulting cookies to
 * `OPERATOR_STORAGE_STATE`. The chromium project loads that state, so the
 * existing specs stay unchanged and authenticated.
 *
 * The dedicated `auth.spec.ts` scenarios that must be UNAUTHENTICATED (the
 * redirect-to-login and invalid-credential cases) override this with an empty
 * storage state via `test.use`.
 */
setup("authenticate the test operator", async ({ page }) => {
  await page.goto("/login");

  await page.getByLabel("EMAIL", { exact: true }).fill(TEST_OPERATOR_EMAIL);
  await page.getByLabel("PASSWORD", { exact: true }).fill(TEST_OPERATOR_PASSWORD);
  await page.getByRole("button", { name: /^sign in$/i }).click();

  // A successful sign-in redirects off /login to the dashboard.
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
  await expect(page).toHaveURL(/\/$|\/agents|\/runs/);

  await page.context().storageState({ path: OPERATOR_STORAGE_STATE });
});
