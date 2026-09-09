import { expect, test } from "@playwright/test";

import { TEST_OPERATOR_EMAIL, TEST_OPERATOR_PASSWORD } from "./fixtures/auth";

/**
 * E2E — authentication (S-119, PRD AC1/AC3/AC4/AC5/AC13).
 *
 * These scenarios run UNAUTHENTICATED (an empty storage state overrides the
 * chromium project's saved operator session), driving the real gate + login
 * flow through the browser against the real local stack.
 *
 * Coverage:
 *   - unauthenticated visit to a protected route → redirect to /login (AC1)
 *   - valid credentials → session established, redirected off /login (AC3)
 *   - a tampered off-origin `redirect` lands on `/`, never off-site (AC4)
 *   - invalid credentials → generic error in a role="alert" region (AC5)
 *   - the SHOW toggle reveals/re-masks the password (AC13)
 */

// Everything here is deliberately unauthenticated.
test.use({ storageState: { cookies: [], origins: [] } });

test.describe("auth", () => {
  test("unauthenticated visit to a protected route redirects to /login (AC1)", async ({ page }) => {
    await page.goto("/");
    await page.waitForURL(/\/login(\?|$)/);
    expect(new URL(page.url()).pathname).toBe("/login");
    // The original target is carried as the redirect param.
    expect(new URL(page.url()).searchParams.get("redirect")).toBe("/");
    // The form rendered outside the shell (no primary nav).
    await expect(page.getByRole("heading", { name: /^sign in$/i })).toBeVisible();
    await expect(page.getByRole("navigation", { name: /primary/i })).toHaveCount(0);
  });

  test("valid credentials sign in and redirect to the sanitized target (AC3)", async ({ page }) => {
    await page.goto("/login?redirect=%2Fagents%2Fdependency-update");
    await page.getByLabel("EMAIL", { exact: true }).fill(TEST_OPERATOR_EMAIL);
    await page.getByLabel("PASSWORD", { exact: true }).fill(TEST_OPERATOR_PASSWORD);
    await page.getByRole("button", { name: /^sign in$/i }).click();

    // Redirected to the sanitized same-origin target, no longer on /login.
    await page.waitForURL(/\/agents\/dependency-update$/);
    expect(new URL(page.url()).pathname).toBe("/agents/dependency-update");
  });

  test("a tampered off-origin redirect lands on / (AC4)", async ({ page }) => {
    await page.goto("/login?redirect=%2F%2Fevil.com");
    await page.getByLabel("EMAIL", { exact: true }).fill(TEST_OPERATOR_EMAIL);
    await page.getByLabel("PASSWORD", { exact: true }).fill(TEST_OPERATOR_PASSWORD);
    await page.getByRole("button", { name: /^sign in$/i }).click();

    // Must NOT navigate off-origin; the sanitized target is `/`.
    await page.waitForURL("**/");
    const url = new URL(page.url());
    expect(url.origin).toBe(new URL(page.url()).origin);
    expect(url.hostname).not.toBe("evil.com");
    expect(url.pathname).toBe("/");
  });

  test("invalid credentials show the generic error in a role=alert region (AC5)", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.getByLabel("EMAIL", { exact: true }).fill(TEST_OPERATOR_EMAIL);
    await page.getByLabel("PASSWORD", { exact: true }).fill("the-wrong-password");
    await page.getByRole("button", { name: /^sign in$/i }).click();

    // Our error region carries role="alert"; Next injects its own empty
    // route-announcer alert, so scope by the message text.
    const alert = page.getByRole("alert").filter({ hasText: /invalid email or password\./i });
    await expect(alert).toBeVisible();
    await expect(alert).toHaveText(/invalid email or password\./i);
    // Still on /login; the password field is not echoed (value cleared/empty).
    expect(new URL(page.url()).pathname).toBe("/login");
    await expect(page.getByLabel("PASSWORD", { exact: true })).toHaveValue("");
    // The button returns to enabled.
    await expect(page.getByRole("button", { name: /^sign in$/i })).toBeEnabled();
  });

  test("the SHOW toggle reveals and re-masks the password (AC13)", async ({ page }) => {
    await page.goto("/login");
    const password = page.getByLabel("PASSWORD", { exact: true });
    await password.fill("visible-check");
    await expect(password).toHaveAttribute("type", "password");

    await page.getByRole("button", { name: /show password/i }).click();
    await expect(page.getByLabel("PASSWORD", { exact: true })).toHaveAttribute("type", "text");

    await page.getByRole("button", { name: /hide password/i }).click();
    await expect(page.getByLabel("PASSWORD", { exact: true })).toHaveAttribute("type", "password");
  });

  test("redirect=/login does not loop — a valid login lands on / (edge)", async ({ page }) => {
    await page.goto("/login?redirect=%2Flogin");
    await page.getByLabel("EMAIL", { exact: true }).fill(TEST_OPERATOR_EMAIL);
    await page.getByLabel("PASSWORD", { exact: true }).fill(TEST_OPERATOR_PASSWORD);
    await page.getByRole("button", { name: /^sign in$/i }).click();
    await page.waitForURL("**/");
    expect(new URL(page.url()).pathname).toBe("/");
  });
});
