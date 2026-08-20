import { describe, it, expect } from "vitest";
import { parseMaxLifetime, getAgentLifecycle, clearLifecycleCache } from "./agentcore-adapter.js";

describe("AgentCore adapter", () => {
  describe("parseMaxLifetime", () => {
    it("returns the value when maxLifetime is present", () => {
      expect(parseMaxLifetime({ maxLifetime: 3600 })).toBe(3600);
    });

    it("defaults to 28800 when maxLifetime is undefined", () => {
      expect(parseMaxLifetime({ maxLifetime: undefined })).toBe(28800);
    });

    it("defaults to 28800 when lifecycleConfig is undefined", () => {
      expect(parseMaxLifetime(undefined)).toBe(28800);
    });

    it("defaults to 28800 when lifecycleConfig is null", () => {
      expect(parseMaxLifetime(null)).toBe(28800);
    });

    it("defaults to 28800 when lifecycleConfig is an empty object", () => {
      expect(parseMaxLifetime({})).toBe(28800);
    });

    it("returns 0 when maxLifetime is explicitly 0", () => {
      expect(parseMaxLifetime({ maxLifetime: 0 })).toBe(0);
    });
  });

  describe("getAgentLifecycle", () => {
    it("returns default maxLifetime of 28800", async () => {
      clearLifecycleCache();
      const result = await getAgentLifecycle("dep-updater");
      expect(result.maxLifetime).toBe(28800);
    });

    it("returns same result for any agent name (default behavior)", async () => {
      clearLifecycleCache();
      const a = await getAgentLifecycle("agent-a");
      const b = await getAgentLifecycle("agent-b");
      expect(a.maxLifetime).toBe(28800);
      expect(b.maxLifetime).toBe(28800);
    });
  });
});
