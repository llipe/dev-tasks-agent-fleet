import { describe, expect, it, vi } from "vitest";
import { invokeResolvedRun, type InvokeCoreDeps } from "@/lib/domain/invoke-resolved-run";

// Layer 1 — S-172 (#317): the shared invoke core (D-W6). Both the schedule fire
// route and the webhook handler call it, so it must keep the fire route's exact
// semantics: payload → buildRunInsert → insertQueuedRun → invokeAgentRuntime,
// and on an invoke throw → markRunFailedToStart (a mark failure is swallowed;
// the reaper is the backstop).

const agent = {
  id: "ag-1",
  version: "1.0",
  runtime_arn: "arn:aws:bedrock-agentcore:x",
  runtime_qualifier: "DEFAULT",
  requires_repository: true,
  max_runtime_seconds: 3600,
  grace_seconds: 60,
  start_timeout_seconds: 120,
};

function deps(over: Partial<InvokeCoreDeps> = {}): InvokeCoreDeps & { order: string[] } {
  const order: string[] = [];
  return {
    order,
    newRunId: () => "run-1",
    insertQueuedRun: vi.fn(async () => {
      order.push("insert");
    }),
    invokeAgentRuntime: vi.fn(async () => {
      order.push("invoke");
    }),
    markRunFailedToStart: vi.fn(async () => {
      order.push("mark");
    }),
    ...over,
  };
}

const input = {
  agent,
  repository: {
    id: "rp-1",
    installation_id: "in-1",
    full_name: "llipe/repo-a",
    default_branch: "trunk",
  },
  params: { mode: "audit_only" },
  trigger: { triggerType: "webhook", triggeredBy: "webhook:ep-1:rule-1" } as const,
};

describe("invokeResolvedRun", () => {
  it("inserts the queued run before invoking, with the trigger descriptor", async () => {
    const d = deps();
    const r = await invokeResolvedRun(d, input);
    expect(r).toEqual({ ok: true, runId: "run-1" });
    expect(d.order).toEqual(["insert", "invoke"]);
    expect(d.insertQueuedRun).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "run-1",
        agent_id: "ag-1",
        repository_id: "rp-1",
        installation_id: "in-1",
        trigger_type: "webhook",
        triggered_by: "webhook:ep-1:rule-1",
        status: "queued",
        params: { mode: "audit_only" },
      }),
    );
  });

  it("builds the repository payload with the repo default branch", async () => {
    const d = deps();
    await invokeResolvedRun(d, input);
    expect(d.invokeAgentRuntime).toHaveBeenCalledWith(
      { runtimeArn: agent.runtime_arn, runtimeQualifier: "DEFAULT" },
      {
        payload: {
          run_id: "run-1",
          repository_org: "llipe",
          repository_name: "repo-a",
          base_branch: "trunk",
          params: { mode: "audit_only" },
        },
      },
    );
  });

  it("lets an explicit base_branch param win over the repo default", async () => {
    const d = deps();
    await invokeResolvedRun(d, { ...input, params: { mode: "fix", base_branch: "release" } });
    expect(vi.mocked(d.invokeAgentRuntime).mock.calls[0]![1].payload).toMatchObject({
      base_branch: "release",
    });
  });

  it("builds the no-repository payload for an agent that needs none", async () => {
    const d = deps();
    await invokeResolvedRun(d, {
      ...input,
      agent: { ...agent, requires_repository: false },
      repository: null,
    });
    expect(vi.mocked(d.invokeAgentRuntime).mock.calls[0]![1].payload).toEqual({
      run_id: "run-1",
      base_branch: "main",
      params: { mode: "audit_only" },
    });
    expect(d.insertQueuedRun).toHaveBeenCalledWith(
      expect.objectContaining({ repository_id: null, installation_id: null }),
    );
  });

  it("on an invoke throw, marks failed_to_start and returns the typed failure", async () => {
    const err = Object.assign(new Error("boom"), { code: "CREDENTIALS_UNAVAILABLE", status: 500 });
    const d = deps({ invokeAgentRuntime: vi.fn(async () => Promise.reject(err)) });
    const r = await invokeResolvedRun(d, input);
    expect(r).toMatchObject({
      ok: false,
      runId: "run-1",
      errorCode: "CREDENTIALS_UNAVAILABLE",
      status: 500,
    });
    expect(d.markRunFailedToStart).toHaveBeenCalledWith("run-1", "CREDENTIALS_UNAVAILABLE", "boom");
  });

  it("defaults an untyped invoke failure to INVOCATION_FAILED / 502", async () => {
    const d = deps({ invokeAgentRuntime: vi.fn(async () => Promise.reject(new Error("x"))) });
    const r = await invokeResolvedRun(d, input);
    expect(r).toMatchObject({ ok: false, errorCode: "INVOCATION_FAILED", status: 502 });
  });

  it("swallows a markRunFailedToStart failure (the reaper is the backstop)", async () => {
    const d = deps({
      invokeAgentRuntime: vi.fn(async () => Promise.reject(new Error("x"))),
      markRunFailedToStart: vi.fn(async () => Promise.reject(new Error("db down"))),
    });
    const r = await invokeResolvedRun(d, input);
    expect(r).toMatchObject({ ok: false, runId: "run-1", markFailed: true });
  });

  it("calls onQueued after the insert and before the invoke", async () => {
    const d = deps();
    d.onQueued = (runId) => d.order.push(`queued:${runId}`);
    await invokeResolvedRun(d, input);
    expect(d.order).toEqual(["insert", "queued:run-1", "invoke"]);
  });

  it("propagates an insert failure without invoking (nothing to clean up)", async () => {
    const d = deps({
      insertQueuedRun: vi.fn(async () => Promise.reject(new Error("insert failed"))),
    });
    await expect(invokeResolvedRun(d, input)).rejects.toThrow("insert failed");
    expect(d.invokeAgentRuntime).not.toHaveBeenCalled();
  });
});
