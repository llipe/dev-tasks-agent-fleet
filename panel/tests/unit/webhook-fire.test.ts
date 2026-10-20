import { describe, expect, it, vi } from "vitest";
import { fireResolvedRoute, type FireDeps } from "@/lib/webhooks/fire";
import type { ResolveResult } from "@/lib/domain/webhook-resolve";
import type { ReceivedDelivery } from "@/lib/webhooks/receive";
import type { AgentRow, RepositoryRow, WebhookRuleRow } from "@/lib/supabase/types";

// Layer 1 — S-172 (#317): a resolved webhook route is invoked through the shared
// core with the webhook trigger descriptor, and the delivery is recorded
// `fired` with the run id (AC1). An invoke that fails to start is still a
// visible failed_to_start run, so the delivery is still `fired` (EC-22).

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

function deps(result: Awaited<ReturnType<FireDeps["invoke"]>>): FireDeps & { logs: unknown[] } {
  const logs: unknown[] = [];
  return {
    logs,
    invoke: vi.fn(async () => result),
    recordFired: vi.fn(async () => undefined),
    log: (f) => logs.push(f),
  };
}

describe("fireResolvedRoute", () => {
  it("invokes with webhook:<endpoint>:<rule> and records fired + run id (AC1)", async () => {
    const d = deps({ ok: true, runId: "run-9" });
    expect(await fireResolvedRoute(d, rule, resolved, delivery)).toEqual({
      status: 202,
      body: { run_id: "run-9", status: "queued" },
    });
    expect(d.invoke).toHaveBeenCalledWith({
      agent: resolved.agent,
      repository: resolved.repository,
      params: { mode: "audit_only" },
      trigger: { triggerType: "webhook", triggeredBy: "webhook:ep-1:rule-1" },
    });
    expect(d.recordFired).toHaveBeenCalledWith("row-1", "run-9", "rule-1", null);
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

  it("still records fired when the run failed to start, and answers 202 (EC-22)", async () => {
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
    expect(JSON.stringify(d.logs)).not.toContain('"x"');
  });

  it("propagates an insert failure (route answers 5xx, nothing was invoked)", async () => {
    const d = deps({ ok: true, runId: "unused" });
    vi.mocked(d.invoke).mockRejectedValueOnce(new Error("insert failed"));
    await expect(fireResolvedRoute(d, rule, resolved, delivery)).rejects.toThrow("insert failed");
    expect(d.recordFired).not.toHaveBeenCalled();
  });
});
