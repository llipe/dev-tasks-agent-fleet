import { describe, expect, it, vi } from "vitest";
import { dispatchDelivery, type DispatchDeps } from "@/lib/webhooks/dispatch";
import type { ReceivedDelivery } from "@/lib/webhooks/receive";
import type { ResolveResult } from "@/lib/domain/webhook-resolve";
import type { AgentRow, WebhookRuleRow } from "@/lib/supabase/types";

// Layer 1 — S-171 (#316): after a delivery is `received`, route it (S-170),
// resolve the matched rule (S-171) and record the outcome. Invocation is S-172:
// a resolved route is handed to `onResolved`, which this story leaves recording
// the delivery as `received` with reason `resolved`.

const delivery: ReceivedDelivery = {
  rowId: "row-1",
  endpointId: "ep-1",
  eventType: "issue_comment",
  payload: { sender: { login: "alice", type: "User" }, comment: { body: "security review" } },
};

function ruleRow(over: Partial<WebhookRuleRow> = {}): WebhookRuleRow {
  return {
    id: "rule-1",
    endpoint_id: "ep-1",
    position: 0,
    name: "",
    event_types: ["issue_comment"],
    conditions: [{ field: "comment.body", op: "equals", value: "security review" }],
    is_default: false,
    agent_id: "ag-1",
    repo_mode: "payload_field",
    repository_id: null,
    repo_payload_field: "repository.full_name",
    params: {},
    consecutive_failures: 0,
    auto_disable_threshold: 3,
    is_enabled: true,
    created_at: "",
    updated_at: "",
    ...over,
  };
}

function deps(over: Partial<DispatchDeps> = {}, resolved?: ResolveResult) {
  const d: DispatchDeps = {
    getEndpointRouting: vi.fn(async () => ({ ignore_bot_author: true })),
    getBotLogin: vi.fn(async () => "fleet[bot]"),
    getRules: vi.fn(async () => [ruleRow()]),
    resolve: vi.fn(
      async () =>
        resolved ??
        ({
          ok: true,
          agent: { id: "ag-1" } as AgentRow,
          repository: null,
          params: {},
          droppedKeys: [],
        } as ResolveResult),
    ),
    setRoute: vi.fn(async () => undefined),
    onResolved: vi.fn(async () => ({ status: 202, body: { received: true } })),
    ...over,
  };
  return d;
}

describe("dispatchDelivery", () => {
  it("records no_match (202) when nothing matches and there's no default (AC4)", async () => {
    const d = deps({
      getRules: vi.fn(async () => [
        ruleRow({ conditions: [{ field: "comment.body", op: "equals", value: "x" }] }),
      ]),
    });
    expect(await dispatchDelivery(d, delivery)).toEqual({
      status: 202,
      body: { skipped: true, reason: "no_match" },
    });
    expect(d.setRoute).toHaveBeenCalledWith("row-1", "no_match", null, null);
    expect(d.resolve).not.toHaveBeenCalled();
  });

  it("records the bot-author guard as ignored (AC7)", async () => {
    const bot = { ...delivery, payload: { sender: { login: "fleet[bot]", type: "Bot" } } };
    const d = deps();
    expect(await dispatchDelivery(d, bot)).toEqual({
      status: 202,
      body: { ignored: true, reason: "bot_author" },
    });
    expect(d.setRoute).toHaveBeenCalledWith("row-1", "ignored", "bot_author", null);
  });

  it.each(["agent_unavailable", "repository_not_allowed", "invalid_params"] as const)(
    "records route_rejected:%s with the matched rule (AC5)",
    async (reason) => {
      const d = deps({}, { ok: false, reason });
      expect(await dispatchDelivery(d, delivery)).toEqual({
        status: 202,
        body: { skipped: true, reason },
      });
      expect(d.setRoute).toHaveBeenCalledWith("row-1", "route_rejected", reason, "rule-1");
      expect(d.onResolved).not.toHaveBeenCalled();
    },
  );

  it("hands a resolved route to onResolved with the rule and records the match", async () => {
    const d = deps();
    const res = await dispatchDelivery(d, delivery);
    expect(res).toEqual({ status: 202, body: { received: true } });
    expect(d.onResolved).toHaveBeenCalledWith(
      expect.objectContaining({ id: "rule-1" }),
      expect.objectContaining({ ok: true }),
      delivery,
    );
    expect(d.setRoute).toHaveBeenCalledWith("row-1", "received", "resolved", "rule-1");
  });

  it("resolves the default rule when nothing else matches", async () => {
    const def = ruleRow({ id: "def", is_default: true, conditions: [], event_types: [] });
    const d = deps({
      getRules: vi.fn(async () => [ruleRow({ conditions: [{ field: "x", op: "exists" }] }), def]),
    });
    await dispatchDelivery(d, delivery);
    expect(d.resolve).toHaveBeenCalledWith(
      expect.objectContaining({ id: "def" }),
      delivery.payload,
    );
  });

  it("notes dropped undeclared keys in the reason", async () => {
    const d = deps(
      {},
      {
        ok: true,
        agent: { id: "ag-1" } as AgentRow,
        repository: null,
        params: {},
        droppedKeys: ["token", "x"],
      },
    );
    await dispatchDelivery(d, delivery);
    expect(d.setRoute).toHaveBeenCalledWith(
      "row-1",
      "received",
      "resolved; dropped undeclared params: token,x",
      "rule-1",
    );
  });

  it("caps the reason at 500 characters (R-3)", async () => {
    const keys = Array.from({ length: 200 }, (_, i) => `key${i}`);
    const d = deps(
      {},
      {
        ok: true,
        agent: { id: "ag-1" } as AgentRow,
        repository: null,
        params: {},
        droppedKeys: keys,
      },
    );
    await dispatchDelivery(d, delivery);
    const reason = vi.mocked(d.setRoute).mock.calls[0]![2]!;
    expect(reason.length).toBeLessThanOrEqual(500);
  });
});
