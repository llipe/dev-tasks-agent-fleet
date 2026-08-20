/**
 * Integration tests (mocked) for Logs Insights query execution.
 *
 * Tests:
 * - Complete after several Running polls
 * - Failed query
 * - Cancelled query
 * - Deadline exceeded → StopQuery + timeout
 * - Concurrent identical queries collapse via single-flight
 */

/* eslint-disable @typescript-eslint/no-non-null-assertion */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mockClient } from "aws-sdk-client-mock";
import {
  CloudWatchLogsClient,
  StartQueryCommand,
  GetQueryResultsCommand,
  StopQueryCommand,
} from "@aws-sdk/client-cloudwatch-logs";
import { _setClient, executeInsightsQuery } from "../aws/logs-insights-adapter.js";
import { queryRuns, clearRunListCache } from "./run-query-service.js";
import type { LogsInsightsQueryParams } from "../aws/logs-insights-adapter.js";

const cwlMock = mockClient(CloudWatchLogsClient);

function makeQueryParams(): LogsInsightsQueryParams {
  return {
    logGroupName: "/aws/vendedlogs/agentcore/dep-updater/spans",
    queryString: "fields @timestamp | limit 10",
    startTime: Math.floor(Date.now() / 1000) - 86400,
    endTime: Math.floor(Date.now() / 1000),
  };
}

function makeResultRow() {
  return [
    { field: "session_id", value: "test-session-001" },
    { field: "session_id_fallback", value: "test-session-001" },
    { field: "subject_id", value: "org/repo" },
    { field: "run_status", value: "success" },
    { field: "outcome_type", value: "pr" },
    { field: "outcome_url", value: "https://github.com/org/repo/pull/1" },
    { field: "service_name", value: "dep-updater" },
    { field: "duration_ns", value: "60000000000" },
    { field: "start_time", value: "1737999000000000000" },
    { field: "parent_span_id", value: "" },
  ];
}

