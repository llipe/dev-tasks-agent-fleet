import { describe, it, expect } from "vitest";
import {
  okOutcome,
  emptyOutcome,
  timeoutOutcome,
  errorOutcome,
  makeCorrelationId,
} from "./types.js";

describe("ReadOutcome<T>", () => {
  describe("makeCorrelationId", () => {
    it("returns a UUID-like string", () => {
      const id = makeCorrelationId();
      expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
    });

    it("generates unique IDs", () => {
      const ids = new Set(Array.from({ length: 100 }, () => makeCorrelationId()));
      expect(ids.size).toBe(100);
    });
  });

  describe("ok outcome", () => {
    it("has status 'ok' and carries data", () => {
      const result = okOutcome({ items: [1, 2, 3] });
      expect(result.status).toBe("ok");
      if (result.status === "ok") {
        expect(result.data).toEqual({ items: [1, 2, 3] });
      }
      expect(result.correlationId).toBeDefined();
    });

    it("accepts a custom correlation id", () => {
      const result = okOutcome("data", "custom-id");
      expect(result.correlationId).toBe("custom-id");
    });
  });

  describe("empty outcome", () => {
    it("has status 'empty' with correlation id", () => {
      const result = emptyOutcome<string>();
      expect(result.status).toBe("empty");
      expect(result.correlationId).toBeDefined();
    });
  });

  describe("timeout outcome", () => {
    it("has status 'timeout' with correlation id", () => {
      const result = timeoutOutcome<number>();
      expect(result.status).toBe("timeout");
      expect(result.correlationId).toBeDefined();
    });
  });

  describe("error outcome", () => {
    it("has status 'error' with error message and correlation id", () => {
      const result = errorOutcome<string>("something went wrong");
      expect(result.status).toBe("error");
      if (result.status === "error") {
        expect(result.error).toBe("something went wrong");
      }
      expect(result.correlationId).toBeDefined();
    });
  });
});
