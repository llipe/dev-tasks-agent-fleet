import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { buildSessionId } from "@fleet/shared";
import type { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";

// We'll test the handler using a different approach — directly testing the
// composition of scope-reader, params-merge, invoker, and pool.
// The handler.ts itself depends on real AWS SDK clients, so we test the
// logic composition through a handler-like function.

import { queryEnabledSubjects, getAgentConfig } from "../src/scope-reader.js";
import { mergeParams } from "../src/params-merge.js";
import { stampAndInvoke, type InvokerDeps } from "../src/invoker.js";
import { pool, ORCHESTRATOR_CONCURRENCY } from "../src/pool.js";
import type { OrchestratorEvent, InvocationPayload, InvocationResult } from "../src/types.js";
import * as logger from "../src/logger.js";

// Minimal handler reimplementation for testing (same logic as handler.ts, without real SDK)
async function testHandler(
  event: OrchestratorEvent,
  deps: {
    docClient: DynamoDBDocumentClient;
    invokeAgent: (payload: InvocationPayload) => Promise<void>;
  },
): Promise<InvocationResult[]> {
  const { agent, scheduledAt } = event;
  const scheduledDate = new Date(scheduledAt);

  logger.setLogContext({ agent, function: "orchestrator" });
  logger.info("Orchestration started", { scheduledAt });

  const subjects = await queryEnabledSubjects(deps.docClient, agent);

  if (subjects.length === 0) {
    logger.info("No enabled repos found — nothing to invoke", { agent });
    logger.summary(0, 0, 0);
    return [];
  }

  const config = await getAgentConfig(deps.docClient, agent);
  const globalDefaults = config?.defaultParams ?? {};

  const payloads: InvocationPayload[] = subjects.map((entry) => ({
    session_id: buildSessionId(agent, entry.subjectId, scheduledDate),
    repo: entry.subjectId,
    params: mergeParams(globalDefaults, entry.params),
  }));

  const invokerDeps: InvokerDeps = {
    dynamoClient: deps.docClient,
    invokeAgent: deps.invokeAgent,
    agentName: agent,
  };

  const results = await pool(
    payloads,
    (payload) => stampAndInvoke(invokerDeps, payload),
    ORCHESTRATOR_CONCURRENCY,
  );

  const invoked = results.filter((r) => r.status === "invoked").length;
  const failed = results.filter((r) => r.status === "failed").length;

  for (const result of results) {
    if (result.status === "failed") {
      logger.error("Invocation failed", {
        session_id: result.sessionId,
        repo: result.repo,
        error: result.error,
      });
    } else {
      logger.info("Invocation succeeded", {
        session_id: result.sessionId,
        repo: result.repo,
      });
    }
  }

  logger.summary(invoked, 0, failed);
  return results;
}

function mockDocClient(responses: Record<string, unknown>[]) {
  let callIndex = 0;
  return {
    send: vi.fn(async () => {
      const response = responses[callIndex] ?? {};
      callIndex++;
      return response;
    }),
  } as unknown as DynamoDBDocumentClient;
}

function parseSummary(logOutput: string[]): { invoked: number; failed: number } {
  const line = logOutput.find((l) => l.includes("Orchestration complete"));
  expect(line).toBeDefined();
  return JSON.parse(line ?? "{}") as { invoked: number; failed: number };
}

describe("handler — integration (mocked)", () => {
  let originalStdoutWrite: typeof process.stdout.write;
  let logOutput: string[];

  beforeEach(() => {
    originalStdoutWrite = process.stdout.write;
    logOutput = [];
    process.stdout.write = vi.fn((chunk: string | Uint8Array) => {
      logOutput.push(typeof chunk === "string" ? chunk : new TextDecoder().decode(chunk));
      return true;
    }) as unknown as typeof process.stdout.write;
  });

  afterEach(() => {
    process.stdout.write = originalStdoutWrite;
  });

  it("fan-out over N repos: invokes all enabled repos", async () => {
    const docClient = mockDocClient([
      // Query for enabled subjects
      {
        Items: [
          { pk: "SUBJECT#org/repo-1", sk: "AGENT#dep-updater", enabled: true, params: {} },
          {
            pk: "SUBJECT#org/repo-2",
            sk: "AGENT#dep-updater",
            enabled: true,
            params: { max_fix_attempts: 5 },
          },
          { pk: "SUBJECT#org/repo-3", sk: "AGENT#dep-updater", enabled: true, params: {} },
        ],
      },
      // GetItem for CONFIG
      {
        Item: {
          pk: "CONFIG",
          sk: "AGENT#dep-updater",
          agent_name: "dep-updater",
          default_params: { allow_fixes: true },
        },
      },
      // UpdateCommand calls (stamp running x3)
      {},
      {},
      {},
    ]);

    const invokeAgent = vi.fn(async () => {});
    const results = await testHandler(
      { agent: "dep-updater", scheduledAt: "2025-01-27T10:00:00Z" },
      { docClient, invokeAgent },
    );

    expect(results).toHaveLength(3);
    expect(results.filter((r) => r.status === "invoked")).toHaveLength(3);
    expect(invokeAgent).toHaveBeenCalledTimes(3);

    // Verify params merge: repo-2 should have max_fix_attempts=5 overriding global
    const repo2Payload = results.find((r) => r.repo === "org/repo-2");
    expect(repo2Payload).toBeDefined();
    // Verify via the invokeAgent mock that repo-2 received merged params
    const calls = invokeAgent.mock.calls as unknown as [InvocationPayload][];
    const repo2Invocation = calls.find((c) => c[0].repo === "org/repo-2");
    expect(repo2Invocation).toBeDefined();
    expect(repo2Invocation?.[0].params).toEqual({
      allow_fixes: true,
      max_fix_attempts: 5,
    });

    // Summary log
    const summary = parseSummary(logOutput);
    expect(summary.invoked).toBe(3);
    expect(summary.failed).toBe(0);
  });

  it("one throwing invoke while rest proceed; failure walk-back", async () => {
    const docClient = mockDocClient([
      // Query
      {
        Items: [
          { pk: "SUBJECT#org/repo-1", sk: "AGENT#dep-updater", enabled: true, params: {} },
          { pk: "SUBJECT#org/repo-2", sk: "AGENT#dep-updater", enabled: true, params: {} },
          { pk: "SUBJECT#org/repo-3", sk: "AGENT#dep-updater", enabled: true, params: {} },
        ],
      },
      // GetItem CONFIG
      {
        Item: {
          pk: "CONFIG",
          sk: "AGENT#dep-updater",
          agent_name: "dep-updater",
          default_params: {},
        },
      },
      // Stamp running calls + stamp failed for repo-2
      {},
      {},
      {},
      {},
      {},
    ]);

    const invokeAgent = vi.fn(async (payload: InvocationPayload) => {
      if (payload.repo === "org/repo-2") throw new Error("Throttled");
    });

    const results = await testHandler(
      { agent: "dep-updater", scheduledAt: "2025-01-27T10:00:00Z" },
      { docClient, invokeAgent },
    );

    expect(results).toHaveLength(3);
    const invokedCount = results.filter((r) => r.status === "invoked").length;
    const failedCount = results.filter((r) => r.status === "failed").length;
    expect(invokedCount).toBe(2);
    expect(failedCount).toBe(1);

    const failedResult = results.find((r) => r.status === "failed");
    expect(failedResult).toBeDefined();
    expect(failedResult?.repo).toBe("org/repo-2");
    expect(failedResult?.error).toBe("Throttled");

    // Summary log
    const summary = parseSummary(logOutput);
    expect(summary.invoked).toBe(2);
    expect(summary.failed).toBe(1);
  });

  it("disabled repos excluded (filter at DynamoDB level)", async () => {
    // The GSI1 query already filters enabled=true, so only enabled repos appear
    const docClient = mockDocClient([
      {
        Items: [
          { pk: "SUBJECT#org/enabled-repo", sk: "AGENT#dep-updater", enabled: true, params: {} },
        ],
      },
      { Item: null },
      {}, // stamp
    ]);

    const invokeAgent = vi.fn(async () => {});
    const results = await testHandler(
      { agent: "dep-updater", scheduledAt: "2025-01-27T10:00:00Z" },
      { docClient, invokeAgent },
    );

    expect(results).toHaveLength(1);
    expect(invokeAgent).toHaveBeenCalledTimes(1);
    const calls = invokeAgent.mock.calls as unknown as [InvocationPayload][];
    expect(calls[0]?.[0].repo).toBe("org/enabled-repo");
  });

  it("scheduledAt retry produces identical session_id (determinism)", () => {
    const scheduledAt = "2025-01-27T10:00:00Z";
    const repo = "org/repo";
    const agent = "dep-updater";

    const id1 = buildSessionId(agent, repo, new Date(scheduledAt));
    const id2 = buildSessionId(agent, repo, new Date(scheduledAt));
    expect(id1).toBe(id2);
  });

  it("zero enabled repos produces zero invocations and a clean return", async () => {
    const docClient = mockDocClient([{ Items: [] }]);
    const invokeAgent = vi.fn(async () => {});

    const results = await testHandler(
      { agent: "dep-updater", scheduledAt: "2025-01-27T10:00:00Z" },
      { docClient, invokeAgent },
    );

    expect(results).toEqual([]);
    expect(invokeAgent).not.toHaveBeenCalled();

    const summary = parseSummary(logOutput);
    expect(summary.invoked).toBe(0);
    expect(summary.failed).toBe(0);
  });

  it("session_id per invocation is logged", async () => {
    const docClient = mockDocClient([
      {
        Items: [{ pk: "SUBJECT#org/repo-1", sk: "AGENT#dep-updater", enabled: true, params: {} }],
      },
      { Item: null },
      {},
    ]);

    const invokeAgent = vi.fn(async () => {});
    await testHandler(
      { agent: "dep-updater", scheduledAt: "2025-01-27T10:00:00Z" },
      { docClient, invokeAgent },
    );

    const successLog = logOutput.find((l) => l.includes("Invocation succeeded"));
    expect(successLog).toBeDefined();
    const logObj = JSON.parse(successLog ?? "{}") as { session_id?: string };
    expect(logObj.session_id).toBeDefined();
    expect((logObj.session_id ?? "").length).toBeGreaterThanOrEqual(33);
  });
});

describe("buildSessionId integration", () => {
  it("produces deterministic IDs for same inputs", () => {
    const d = new Date("2025-01-27T10:00:00Z");
    const id1 = buildSessionId("dep-updater", "myorg/repo", d);
    const id2 = buildSessionId("dep-updater", "myorg/repo", d);
    expect(id1).toBe(id2);
  });

  it("produces different IDs for different scheduledAt", () => {
    const d1 = new Date("2025-01-27T10:00:00Z");
    const d2 = new Date("2025-01-27T16:00:00Z");
    const id1 = buildSessionId("dep-updater", "myorg/repo", d1);
    const id2 = buildSessionId("dep-updater", "myorg/repo", d2);
    expect(id1).not.toBe(id2);
  });

  it("produces IDs at least 33 characters long", () => {
    const d = new Date("2025-01-27T10:00:00Z");
    const id = buildSessionId("ci", "web", d);
    expect(id.length).toBeGreaterThanOrEqual(33);
  });

  it("format matches expected pattern", () => {
    const d = new Date("2025-01-27T10:00:00Z");
    const id = buildSessionId("dep-updater", "myorg/repo", d);
    expect(id).toContain("dep-updater");
    expect(id).toContain("myorg-repo");
    expect(id).toContain("20250127");
  });
});
