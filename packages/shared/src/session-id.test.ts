import { describe, it, expect } from "vitest";
import { buildSessionId } from "./session-id.js";

describe("buildSessionId", () => {
  const scheduledAt = new Date("2026-08-24T06:00:00Z");

  describe("length floor", () => {
    it("produces at least 33 characters for shortest inputs", () => {
      // Shortest possible: agent="ci", repo="a/b"
      const id = buildSessionId("ci", "a/b", scheduledAt);
      expect(id.length).toBeGreaterThanOrEqual(33);
    });

    it("produces at least 33 characters for normal inputs", () => {
      const id = buildSessionId("dep-updater", "myorg/my-repo", scheduledAt);
      expect(id.length).toBeGreaterThanOrEqual(33);
    });

    it("produces at least 33 characters for long inputs", () => {
      const id = buildSessionId(
        "very-long-agent-name",
        "organization/very-long-repository-name",
        scheduledAt,
      );
      expect(id.length).toBeGreaterThanOrEqual(33);
    });
  });

  describe("determinism", () => {
    it("produces the same output for the same inputs", () => {
      const id1 = buildSessionId("dep-updater", "myorg/repo", scheduledAt);
      const id2 = buildSessionId("dep-updater", "myorg/repo", scheduledAt);
      expect(id1).toBe(id2);
    });

    it("produces different output for different agents", () => {
      const id1 = buildSessionId("dep-updater", "myorg/repo", scheduledAt);
      const id2 = buildSessionId("other-agent", "myorg/repo", scheduledAt);
      expect(id1).not.toBe(id2);
    });

    it("produces different output for different repos", () => {
      const id1 = buildSessionId("dep-updater", "myorg/repo-a", scheduledAt);
      const id2 = buildSessionId("dep-updater", "myorg/repo-b", scheduledAt);
      expect(id1).not.toBe(id2);
    });

    it("produces different output for different times", () => {
      const id1 = buildSessionId("dep-updater", "myorg/repo", scheduledAt);
      const id2 = buildSessionId("dep-updater", "myorg/repo", new Date("2026-08-25T06:00:00Z"));
      expect(id1).not.toBe(id2);
    });
  });

  describe("charset", () => {
    it("only contains URL-safe characters (alphanumeric and hyphen)", () => {
      const id = buildSessionId("dep-updater", "myorg/repo", scheduledAt);
      expect(id).toMatch(/^[A-Za-z0-9-]+$/);
    });

    it("only contains URL-safe characters for shortest input", () => {
      const id = buildSessionId("ci", "a/b", scheduledAt);
      expect(id).toMatch(/^[A-Za-z0-9-]+$/);
    });
  });
});
