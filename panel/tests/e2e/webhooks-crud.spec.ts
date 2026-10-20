import { expect, test } from "@playwright/test";

import { withDb } from "./fixtures/seed";
import { E2E_PREFIX, resetWebhooks } from "./fixtures/webhook-seed";

/**
 * E2E — /webhooks endpoint + rule CRUD (S-179, #324), against the real local
 * Supabase stack. Asserts on the DB, never on internals.
 *
 * Traceability (PRD §8):
 * | Scenario                                              | AC   |
 * | ----------------------------------------------------- | ---- |
 * | create endpoint; secret shown once, equals Vault, gone | AC8, AC9 |
 * | add two ordered rules, reorder, positions persist     | AC8, AC4 |
 * | a rule that can't resolve is flagged and not stored   | AC8, AC5 |
 * | delete a rule, then the endpoint (secret removed too)  | AC8  |
 * | /webhooks logged out → /login                          | AC8  |
 */

const NAME = `${E2E_PREFIX}crud`;

async function endpointRow() {
  return withDb((c) =>
    c
      .query<{
        id: string;
        secret: string | null;
      }>(
        `select id, webhook.read_endpoint_secret(id) secret from webhook_endpoints where name = $1`,
        [NAME],
      )
      .then((r) => r.rows[0] ?? null),
  );
}

test.describe("webhooks — endpoint + rule CRUD", () => {
  test.beforeEach(async () => {
    await resetWebhooks();
  });
  test.afterAll(async () => {
    await resetWebhooks();
  });

  test("create an endpoint, capture the secret once, add/reorder/delete rules, delete it", async ({
    page,
  }) => {
    await page.goto("/webhooks");
    await page
      .getByRole("button", { name: /new endpoint/i })
      .first()
      .click();
    const form = page.getByRole("dialog", { name: /new endpoint/i });
    await form.getByLabel(/^name/i).fill(NAME);
    await form.getByRole("checkbox", { name: "issue_comment", exact: true }).check();
    await form.getByRole("button", { name: /create endpoint/i }).click();

    const reveal = page.getByRole("dialog", { name: /copy the signing secret/i });
    const secret = await reveal.getByLabel(/signing secret/i).inputValue();
    expect(secret).toMatch(/^[0-9a-f]{64}$/);
    expect((await endpointRow())?.secret).toBe(secret); // stored in Vault
    await reveal.getByRole("button", { name: /i.ve stored it/i }).click();
    await page.reload();
    expect(await page.content()).not.toContain(secret); // never shown again (AC8/AC9)

    const ep = (await endpointRow())!;
    await page.getByRole("link", { name: NAME }).click();
    await expect(page).toHaveURL(new RegExp(`/webhooks/${ep.id}$`));

    for (const rule of ["first", "second"]) {
      await page
        .getByRole("button", { name: /add rule/i })
        .first()
        .click();
      const dlg = page.getByRole("dialog", { name: /new rule/i });
      await dlg.getByLabel(/^rule name/i).fill(rule);
      await dlg.getByRole("checkbox", { name: "issue_comment", exact: true }).check();
      await dlg.getByRole("button", { name: /add condition/i }).click();
      await dlg.getByLabel("Condition 1 field").fill("comment.body");
      await dlg.getByLabel("Condition 1 operator").selectOption("contains");
      await dlg.getByLabel("Condition 1 value").fill(`/${rule}`);
      await dlg.getByLabel(/^agent/i).selectOption({ label: "Security Analyst" });
      await dlg.getByRole("button", { name: /save rule/i }).click();
      await expect(dlg).toBeHidden();
    }

    // A rule that can't resolve is flagged before save and not stored.
    await page
      .getByRole("button", { name: /add rule/i })
      .first()
      .click();
    const bad = page.getByRole("dialog", { name: /new rule/i });
    await bad.getByLabel(/^rule name/i).fill("broken");
    await bad.getByRole("checkbox", { name: "issue_comment", exact: true }).check();
    await bad.getByLabel(/^agent/i).selectOption({ label: "Security Analyst" });
    await bad.getByLabel("Repository path").fill("repository..full_name");
    await bad.getByRole("button", { name: /save rule/i }).click();
    await expect(bad.getByText(/not a valid path/i)).toBeVisible();
    await bad.getByRole("button", { name: "Cancel" }).click();

    await page.getByRole("button", { name: "Move rule second up" }).click();
    await expect(
      page
        .getByRole("list", { name: /rules in match order/i })
        .getByRole("listitem")
        .first(),
    ).toContainText("second");
    const order = () =>
      withDb((c) =>
        c
          .query(
            `select name, position from webhook_rules where endpoint_id=$1 order by position`,
            [ep.id],
          )
          .then((r) => r.rows),
      );
    expect(await order()).toEqual([
      { name: "second", position: 0 },
      { name: "first", position: 1 },
    ]);

    await page.getByRole("button", { name: "Delete rule first" }).click();
    await page
      .getByRole("alertdialog", { name: /delete rule/i })
      .getByRole("button", { name: /delete rule/i })
      .click();
    await expect(page.getByRole("button", { name: "Delete rule first" })).toBeHidden();
    expect((await order()).map((r) => r.name)).toEqual(["second"]);

    await page.getByRole("link", { name: "Webhooks", exact: true }).first().click();
    await page.getByRole("button", { name: `Delete ${NAME}` }).click();
    await page
      .getByRole("alertdialog", { name: /delete endpoint/i })
      .getByRole("button", { name: /delete endpoint/i })
      .click();
    await expect(page.getByRole("link", { name: NAME })).toBeHidden();
    expect(await endpointRow()).toBeNull();
    const leftover = await withDb((c) =>
      c
        .query<{
          n: number;
        }>(`select count(*)::int n from vault.secrets where name = $1`, [
          `webhook_endpoint_${ep.id}`,
        ])
        .then((r) => r.rows[0]!.n),
    );
    expect(leftover).toBe(0);
  });

  test.describe("logged out", () => {
    test.use({ storageState: { cookies: [], origins: [] } });

    test("/webhooks and an endpoint page redirect to /login", async ({ page }) => {
      await page.goto("/webhooks");
      await expect(page).toHaveURL(/\/login/);
      await page.goto("/webhooks/3f9b1c2e-8a4d-4c6b-9e1f-2a3b4c5d6e7f");
      await expect(page).toHaveURL(/\/login/);
    });
  });
});
