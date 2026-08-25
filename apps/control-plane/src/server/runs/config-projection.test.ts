/**
 * Unit tests for config-projection — S-018 sub-tasks 18.2, 18.11.
 *
 * Covers:
 * - Config-row-to-Run projection
 * - deriveStatus wired with per-agent maxLifetime
 * - Boundary case ±1 ms around the threshold
 */

import { describe, it, expect } from "vitest";
import { projectConfigRun } from "./config-projection.js";
import type { SubjectAgent } from "../repository/scope-repository.js";
import { DEFAULT_MAX_LIFETIME_MS, TERMINATION_GRACE_MS } from "@fleet/shared";

function makeSubjectAgent(overrides: Partial<SubjectAgent> = {}): SubjectAgent {
  return {
    subjectId: "myorg/repo-a",
    agentName: "dep-updater",
    enabled: true,
    params: {},
    lastSessionId: "session-abc-123",
    lastRunAt: "2026-08-20T06:00:00.000Z",
    lastStatus: "success",
    lastOutcomeUrl: "https://github.com/myorg/repo-a/pull/1",
    ...overrides,
  };
}

describe("projectConfigRun", () => {
  it("projects a SubjectAgent into a ConfigRun with source='config'", () => {
    const agent = makeSubjectAgent();
    const result = projectConfigRun(agent, 28800);

    expect(result).not.toBeNull();
    expect(result?.sessionId).toBe("session-abc-123");
    expect(result?.subjectId).toBe("myorg/repo-a");
    expect(result?.agentName).toBe("dep-updater");
    expect(result?.status).toBe("success");
    expect(result?.outcomeType).toBe("");
    expect(result?.outcomeUrl).toBe("https://github.com/myorg/repo-a/pull/1");
    expect(result?.startedAt).toBe("2026-08-20T06:00:00.000Z");
    expect(result?.durationMs).toBe(0);
    expect(result?.perModel).toEqual([]);
    expect(result?.source).toBe("config");
  });

  it("returns null when lastSessionId is missing", () => {
    const agent = makeSubjectAgent({ lastSessionId: undefined });
    const result = projectConfigRun(agent, 28800);
    expect(result).toBeNull();
  });

  it("returns null when lastRunAt is missing", () => {
    const agent = makeSubjectAgent({ lastRunAt: undefined });
    const result = projectConfigRun(agent, 28800);
    expect(result).toBeNull();
  });

  describe("deriveStatus with per-agent maxLifetime", () => {
    // dep-updater: maxLifetime=3600s → 3_600_000ms
    // threshold = maxLifetime + TERMINATION_GRACE = 3_600_000 + 300_000 = 3_900_000ms
    const DEP_UPDATER_MAX_LIFETIME = 3600; // seconds
    const thresholdMs = DEP_UPDATER_MAX_LIFETIME * 1000 + TERMINATION_GRACE_MS;

    it("running run within maxLifetime stays 'running'", () => {
      const startTime = "2026-08-20T06:00:00.000Z";
      const startMs = new Date(startTime).getTime();
      const now = startMs + 60_000;

      const agent = makeSubjectAgent({ lastStatus: "running", lastRunAt: startTime });
      const result = projectConfigRun(agent, DEP_UPDATER_MAX_LIFETIME, now);

      expect(result?.status).toBe("running");
    });

    it("running run at exactly threshold-1ms stays 'running' (boundary)", () => {
      const startTime = "2026-08-20T06:00:00.000Z";
      const startMs = new Date(startTime).getTime();
      const now = startMs + thresholdMs - 1;

      const agent = makeSubjectAgent({ lastStatus: "running", lastRunAt: startTime });
      const result = projectConfigRun(agent, DEP_UPDATER_MAX_LIFETIME, now);

      expect(result?.status).toBe("running");
    });

    it("running run at exactly threshold becomes 'incomplete' (boundary)", () => {
      const startTime = "2026-08-20T06:00:00.000Z";
      const startMs = new Date(startTime).getTime();
      const now = startMs + thresholdMs;

      const agent = makeSubjectAgent({ lastStatus: "running", lastRunAt: startTime });
      const result = projectConfigRun(agent, DEP_UPDATER_MAX_LIFETIME, now);

      expect(result?.status).toBe("incomplete");
    });

    it("running run at threshold+1ms is 'incomplete' (boundary)", () => {
      const startTime = "2026-08-20T06:00:00.000Z";
      const startMs = new Date(startTime).getTime();
      const now = startMs + thresholdMs + 1;

      const agent = makeSubjectAgent({ lastStatus: "running", lastRunAt: startTime });
      const result = projectConfigRun(agent, DEP_UPDATER_MAX_LIFETIME, now);

      expect(result?.status).toBe("incomplete");
    });

    it("uses default maxLifetime when not provided", () => {
      const startTime = "2026-08-20T06:00:00.000Z";
      const startMs = new Date(startTime).getTime();
      const now = startMs + DEFAULT_MAX_LIFETIME_MS + TERMINATION_GRACE_MS;

      const agent = makeSubjectAgent({ lastStatus: "running", lastRunAt: startTime });
      const result = projectConfigRun(agent, undefined, now);

      expect(result?.status).toBe("incomplete");
    });

    it("non-running status passes through unchanged", () => {
      const agent = makeSubjectAgent({ lastStatus: "failed" });
      const result = projectConfigRun(agent, DEP_UPDATER_MAX_LIFETIME);

      expect(result?.status).toBe("failed");
    });

    it("success status passes through unchanged", () => {
      const agent = makeSubjectAgent({ lastStatus: "success" });
      const result = projectConfigRun(agent, DEP_UPDATER_MAX_LIFETIME);

      expect(result?.status).toBe("success");
    });
  });
});