describe("Logs Insights query integration", () => {
  beforeEach(() => {
    cwlMock.reset();
    clearRunListCache();
    // Inject the mocked client
    _setClient(cwlMock as unknown as CloudWatchLogsClient);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("Complete after several Running polls", () => {
    it("polls until Complete and returns ok with results", async () => {
      cwlMock.on(StartQueryCommand).resolves({ queryId: "query-123" });

      // First two polls return Running, third returns Complete
      let pollCount = 0;
      cwlMock.on(GetQueryResultsCommand).callsFake(() => {
        pollCount++;
        if (pollCount < 3) {
          return { status: "Running", results: [] };
        }
        return {
          status: "Complete",
          results: [makeResultRow()],
        };
      });

      const result = await executeInsightsQuery(makeQueryParams(), {
        initialDelayMs: 10,
        maxDelayMs: 50,
        deadlineMs: 5000,
      });

      expect(result.status).toBe("ok");
      if (result.status === "ok") {
        expect(result.data.rows).toHaveLength(1);
        expect(result.data.rows[0]!["session_id"]).toBe("test-session-001");
      }
      expect(pollCount).toBe(3);
    });
  });

  describe("Failed query", () => {
    it("returns error when query status is Failed", async () => {
      cwlMock.on(StartQueryCommand).resolves({ queryId: "query-fail" });

      cwlMock.on(GetQueryResultsCommand).resolves({ status: "Failed", results: [] });

      const result = await executeInsightsQuery(makeQueryParams(), {
        initialDelayMs: 10,
        maxDelayMs: 50,
        deadlineMs: 5000,
      });

      expect(result.status).toBe("error");
      if (result.status === "error") {
        expect(result.error).toContain("failed");
      }
    });
  });

  describe("Cancelled query", () => {
    it("returns error when query status is Cancelled", async () => {
      cwlMock.on(StartQueryCommand).resolves({ queryId: "query-cancel" });

      cwlMock.on(GetQueryResultsCommand).resolves({ status: "Cancelled", results: [] });

      const result = await executeInsightsQuery(makeQueryParams(), {
        initialDelayMs: 10,
        maxDelayMs: 50,
        deadlineMs: 5000,
      });

      expect(result.status).toBe("error");
      if (result.status === "error") {
        expect(result.error).toContain("cancelled");
      }
    });
  });

  describe("Deadline exceeded → StopQuery + timeout", () => {
    it("calls StopQuery and returns timeout when deadline expires", async () => {
      cwlMock.on(StartQueryCommand).resolves({ queryId: "query-timeout" });

      // Always return Running so it never completes
      cwlMock.on(GetQueryResultsCommand).resolves({ status: "Running", results: [] });

      cwlMock.on(StopQueryCommand).resolves({});

      const result = await executeInsightsQuery(makeQueryParams(), {
        initialDelayMs: 10,
        maxDelayMs: 20,
        deadlineMs: 100, // Very short deadline for test speed
      });

      expect(result.status).toBe("timeout");

      // Verify StopQuery was called
      const stopCalls = cwlMock.commandCalls(StopQueryCommand);
      expect(stopCalls.length).toBe(1);
      expect(stopCalls[0]!.args[0].input.queryId).toBe("query-timeout");
    });

    it("timeout is distinct from empty", async () => {
      // Empty case
      cwlMock.on(StartQueryCommand).resolves({ queryId: "query-empty" });
      cwlMock.on(GetQueryResultsCommand).resolves({ status: "Complete", results: [] });

      const emptyResult = await executeInsightsQuery(makeQueryParams(), {
        initialDelayMs: 10,
        maxDelayMs: 50,
        deadlineMs: 5000,
      });

      expect(emptyResult.status).toBe("empty");

      // Timeout case
      cwlMock.reset();
      cwlMock.on(StartQueryCommand).resolves({ queryId: "query-timeout-2" });
      cwlMock.on(GetQueryResultsCommand).resolves({ status: "Running", results: [] });
      cwlMock.on(StopQueryCommand).resolves({});

      const timeoutResult = await executeInsightsQuery(makeQueryParams(), {
        initialDelayMs: 10,
        maxDelayMs: 20,
        deadlineMs: 100,
      });

      expect(timeoutResult.status).toBe("timeout");
      expect(emptyResult.status).not.toBe(timeoutResult.status);
    });
  });

  describe("Run query service integration", () => {
    it("maps successful query results to Run objects", async () => {
      cwlMock.on(StartQueryCommand).resolves({ queryId: "query-runs" });

      cwlMock.on(GetQueryResultsCommand).resolves({
        status: "Complete",
        results: [makeResultRow()],
      });

      const input = {
        agentName: "dep-updater",
        from: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000),
        to: new Date(),
      };

      const result = await queryRuns(input);

      expect(result.status).toBe("ok");
      if (result.status === "ok") {
        expect(result.data).toHaveLength(1);
        expect(result.data[0]!.sessionId).toBe("test-session-001");
        expect(result.data[0]!.source).toBe("spans");
      }
    });
  });
});

describe("Concurrent identical queries collapse via single-flight", () => {
  beforeEach(() => {
    cwlMock.reset();
    clearRunListCache();
    _setClient(cwlMock as unknown as CloudWatchLogsClient);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("multiple concurrent calls for the same key result in one StartQuery", async () => {
    let startQueryCount = 0;

    cwlMock.on(StartQueryCommand).callsFake(() => {
      startQueryCount++;
      return { queryId: "query-single-flight" };
    });

    cwlMock.on(GetQueryResultsCommand).resolves({
      status: "Complete",
      results: [makeResultRow()],
    });

    const input = {
      agentName: "dep-updater",
      from: new Date("2025-01-01T00:00:00Z"),
      to: new Date("2025-01-02T00:00:00Z"),
    };

    // Fire 3 concurrent requests with same input
    const [r1, r2, r3] = await Promise.all([queryRuns(input), queryRuns(input), queryRuns(input)]);

    // All should succeed
    expect(r1.status).toBe("ok");
    expect(r2.status).toBe("ok");
    expect(r3.status).toBe("ok");

    // Only ONE StartQuery should have been issued (single-flight)
    expect(startQueryCount).toBe(1);
  });
});
