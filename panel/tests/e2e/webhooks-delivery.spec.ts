import { expect, test } from "@playwright/test";

import { withDb } from "./fixtures/seed";
import {
  commentPayload,
  deliveriesFor,
  postDelivery,
  resetWebhooks,
  seedWebhookEndpoint,
  webhookRuns,
  E2E_REPO,
} from "./fixtures/webhook-seed";

/**
 * E2E — inbound deliveries end to end (S-179, #324). Real local Supabase,
 * the real `/api/webhooks/<token>` route on the production build, and the
 * AgentCore HTTP stub (global-setup) instead of AWS. Each scenario signs its
 * payload with the endpoint's secret the way GitHub does.
 *
 * Traceability (PRD §8):
 * | Scenario                                                            | AC        |
 * | ------------------------------------------------------------------- | --------- |
 * | signed → run (trigger_type=webhook), visible + linked in the log    | AC1, AC8  |
 * | unsigned / wrong signature → 401, unauthorized, no run              | AC2, AC9  |
 * | replayed delivery id → 200 no-op, still one run                     | AC2       |
 * | non-allowlisted event → 202 ignored; oversized body → 413; no run   | AC3       |
 * | rule #2 matches → rule #2 fires on the payload's repo; else no_match| AC4       |
 * | repo outside the allowlist → route_rejected, no run                 | AC5       |
 * | second delivery while the first run is active → skipped (G1)        | AC6       |
 * | event authored by the fleet's own bot → no run                      | AC7       |
 * | no secret or raw signature in any delivery record                   | AC9       |
 * The run_failed notification half of AC6 is covered at L2.5
 * (notify-sweep.test.ts) and the release-gate half of AC8 by S-175.
 */

const BOT = "dev-tasks-agent-fleet[bot]"; // supabase/seed.sql webhook.config bot_login

