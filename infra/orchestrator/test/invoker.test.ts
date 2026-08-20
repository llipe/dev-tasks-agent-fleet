import { describe, it, expect, vi } from "vitest";
import type { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";
import { stampAndInvoke, type InvokerDeps } from "../src/invoker.js";
import type { InvocationPayload } from "../src/types.js";

function mockDeps(overrides?: {
  invokeAgent?: (p: InvocationPayload) => Promise<void>;
}): InvokerDeps & { sendCalls: unknown[][] } {
  const sendCalls: unknown[][] = [];
  return {
    dynamoClient: {
      send: vi.fn(async (cmd: unknown) => {
        sendCalls.push([cmd]);
        return {};
      }),
    } as unknown as DynamoDBDocumentClient,
    invokeAgent: overrides?.invokeAgent ?? vi.fn(async () => {}),
    agentName: "dep-updater",
    sendCalls,
  };
}

describe("stampAndInvoke", () => {
  const payload: InvocationPayload = {
    session_id: "dep-updater-myorg-repo-20250127-100000",
    repo: "myorg/repo",
    params: { allow_fixes: true },
  };

  it("stamps running state before invoking", async () => {
    const deps = mockDeps();
    await stampAndInvoke(deps, payload);

    // First call should be UpdateItem for stamping
    expect(deps.dynamoClient.send).toHaveBeenCalledTimes(1);
    const firstCall = vi.mocked(deps.dynamoClient.send).mock.calls[0]?.[0] as
      { input: Record<string, unknown> } | undefined;
    expect(firstCall).toBeDefined();
    expect(firstCall?.input).toMatchObject({
      TableName: "agent-fleet-config",
      Key: { pk: "SUBJECT#myorg/repo", sk: "AGENT#dep-updater" },
      UpdateExpression: expect.stringContaining("last_status = :status"),
      ExpressionAttributeValues: expect.objectContaining({ ":status": "running" }),
    });
  });

  it("returns invoked status on success", async () => {
    const deps = mockDeps();
    const result = await stampAndInvoke(deps, payload);

    expect(result).toEqual({
      repo: "myorg/repo",
      sessionId: "dep-updater-myorg-repo-20250127-100000",
      status: "invoked",
    });
  });

  it("calls invokeAgent with the payload", async () => {
    const invokeAgent = vi.fn(async () => {});
    const deps = mockDeps({ invokeAgent });
    await stampAndInvoke(deps, payload);

    expect(invokeAgent).toHaveBeenCalledWith(payload);
  });

  it("stamps failed status when invoke throws", async () => {
    const invokeAgent = vi.fn(async () => {
      throw new Error("Network error");
    });
    const deps = mockDeps({ invokeAgent });
    const result = await stampAndInvoke(deps, payload);

    expect(result.status).toBe("failed");
    expect(result.error).toBe("Network error");

    // Should have 2 DynamoDB calls: stamp running + stamp failed
    expect(deps.dynamoClient.send).toHaveBeenCalledTimes(2);
    const secondCall = vi.mocked(deps.dynamoClient.send).mock.calls[1]?.[0] as
      { input: { ExpressionAttributeValues: Record<string, unknown> } } | undefined;
    expect(secondCall).toBeDefined();
    expect(secondCall?.input.ExpressionAttributeValues).toMatchObject({ ":status": "failed" });
  });

  it("returns failed result even if walk-back stamp fails", async () => {
    let callCount = 0;
    const dynamoClient = {
      send: vi.fn(async () => {
        callCount++;
        if (callCount === 2) throw new Error("DynamoDB unavailable");
        return {};
      }),
    } as unknown as DynamoDBDocumentClient;

    const invokeAgent = vi.fn(async () => {
      throw new Error("Throttled");
    });

    const deps: InvokerDeps = { dynamoClient, invokeAgent, agentName: "dep-updater" };
    const result = await stampAndInvoke(deps, payload);

    // Should not throw — walk-back failure is swallowed
    expect(result.status).toBe("failed");
    expect(result.error).toBe("Throttled");
  });
});
