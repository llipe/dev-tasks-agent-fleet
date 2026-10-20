import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { randomBytes } from "node:crypto";
import { localRestConfig, probeLocalDb, withDb } from "./db";
import {
  createWebhookRule,
  deleteWebhookRule,
  getWebhookRulesForEndpoint,
  reorderWebhookRules,
  setWebhookRuleEnabled,
  updateWebhookRule,
} from "@/lib/supabase/queries";
import type { RuleWriteInput } from "@/lib/domain/webhook-rule-save";

// Layer 2.5 — S-177 (#322): rules persist with correct ordering.
//  - a new rule goes to the end (max position + 1);
//  - reorder renumbers every rule of the endpoint in ONE statement (the
//    `(endpoint_id, position)` unique is deferrable), so no intermediate state
//    can violate it, and a partial or foreign id list is rejected unchanged;
//  - update writes every editable field; delete leaves the rest in order;
//  - the reorder RPC is service_role-only.

const probe = await probeLocalDb();
const ANON_KEY = process.env.SUPABASE_ANON_KEY ?? process.env.ANON_KEY ?? "";
let client: SupabaseClient;
let endpointId = "";
let agentId = "";
let repoId = "";

function rule(name: string, over: Partial<RuleWriteInput> = {}): RuleWriteInput {
  return {
    name,
    eventTypes: ["issue_comment"],
    conditions: [{ field: "comment.body", op: "contains", value: "/" + name }],
    isDefault: false,
    agentId,
    repoMode: "payload_field",
    repositoryId: null,
    repoPayloadField: "repository.full_name",
    params: { static: { mode: "audit_only" }, from_payload: {} },
    autoDisableThreshold: 3,
    notifyOnSuccess: false,
    isEnabled: true,
    ...over,
  };
}

const order = async () =>
  (await getWebhookRulesForEndpoint(client, endpointId)).map((r) => [r.name, r.position]);