test.describe("webhooks — deliveries end to end", () => {
  test.beforeEach(async () => {
    await resetWebhooks();
  });
  test.afterAll(async () => {
    await resetWebhooks();
  });

  test("a signed delivery creates a webhook run, linked from the delivery log (AC1)", async ({
    page,
    request,
  }) => {
    const ep = await seedWebhookEndpoint({
      name: "signed",
      rules: [
        {
          name: "audit",
          events: ["issue_comment"],
          conditions: [{ field: "comment.body", op: "contains", value: "/audit" }],
        },
      ],
    });
    const res = await postDelivery(request, ep.token, {
      event: "issue_comment",
      deliveryId: "e2e-signed-1",
      payload: commentPayload("please /audit"),
      secret: ep.secret,
    });
    expect(res.status).toBe(202);
    expect(res.json).toMatchObject({ status: "queued" });

    const runs = await webhookRuns(ep.id);
    expect(runs).toHaveLength(1);
    expect(runs[0]).toMatchObject({
      trigger_type: "webhook",
      triggered_by: `webhook:${ep.id}:${ep.ruleIds[0]}`,
      repository: E2E_REPO,
    });
    expect(await deliveriesFor(ep.id)).toEqual([
      expect.objectContaining({
        outcome: "fired",
        run_id: runs[0]!.id,
        matched_rule_id: ep.ruleIds[0],
      }),
    ]);

    await page.goto(`/webhooks/${ep.id}`);
    const log = page.getByRole("table", { name: "Deliveries" });
    await expect(log.getByText("fired")).toBeVisible();
    await expect(log.getByText("e2e-signed-1")).toBeVisible();
    await log.getByRole("link", { name: /open run/i }).click();
    await expect(page).toHaveURL(new RegExp(`/runs/${runs[0]!.id}$`));

    await page.goto("/runs");
    // ...and in run history, as a normal row linking to the same run.
    await expect(
      page
        .getByRole("table", { name: "Run history" })
        .locator(`a[href="/runs/${runs[0]!.id}"]`)
        .first(),
    ).toBeVisible();
  });

  test("unsigned or wrongly signed → 401 recorded unauthorized, no run (AC2, AC9)", async ({
    request,
  }) => {
    const ep = await seedWebhookEndpoint({
      name: "unsigned",
      rules: [{ name: "any", events: ["issue_comment"], conditions: [] }],
    });
    const unsigned = await postDelivery(request, ep.token, {
      event: "issue_comment",
      deliveryId: "e2e-unsigned",
      payload: commentPayload("x"),
      secret: null,
    });
    const wrong = await postDelivery(request, ep.token, {
      event: "issue_comment",
      deliveryId: "e2e-wrong",
      payload: commentPayload("x"),
      secret: "0".repeat(64),
    });
    expect([unsigned.status, wrong.status]).toEqual([401, 401]);
    expect(await webhookRuns(ep.id)).toHaveLength(0);
    expect((await deliveriesFor(ep.id)).map((d) => d.outcome)).toEqual([
      "unauthorized",
      "unauthorized",
    ]);

    // AC9: no secret or signature material in any stored delivery column.
    const dump = await withDb((c) =>
      c
        .query(`select row_to_json(d)::text j from webhook_deliveries d where endpoint_id=$1`, [
          ep.id,
        ])
        .then((r) => r.rows.map((x) => x.j).join("\n")),
    );
    expect(dump).not.toContain(ep.secret);
    expect(dump).not.toMatch(/sha256=[0-9a-f]{64}/);
  });

  test("a replayed delivery id is a 200 no-op with no second run (AC2)", async ({ request }) => {
    const ep = await seedWebhookEndpoint({
      name: "replay",
      rules: [{ name: "any", events: ["issue_comment"], conditions: [] }],
    });
    const send = () =>
      postDelivery(request, ep.token, {
        event: "issue_comment",
        deliveryId: "e2e-replay",
        payload: commentPayload("x"),
        secret: ep.secret,
      });
    expect((await send()).status).toBe(202);
    const again = await send();
    expect(again).toEqual({ status: 200, json: { duplicate: true } });
    expect(await webhookRuns(ep.id)).toHaveLength(1);
  });

  test("a non-allowlisted event is ignored and an oversized body is 413, neither runs (AC3)", async ({
    request,
  }) => {
    const ep = await seedWebhookEndpoint({
      name: "ac3",
      rules: [{ name: "any", events: ["issue_comment"], conditions: [] }],
    });
    const ignored = await postDelivery(request, ep.token, {
      event: "push",
      deliveryId: "e2e-push",
      payload: commentPayload("x"),
      secret: ep.secret,
    });
    expect(ignored.status).toBe(202);
    const big = await request.post(`/api/webhooks/${ep.token}`, {
      data: "x".repeat(5 * 1024 * 1024 + 1),
      headers: {
        "content-type": "application/json",
        "x-github-event": "issue_comment",
        "x-github-delivery": "e2e-big",
      },
    });
    expect(big.status()).toBe(413);
    expect(await webhookRuns(ep.id)).toHaveLength(0);
    expect(await deliveriesFor(ep.id)).toEqual([
      expect.objectContaining({ outcome: "ignored", reason: "event_not_allowed" }),
    ]);
  });

  test("first match wins: rule #2 fires when only it matches; nothing matching is no_match (AC4)", async ({
    request,
  }) => {
    const ep = await seedWebhookEndpoint({
      name: "ac4",
      rules: [
        {
          name: "audit",
          events: ["issue_comment"],
          conditions: [{ field: "comment.body", op: "equals", value: "/audit" }],
        },
        {
          name: "security review",
          events: ["pull_request_review_comment"],
          conditions: [{ field: "comment.body", op: "equals", value: "security review" }],
        },
      ],
    });
    const hit = await postDelivery(request, ep.token, {
      event: "pull_request_review_comment",
      deliveryId: "e2e-ac4-hit",
      payload: commentPayload("security review"),
      secret: ep.secret,
    });
    expect(hit.status).toBe(202);
    const runs = await webhookRuns(ep.id);
    expect(runs).toEqual([
      expect.objectContaining({
        triggered_by: `webhook:${ep.id}:${ep.ruleIds[1]}`,
        repository: E2E_REPO,
      }),
    ]);

    // Let G1 clear before the next delivery for the same agent + repo.
    await withDb((c) =>
      c.query(
        `update runs set status='succeeded', outcome='no_findings', finished_at=now() where id=$1`,
        [runs[0]!.id],
      ),
    );
    const miss = await postDelivery(request, ep.token, {
      event: "issue_comment",
      deliveryId: "e2e-ac4-miss",
      payload: commentPayload("hello"),
      secret: ep.secret,
    });
    expect(miss).toEqual({ status: 202, json: { skipped: true, reason: "no_match" } });
    expect(await webhookRuns(ep.id)).toHaveLength(1);
  });

  test("a payload repository outside the allowlist is route_rejected, no run (AC5)", async ({
    request,
  }) => {
    const ep = await seedWebhookEndpoint({
      name: "ac5",
      rules: [{ name: "any", events: ["issue_comment"], conditions: [] }],
    });
    const res = await postDelivery(request, ep.token, {
      event: "issue_comment",
      deliveryId: "e2e-ac5",
      payload: commentPayload("x", { repository: { full_name: "someone-else/not-registered" } }),
      secret: ep.secret,
    });
    expect(res.status).toBe(202);
    expect(await webhookRuns(ep.id)).toHaveLength(0);
    expect(await deliveriesFor(ep.id)).toEqual([
      expect.objectContaining({ outcome: "route_rejected", reason: "repository_not_allowed" }),
    ]);
  });

  test("a second delivery while the first run is active is skipped by G1 (AC6)", async ({
    request,
  }) => {
    const ep = await seedWebhookEndpoint({
      name: "ac6",
      rules: [{ name: "any", events: ["issue_comment"], conditions: [] }],
    });
    const send = (id: string) =>
      postDelivery(request, ep.token, {
        event: "issue_comment",
        deliveryId: id,
        payload: commentPayload("x"),
        secret: ep.secret,
      });
    expect((await send("e2e-ac6-a")).json).toMatchObject({ status: "queued" });
    expect(await send("e2e-ac6-b")).toEqual({
      status: 202,
      json: { skipped: true, reason: "overlap" },
    });
    expect(await webhookRuns(ep.id)).toHaveLength(1);
    expect((await deliveriesFor(ep.id)).map((d) => [d.outcome, d.reason])).toEqual([
      ["fired", null],
      ["skipped", "overlap"],
    ]);
  });

  test("an event authored by the fleet's own bot never starts a run (AC7)", async ({ request }) => {
    const ep = await seedWebhookEndpoint({
      name: "ac7",
      rules: [{ name: "any", events: ["issue_comment"], conditions: [] }],
    });
    const res = await postDelivery(request, ep.token, {
      event: "issue_comment",
      deliveryId: "e2e-ac7",
      payload: commentPayload("/audit", { sender: { login: BOT, type: "Bot" } }),
      secret: ep.secret,
    });
    expect(res.status).toBe(202);
    expect(await webhookRuns(ep.id)).toHaveLength(0);
    expect(await deliveriesFor(ep.id)).toEqual([
      expect.objectContaining({ outcome: "ignored", reason: "bot_author" }),
    ]);
  });
});
