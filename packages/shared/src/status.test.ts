import { describe, it, expect } from "vitest";
import { deriveStatus, DEFAULT_MAX_LIFETIME_MS, TERMINATION_GRACE_MS } from "./status.js";

describe("deriveStatus", () => {
  const BASE_TIME = 1_700_000_000_000; // fixed reference point

  describe("non-running statuses pass through", () => {
    it("returns 'success' as-is", () => {
      expect(
        deriveStatus("success", new Date(BASE_TIME - 100_000).toISOString(), undefined, BASE_TIME),
      ).toBe("success");
    });

    it("returns 'failed' as-is", () => {
      expect(
        deriveStatus("failed", new Date(BASE_TIME - 100_000).toISOString(), undefined, BASE_TIME),
      ).toBe("failed");
    });

    it("returns unknown statuses as-is", () => {
      expect(
        deriveStatus(
          "cancelled",
          new Date(BASE_TIME - 100_000).toISOString(),
          undefined,
          BASE_TIME,
        ),
      ).toBe("cancelled");
    });
  });

  describe("running status with time boundary checks", () => {
    const maxLifetime = 3_600_000; // 1 hour

    it("returns 'running' when elapsed < maxLifetime + grace", () => {
      const elapsed = maxLifetime + TERMINATION_GRACE_MS - 1; // 1ms before boundary
      const lastRunAt = new Date(BASE_TIME - elapsed).toISOString();
      expect(deriveStatus("running", lastRunAt, maxLifetime, BASE_TIME)).toBe("running");
    });

    it("returns 'incomplete' at exactly maxLifetime + grace (boundary)", () => {
      const elapsed = maxLifetime + TERMINATION_GRACE_MS; // exactly at boundary
      const lastRunAt = new Date(BASE_TIME - elapsed).toISOString();
      expect(deriveStatus("running", lastRunAt, maxLifetime, BASE_TIME)).toBe("incomplete");
    });

    it("returns 'incomplete' when elapsed > maxLifetime + grace (+1ms)", () => {
      const elapsed = maxLifetime + TERMINATION_GRACE_MS + 1; // 1ms after boundary
      const lastRunAt = new Date(BASE_TIME - elapsed).toISOString();
      expect(deriveStatus("running", lastRunAt, maxLifetime, BASE_TIME)).toBe("incomplete");
    });
  });

  describe("absent maxLifetime fallback", () => {
    it("uses DEFAULT_MAX_LIFETIME_MS when maxLifetimeMs is undefined", () => {
      const elapsed = DEFAULT_MAX_LIFETIME_MS + TERMINATION_GRACE_MS;
      const lastRunAt = new Date(BASE_TIME - elapsed).toISOString();
      expect(deriveStatus("running", lastRunAt, undefined, BASE_TIME)).toBe("incomplete");
    });

    it("still running within DEFAULT_MAX_LIFETIME_MS + grace", () => {
      const elapsed = DEFAULT_MAX_LIFETIME_MS + TERMINATION_GRACE_MS - 1;
      const lastRunAt = new Date(BASE_TIME - elapsed).toISOString();
      expect(deriveStatus("running", lastRunAt, undefined, BASE_TIME)).toBe("running");
    });
  });

  describe("unparseable lastRunAt", () => {
    it("returns the original status when lastRunAt is empty", () => {
      expect(deriveStatus("running", "", undefined, BASE_TIME)).toBe("running");
    });

    it("returns the original status when lastRunAt is invalid", () => {
      expect(deriveStatus("running", "not-a-date", undefined, BASE_TIME)).toBe("running");
    });

    it("returns the original status when lastRunAt is undefined", () => {
      expect(deriveStatus("running", undefined, undefined, BASE_TIME)).toBe("running");
    });
  });

  describe("constants", () => {
    it("DEFAULT_MAX_LIFETIME_MS is 28_800_000 (8 hours)", () => {
      expect(DEFAULT_MAX_LIFETIME_MS).toBe(28_800_000);
    });

    it("TERMINATION_GRACE_MS is 300_000 (5 minutes)", () => {
      expect(TERMINATION_GRACE_MS).toBe(300_000);
    });
  });
});