describe.skipIf(!probe.available)("panel Layer 2.5 — S-177 webhook rule admin", () => {
  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    const { url, serviceKey } = localRestConfig();
    client = createClient(url, serviceKey, { auth: { persistSession: false } });
    ({ agentId, repoId } = await withDb((c) =>
      c
        .query<{ agentId: string; repoId: string }>(
          `select (select id from agents where slug='security-analyst') "agentId",
                  (select id from repositories where is_enabled and archived_at is null order by full_name limit 1) "repoId"`,
        )
        .then((r) => r.rows[0]!),
    ));
  });

  beforeEach(async () => {
    endpointId = await withDb((c) =>
      c
        .query<{
          id: string;
        }>(
          `insert into webhook_endpoints (name, url_token, event_allowlist) values ('s177', $1, '{issue_comment}') returning id`,
          [randomBytes(32).toString("base64url")],
        )
        .then((r) => r.rows[0]!.id),
    );
  });

  afterEach(async () => {
    await withDb((c) => c.query(`delete from webhook_endpoints where id=$1`, [endpointId]));
  });

  it("appends new rules at the end", async () => {
    for (const n of ["a", "b", "c"]) await createWebhookRule(client, endpointId, rule(n));
    expect(await order()).toEqual([
      ["a", 0],
      ["b", 1],
      ["c", 2],
    ]);
  });

  it("reorders every rule in one transaction without tripping the position unique", async () => {
    const ids: Record<string, string> = {};
    for (const n of ["a", "b", "c"]) ids[n] = await createWebhookRule(client, endpointId, rule(n));
    await reorderWebhookRules(client, endpointId, [ids.c!, ids.a!, ids.b!]);
    expect(await order()).toEqual([
      ["c", 0],
      ["a", 1],
      ["b", 2],
    ]);
    await reorderWebhookRules(client, endpointId, [ids.b!, ids.c!, ids.a!]); // a full rotation
    expect(await order()).toEqual([
      ["b", 0],
      ["c", 1],
      ["a", 2],
    ]);
  });

  it("rejects a partial, duplicated or foreign id list and changes nothing", async () => {
    const ids: string[] = [];
    for (const n of ["a", "b"]) ids.push(await createWebhookRule(client, endpointId, rule(n)));
    const foreign = "99999999-9999-4999-8999-999999999999";
    for (const bad of [
      [ids[1]!],
      [ids[1]!, ids[1]!],
      [ids[1]!, foreign],
      [ids[1]!, ids[0]!, foreign],
    ]) {
      await expect(reorderWebhookRules(client, endpointId, bad)).rejects.toThrow();
    }
    expect(await order()).toEqual([
      ["a", 0],
      ["b", 1],
    ]);
  });

  it("updates every editable field", async () => {
    const id = await createWebhookRule(client, endpointId, rule("a"));
    await updateWebhookRule(
      client,
      id,
      rule("renamed", {
        repoMode: "fixed",
        repositoryId: repoId,
        repoPayloadField: null,
        params: { static: { mode: "fix" }, from_payload: { pr_number: "issue.number" } },
        autoDisableThreshold: 5,
        notifyOnSuccess: true,
        isEnabled: false,
      }),
    );
    const [r] = await getWebhookRulesForEndpoint(client, endpointId);
    expect(r).toMatchObject({
      name: "renamed",
      repo_mode: "fixed",
      repository_id: repoId,
      repo_payload_field: null,
      params: { static: { mode: "fix" }, from_payload: { pr_number: "issue.number" } },
      auto_disable_threshold: 5,
      notify_on_success: true,
      is_enabled: false,
      position: 0,
    });
  });

  it("re-enabling a rule resets its failure counter (G3), disabling does not", async () => {
    const id = await createWebhookRule(client, endpointId, rule("a"));
    await withDb((c) =>
      c.query(`update webhook_rules set consecutive_failures = 3, is_enabled = false where id=$1`, [
        id,
      ]),
    );
    await setWebhookRuleEnabled(client, id, true);
    const [r] = await getWebhookRulesForEndpoint(client, endpointId);
    expect(r).toMatchObject({ is_enabled: true, consecutive_failures: 0 });
  });

  it("deletes a rule and keeps the others in order", async () => {
    const ids: string[] = [];
    for (const n of ["a", "b", "c"]) ids.push(await createWebhookRule(client, endpointId, rule(n)));
    await deleteWebhookRule(client, ids[1]!);
    expect((await order()).map(([n]) => n)).toEqual(["a", "c"]);
    // A new rule still goes last.
    await createWebhookRule(client, endpointId, rule("d"));
    expect((await order()).map(([n]) => n)).toEqual(["a", "c", "d"]);
  });

  it("enforces one default rule per endpoint in the DB too", async () => {
    await createWebhookRule(
      client,
      endpointId,
      rule("d1", { isDefault: true, eventTypes: [], conditions: [] }),
    );
    await expect(
      createWebhookRule(
        client,
        endpointId,
        rule("d2", { isDefault: true, eventTypes: [], conditions: [] }),
      ),
    ).rejects.toThrow();
  });

  it("makes the rule RPCs service_role-only", async () => {
    const fns = [
      "public.webhook_reorder_rules(uuid,uuid[])",
      "public.webhook_create_rule(uuid,jsonb)",
    ];
    const rows = await withDb((c) =>
      c
        .query<{ fn: string; anon: boolean; authed: boolean; svc: boolean }>(
          `select f fn, has_function_privilege('anon', f, 'execute') anon,
                  has_function_privilege('authenticated', f, 'execute') authed,
                  has_function_privilege('service_role', f, 'execute') svc
             from unnest($1::text[]) f`,
          [fns],
        )
        .then((r) => r.rows),
    );
    for (const r of rows) expect(r, r.fn).toMatchObject({ anon: false, authed: false, svc: true });
    const { url } = localRestConfig();
    const anon = createClient(url, ANON_KEY, { auth: { persistSession: false } });
    const res = await anon.rpc("webhook_reorder_rules", {
      p_endpoint_id: endpointId,
      p_rule_ids: [],
    });
    expect(res.error).not.toBeNull();
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-177 webhook rule admin (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
