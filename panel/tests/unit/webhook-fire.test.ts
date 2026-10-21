import { describe, expect, it, vi } from "vitest";
import { fireResolvedRoute, type FireDeps } from "@/lib/webhooks/fire";
import type { ResolveResult } from "@/lib/domain/webhook-resolve";
import type { ReceivedDelivery } from "@/lib/webhooks/receive";
import type { AgentRow, RepositoryRow, WebhookRuleRow } from "@/lib/supabase/types";

// Layer 1 — S-172/S-173: fire a resolved webhook route.
//  - guardrail first (S-173): a skip records `skipped:<reason>`, creates no run;
//  - otherwise invoke through the shared core with webhook:<endpoint>:<rule>,
//    record `fired` + run id (AC1), and report the result to G3 per rule.

const delivery: ReceivedDelivery = {
  rowId: "row-1",
  endpointId: "ep-1",
  eventType: "issue_comment",
  payload: {},
};
const rule = { id: "rule-1" } as WebhookRuleRow;
const resolved = {
  ok: true,
  agent: { id: "ag-1" } as AgentRow,
  repository: {
    id: "rp-1",
    installation_id: "in-1",
    full_name: "llipe/a",
    default_branch: "main",
  } as RepositoryRow,
  params: { mode: "audit_only" },
  droppedKeys: [],
} as Extract<ResolveResult, { ok: true }>;

function deps(
  result: Awaited<ReturnType<FireDeps["invoke"]>>,
  guard: string | null = null,
): FireDeps & { logs: unknown[]; order: string[] } {
  const logs: unknown[] = [];
  const order: string[] = [];
  return {
    logs,
    order,
    checkGuardrail: vi.fn(async () => {
      order.push("guard");
      return guard;
    }),
    invoke: vi.fn(async () => {
      order.push("invoke");
      return result;
    }),
    recordFired: vi.fn(async () => {
      order.push("fired");
    }),
    recordSkipped: vi.fn(async () => {
      order.push("skipped");
    }),
    recordRuleResult: vi.fn(async () => {
      order.push("g3");
    }),
    log: (f) => logs.push(f),
  };
}

describe("fireResolvedRoute", () => {
  it("checks the guardrail, invokes with webhook:<endpoint>:<rule>, records fired, then G3 success (AC1)", async () => {
    const d = deps({ ok: true, runId: "run-9" });
    expect(await fireResolvedRoute(d, rule, resolved, delivery)).toEqual({
      status: 202,
      body: { run_id: "run-9", status: "queued" },
    });
    expect(d.order).toEqual(["guard", "invoke", "fired", "g3"]);
    expect(d.checkGuardrail).toHaveBeenCalledWith("ag-1", "rp-1");
    expect(d.invoke).toHaveBeenCalledWith({
      agent: resolved.agent,
      repository: resolved.repository,
      params: { mode: "audit_only" },
      trigger: { triggerType: "webhook", triggeredBy: "webhook:ep-1:rule-1" },
    });
    expect(d.recordFired).toHaveBeenCalledWith("row-1", "run-9", "rule-1", null);
    expect(d.recordRuleResult).toHaveBeenCalledWith("rule-1", true, null);
  });

  it.each(["overlap", "open_pr", "concurrency_cap"])(
    "records skipped:%s and creates no run when the guardrail blocks (AC6)",
    async (reason) => {
      const d = deps({ ok: true, runId: "unused" }, reason);
      expect(await fireResolvedRoute(d, rule, resolved, delivery)).toEqual({
        status: 202,
        body: { skipped: true, reason },
      });
      expect(d.order).toEqual(["guard", "skipped"]);
      expect(d.recordSkipped).toHaveBeenCalledWith("row-1", reason, "rule-1");
      expect(d.invoke).not.toHaveBeenCalled();
      expect(d.recordRuleResult).not.toHaveBeenCalled();
    },
  );

  it("passes a null repository to the guardrail for a no-repository agent", async () => {
    const d = deps({ ok: true, runId: "run-9" });
    await fireResolvedRoute(d, rule, { ...resolved, repository: null }, delivery);
    expect(d.checkGuardrail).toHaveBeenCalledWith("ag-1", null);
  });

  it("keeps the dropped-keys note on the fired row", async () => {
    const d = deps({ ok: true, runId: "run-9" });
    await fireResolvedRoute(d, rule, { ...resolved, droppedKeys: ["token"] }, delivery);
    expect(d.recordFired).toHaveBeenCalledWith(
      "row-1",
      "run-9",
      "rule-1",
      "dropped undeclared params: token",
    );
  });

  it("records fired for a run that failed to start, counts a G3 failure, answers 202 (EC-22)", async () => {
    const d = deps({
      ok: false,
      runId: "run-9",
      errorCode: "INVOCATION_FAILED",
      status: 502,
      cause: new Error("x"),
      markFailed: false,
    });
    expect(await fireResolvedRoute(d, rule, resolved, delivery)).toEqual({
      status: 202,
      body: { run_id: "run-9", status: "failed_to_start" },
    });
    expect(d.recordFired).toHaveBeenCalledWith("row-1", "run-9", "rule-1", null);
    expect(d.recordRuleResult).toHaveBeenCalledWith("rule-1", false, "INVOCATION_FAILED");
    expect(JSON.stringify(d.logs)).not.toContain('"x"');
  });

  it("propagates an insert failure (route answers 5xx, nothing was invoked)", async () => {
    const d = deps({ ok: true, runId: "unused" });
    vi.mocked(d.invoke).mockRejectedValueOnce(new Error("insert failed"));
    await expect(fireResolvedRoute(d, rule, resolved, delivery)).rejects.toThrow("insert failed");
    expect(d.recordFired).not.toHaveBeenCalled();
  });
});
