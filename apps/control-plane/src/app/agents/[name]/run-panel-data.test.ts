import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchLogData, resolveAgentLogGroup } from "./run-panel-data.js";

/**
 * AGENT_LOG_GROUP resolution (issue #56, defect D3).
 *
 * The fallback used to be `/aws/agentcore/dep-updater`, a group that does not
 * exist. AgentCore names the application log group
 * `/aws/bedrock-agentcore/runtimes/depupdater_dep_updater-<generated>-DEFAULT`,
 * and the suffix changes whenever the runtime is recreated — so there is no
 * correct compile-time default. Querying a nonexistent group returns an empty
 * result rather than an error, which made a misconfigured deployment look like a
 * run with no logs.
 *
 * The env var is therefore required, and a missing value surfaces as an
 * actionable error instead of silently empty logs.
 */

const ENV_KEY = "AGENT_LOG_GROUP";
const REAL_GROUP = "/aws/bedrock-agentcore/runtimes/depupdater_dep_updater-M4gkuL4wSr-DEFAULT";

describe("resolveAgentLogGroup", () => {
  const original = process.env[ENV_KEY];

  beforeEach(() => {
    delete process.env[ENV_KEY];
  });

  afterEach(() => {
    if (original === undefined) delete process.env[ENV_KEY];
    else process.env[ENV_KEY] = original;
  });

  it("returns the configured group name", () => {
    process.env[ENV_KEY] = REAL_GROUP;
    expect(resolveAgentLogGroup()).toBe(REAL_GROUP);
  });

  it("returns null when unset rather than guessing a group name", () => {
    expect(resolveAgentLogGroup()).toBeNull();
  });

  it("treats an empty or whitespace-only value as unset", () => {
    process.env[ENV_KEY] = "   ";
    expect(resolveAgentLogGroup()).toBeNull();
  });

  it("trims surrounding whitespace", () => {
    process.env[ENV_KEY] = `  ${REAL_GROUP}  `;
    expect(resolveAgentLogGroup()).toBe(REAL_GROUP);
  });

  it("is read per call, not frozen at module load", () => {
    process.env[ENV_KEY] = REAL_GROUP;
    expect(resolveAgentLogGroup()).toBe(REAL_GROUP);
    process.env[ENV_KEY] = "other-group";
    expect(resolveAgentLogGroup()).toBe("other-group");
  });
});

describe("fetchLogData — log group configuration", () => {
  const original = process.env[ENV_KEY];
  const from = new Date("2025-01-27T00:00:00.000Z");
  const to = new Date("2025-01-28T00:00:00.000Z");

  afterEach(() => {
    if (original === undefined) delete process.env[ENV_KEY];
    else process.env[ENV_KEY] = original;
  });

  it("passes the configured group through to the adapter", async () => {
    process.env[ENV_KEY] = REAL_GROUP;
    const filterLogsBySessionId = vi
      .fn()
      .mockResolvedValue({ status: "ok", data: [], correlationId: "c1" });

    await fetchLogData("session-abc", from, to, {
      querySessionTrace: vi.fn(),
      filterLogsBySessionId,
    });

    expect(filterLogsBySessionId).toHaveBeenCalledWith(
      expect.objectContaining({ logGroupName: REAL_GROUP }),
    );
  });

  it("returns an actionable error and skips the query when unset", async () => {
    delete process.env[ENV_KEY];
    const filterLogsBySessionId = vi.fn();

    const result = await fetchLogData("session-abc", from, to, {
      querySessionTrace: vi.fn(),
      filterLogsBySessionId,
    });

    expect(filterLogsBySessionId).not.toHaveBeenCalled();
    expect(result.status).toBe("error");
    if (result.status !== "error") throw new Error("unreachable");
    expect(result.error).toContain(ENV_KEY);
    expect(result.correlationId).toBeTruthy();
  });

  it("never falls back to the fictional /aws/agentcore/dep-updater group", async () => {
    delete process.env[ENV_KEY];
    const filterLogsBySessionId = vi
      .fn()
      .mockResolvedValue({ status: "ok", data: [], correlationId: "c1" });

    await fetchLogData("session-abc", from, to, {
      querySessionTrace: vi.fn(),
      filterLogsBySessionId,
    });

    for (const call of filterLogsBySessionId.mock.calls) {
      expect(JSON.stringify(call)).not.toContain("/aws/agentcore/dep-updater");
    }
  });
});
