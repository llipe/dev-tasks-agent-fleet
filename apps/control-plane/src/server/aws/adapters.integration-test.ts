/**
 * Integration tests for AWS adapters with mocked SDK clients.
 *
 * Tests:
 * - Each adapter handles throttle-then-success (retries work)
 * - Validation errors are not retried
 * - No ScanCommand is ever sent
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mockClient } from "aws-sdk-client-mock";
import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import {
  ResourceGroupsTaggingAPIClient,
  GetResourcesCommand,
} from "@aws-sdk/client-resource-groups-tagging-api";
import {
  CloudWatchLogsClient,
  StartQueryCommand,
  GetQueryResultsCommand,
  StopQueryCommand,
  FilterLogEventsCommand,
} from "@aws-sdk/client-cloudwatch-logs";
import { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";
import { QueryCommand, GetCommand, UpdateCommand } from "@aws-sdk/lib-dynamodb";

import {
  listManagedAgents,
  clearInventoryCache,
  _setClient as setTaggingClient,
} from "./tagging-adapter.js";
import { executeInsightsQuery, _setClient as setLogsClient } from "./logs-insights-adapter.js";
import { filterLogsBySessionId, _setClient as setFilterLogsClient } from "./filter-logs-adapter.js";
import { _setDocClient } from "./dynamodb-client.js";
import {
  listAgentSubjects,
  getSubjectAgent,
  listSubjects,
  setSubjectEnabled,
} from "../repository/scope-repository.js";

describe("Tagging adapter — throttle then success", () => {
  const taggingMock = mockClient(ResourceGroupsTaggingAPIClient);

  beforeEach(() => {
    taggingMock.reset();
    clearInventoryCache();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("retries on ThrottlingException and succeeds", async () => {
    const throttleError = Object.assign(new Error("Rate exceeded"), {
      name: "ThrottlingException",
      $metadata: { httpStatusCode: 429 },
    });

    taggingMock
      .on(GetResourcesCommand)
      .rejectsOnce(throttleError)
      .resolves({
        ResourceTagMappingList: [
          {
            ResourceARN: "arn:aws:agentcore:us-east-1:123:runtime/dep-updater",
            Tags: [
              { Key: "agent:managed", Value: "true" },
              { Key: "agent:name", Value: "dep-updater" },
              { Key: "agent:domain", Value: "security" },
            ],
          },
        ],
      });

    setTaggingClient(taggingMock as unknown as ResourceGroupsTaggingAPIClient);

    const resultPromise = listManagedAgents();
    await vi.advanceTimersByTimeAsync(5000);
    const result = await resultPromise;

    expect(result).toHaveLength(1);
    expect(result.at(0)).toEqual({
      name: "dep-updater",
      domain: "security",
      arn: "arn:aws:agentcore:us-east-1:123:runtime/dep-updater",
    });
  });

  it("does not retry ValidationException", async () => {
    vi.useRealTimers();
    const validationError = Object.assign(new Error("Invalid input"), {
      name: "ValidationException",
      $metadata: { httpStatusCode: 400 },
    });

    taggingMock.on(GetResourcesCommand).rejects(validationError);
    setTaggingClient(taggingMock as unknown as ResourceGroupsTaggingAPIClient);

    await expect(listManagedAgents()).rejects.toThrow("Invalid input");
    // Only 1 call — no retry
    expect(taggingMock.commandCalls(GetResourcesCommand)).toHaveLength(1);
    vi.useFakeTimers();
  });
});

describe("Logs Insights adapter — throttle then success", () => {
  const logsMock = mockClient(CloudWatchLogsClient);

  beforeEach(() => {
    logsMock.reset();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("retries StartQuery throttle and eventually returns results", async () => {
    const throttleError = Object.assign(new Error("Rate exceeded"), {
      name: "ThrottlingException",
      $metadata: { httpStatusCode: 429 },
    });

    logsMock.on(StartQueryCommand).rejectsOnce(throttleError).resolves({ queryId: "q-123" });

    logsMock.on(GetQueryResultsCommand).resolves({
      status: "Complete",
      results: [[{ field: "@timestamp", value: "2026-01-01T00:00:00Z" }]],
    });

    setLogsClient(logsMock as unknown as CloudWatchLogsClient);

    const resultPromise = executeInsightsQuery(
      {
        logGroupName: "/test/logs",
        queryString: "fields @timestamp",
        startTime: 0,
        endTime: 999999999,
      },
      { initialDelayMs: 10, maxDelayMs: 50, deadlineMs: 10000 },
    );

    await vi.advanceTimersByTimeAsync(15000);
    const result = await resultPromise;

    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.data.rows).toHaveLength(1);
      expect(result.data.rows[0]?.["@timestamp"]).toBe("2026-01-01T00:00:00Z");
    }
  });

  it("returns timeout and calls StopQuery when deadline exceeded", async () => {
    logsMock.on(StartQueryCommand).resolves({ queryId: "q-timeout" });
    logsMock.on(GetQueryResultsCommand).resolves({ status: "Running" });
    logsMock.on(StopQueryCommand).resolves({});

    setLogsClient(logsMock as unknown as CloudWatchLogsClient);

    const resultPromise = executeInsightsQuery(
      {
        logGroupName: "/test/logs",
        queryString: "fields @timestamp",
        startTime: 0,
        endTime: 999999999,
      },
      { initialDelayMs: 50, maxDelayMs: 200, deadlineMs: 500 },
    );

    await vi.advanceTimersByTimeAsync(5000);
    const result = await resultPromise;

    expect(result.status).toBe("timeout");
    expect(logsMock.commandCalls(StopQueryCommand)).toHaveLength(1);
  });

  it("does not retry validation errors on StartQuery", async () => {
    const validationError = Object.assign(new Error("Malformed query"), {
      name: "MalformedQueryException",
      $metadata: { httpStatusCode: 400 },
    });

    logsMock.on(StartQueryCommand).rejects(validationError);
    setLogsClient(logsMock as unknown as CloudWatchLogsClient);

    const resultPromise = executeInsightsQuery(
      {
        logGroupName: "/test/logs",
        queryString: "BAD QUERY",
        startTime: 0,
        endTime: 999999999,
      },
      { initialDelayMs: 10, maxDelayMs: 50, deadlineMs: 5000 },
    );

    await vi.advanceTimersByTimeAsync(5000);
    const result = await resultPromise;

    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.error).toContain("Malformed query");
    }
    // Only 1 call — no retry for validation error
    expect(logsMock.commandCalls(StartQueryCommand)).toHaveLength(1);
  });
});

describe("FilterLogEvents adapter — throttle then success", () => {
  const logsMock = mockClient(CloudWatchLogsClient);

  beforeEach(() => {
    logsMock.reset();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("retries on throttle and returns log lines", async () => {
    const throttleError = Object.assign(new Error("Rate exceeded"), {
      name: "ThrottlingException",
      $metadata: { httpStatusCode: 429 },
    });

    logsMock
      .on(FilterLogEventsCommand)
      .rejectsOnce(throttleError)
      .resolves({
        events: [
          { message: '{"level":"info","msg":"hello"}\n' },
          { message: '{"level":"info","msg":"world"}\n' },
        ],
      });

    setFilterLogsClient(logsMock as unknown as CloudWatchLogsClient);

    const resultPromise = filterLogsBySessionId({
      logGroupName: "/test/logs",
      sessionId: "test-session-123",
    });

    await vi.advanceTimersByTimeAsync(5000);
    const result = await resultPromise;

    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.data).toHaveLength(2);
      expect(result.data.at(0)).toBe('{"level":"info","msg":"hello"}');
    }
  });
});

describe("DynamoDB repository — throttle then success", () => {
  const ddbMock = mockClient(DynamoDBDocumentClient);

  beforeEach(() => {
    ddbMock.reset();
    vi.useFakeTimers();
    _setDocClient(ddbMock as unknown as DynamoDBDocumentClient);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("retries on throttle for listAgentSubjects", async () => {
    const throttleError = Object.assign(new Error("Rate exceeded"), {
      name: "ThrottlingException",
      $metadata: { httpStatusCode: 429 },
    });

    ddbMock
      .on(QueryCommand)
      .rejectsOnce(throttleError)
      .resolves({
        Items: [
          {
            pk: "SUBJECT#myorg/repo",
            sk: "AGENT#dep-updater",
            enabled: true,
            params: {},
          },
        ],
      });

    const resultPromise = listAgentSubjects("dep-updater");
    await vi.advanceTimersByTimeAsync(5000);
    const result = await resultPromise;

    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.data).toHaveLength(1);
      expect(result.data[0]?.subjectId).toBe("myorg/repo");
    }
  });

  it("retries on throttle for getSubjectAgent", async () => {
    const throttleError = Object.assign(new Error("Rate exceeded"), {
      name: "ThrottlingException",
      $metadata: { httpStatusCode: 429 },
    });

    ddbMock
      .on(GetCommand)
      .rejectsOnce(throttleError)
      .resolves({
        Item: {
          pk: "SUBJECT#myorg/repo",
          sk: "AGENT#dep-updater",
          enabled: true,
          params: { allow_fixes: true },
        },
      });

    const resultPromise = getSubjectAgent("myorg/repo", "dep-updater");
    await vi.advanceTimersByTimeAsync(5000);
    const result = await resultPromise;

    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.data.enabled).toBe(true);
      expect(result.data.params).toEqual({ allow_fixes: true });
    }
  });

  it("does not retry ValidationException for setSubjectEnabled", async () => {
    const validationError = Object.assign(new Error("Invalid"), {
      name: "ValidationException",
      $metadata: { httpStatusCode: 400 },
    });

    ddbMock.on(UpdateCommand).rejects(validationError);

    const resultPromise = setSubjectEnabled("myorg/repo", "dep-updater", true);
    await vi.advanceTimersByTimeAsync(5000);
    const result = await resultPromise;

    expect(result.status).toBe("error");
    // Only 1 call — validation errors not retried
    expect(ddbMock.commandCalls(UpdateCommand)).toHaveLength(1);
  });

  it("retries on throttle for listSubjects", async () => {
    const throttleError = Object.assign(new Error("Rate exceeded"), {
      name: "ThrottlingException",
      $metadata: { httpStatusCode: 429 },
    });

    ddbMock
      .on(QueryCommand)
      .rejectsOnce(throttleError)
      .resolves({
        Items: [
          {
            pk: "SUBJECT#myorg/repo",
            sk: "META",
            subject_id: "myorg/repo",
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
      });

    const resultPromise = listSubjects();
    await vi.advanceTimersByTimeAsync(5000);
    const result = await resultPromise;

    expect(result.status).toBe("ok");
    if (result.status === "ok") {
      expect(result.data).toHaveLength(1);
      expect(result.data[0]?.subjectId).toBe("myorg/repo");
    }
  });
});

describe("No ScanCommand ever sent", () => {
  it("scope-repository.ts source code does not contain ScanCommand", () => {
    // Read all source files in the server directory
    const serverDir = resolve(import.meta.dirname, "..");
    const files = getAllTsFiles(serverDir);

    for (const file of files) {
      // Skip test files
      if (file.includes(".test.") || file.includes(".integration-test.")) continue;

      const content = readFileSync(file, "utf-8");
      expect(content).not.toContain("ScanCommand");
      expect(content).not.toContain("new Scan");
    }
  });
});

function getAllTsFiles(dir: string): string[] {
  const results: string[] = [];
  const entries = readdirSync(dir, { withFileTypes: true });

  for (const entry of entries) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory() && !entry.name.startsWith(".") && entry.name !== "node_modules") {
      results.push(...getAllTsFiles(fullPath));
    } else if (entry.isFile() && entry.name.endsWith(".ts")) {
      results.push(fullPath);
    }
  }

  return results;
}
