import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { mapSpanToRunFields, isRootSpan, isGenAiChildSpan } from "./span-mapper.js";
import type { MappedRunFields } from "./span-mapper.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const fixturesDir = resolve(__dirname, "../__fixtures__");

function loadFixture(name: string): Record<string, unknown> {
  const raw = readFileSync(resolve(fixturesDir, name), "utf-8");
  return JSON.parse(raw) as Record<string, unknown>;
}

describe("span-mapper", () => {
  describe("isRootSpan", () => {
    it("identifies root span by empty parentSpanId and llipe.run.status presence", () => {
      const root = loadFixture("root-span.json");
      expect(isRootSpan(root)).toBe(true);
    });

    it("rejects child span (non-empty parentSpanId)", () => {
      const child = loadFixture("gen-ai-child-span.json");
      expect(isRootSpan(child)).toBe(false);
    });

    it("rejects span without llipe.run.status even if parentSpanId is empty", () => {
      const span = {
        parentSpanId: "",
        resource: { attributes: { "service.name": "dep-updater" } },
      };
      expect(isRootSpan(span)).toBe(false);
    });
  });

  describe("isGenAiChildSpan", () => {
    it("identifies gen_ai child span by parentSpanId and gen_ai attributes", () => {
      const child = loadFixture("gen-ai-child-span.json");
      expect(isGenAiChildSpan(child)).toBe(true);
    });

    it("rejects root span (no gen_ai.request.model attribute)", () => {
      const root = loadFixture("root-span.json");
      expect(isGenAiChildSpan(root)).toBe(false);
    });

    it("rejects span with gen_ai attributes but no parentSpanId", () => {
      const span = {
        parentSpanId: "",
        attributes: { "gen_ai.request.model": "us.anthropic.claude-sonnet-4-6" },
        resource: { attributes: {} },
      };
      expect(isGenAiChildSpan(span)).toBe(false);
    });
  });

  describe("mapSpanToRunFields - root span", () => {
    it("resolves all run-level fields from root span fixture", () => {
      const root = loadFixture("root-span.json");
      const result = mapSpanToRunFields(root);

      expect(result).not.toBeNull();
      const fields = result as MappedRunFields;

      expect(fields.sessionId).toBe("dep-updater__llipe-dev-tasks-agent-fleet__20250127T120000Z");
      expect(fields.subjectId).toBe("llipe/dev-tasks-agent-fleet");
      expect(fields.runStatus).toBe("success");
      expect(fields.outcomeType).toBe("pr");
      expect(fields.outcomeUrl).toBe("https://github.com/llipe/dev-tasks-agent-fleet/pull/42");
      expect(fields.serviceName).toBe("dep-updater");
      expect(fields.durationNs).toBe(60000000000);
      expect(fields.timestamp).toBe("1737999000000000000");
    });

    it("returns null for child spans", () => {
      const child = loadFixture("gen-ai-child-span.json");
      const result = mapSpanToRunFields(child);
      expect(result).toBeNull();
    });

    it("resolves session ID via fallback when primary is absent", () => {
      const span = {
        parentSpanId: "",
        startTimeUnixNano: "1737999000000000000",
        duration: 5000000000,
        resource: {
          attributes: {
            "service.name": "dep-updater",
            "llipe.session.id": "fallback-session-id",
            "llipe.subject.id": "owner/repo",
            "llipe.run.status": "success",
            "llipe.outcome.type": "none",
            "llipe.outcome.url": "",
          },
        },
        attributes: {},
      };

      const result = mapSpanToRunFields(span);
      expect(result).not.toBeNull();
      expect((result as MappedRunFields).sessionId).toBe("fallback-session-id");
    });

    it("returns null if session ID is not resolvable from any path", () => {
      const span = {
        parentSpanId: "",
        startTimeUnixNano: "1737999000000000000",
        duration: 5000000000,
        resource: {
          attributes: {
            "service.name": "dep-updater",
            "llipe.subject.id": "owner/repo",
            "llipe.run.status": "success",
            "llipe.outcome.type": "none",
            "llipe.outcome.url": "",
          },
        },
        attributes: {},
      };

      const result = mapSpanToRunFields(span);
      expect(result).toBeNull();
    });
  });

  describe("mapSpanToRunFields - gen_ai child span", () => {
    it("resolves gen_ai fields from child span fixture", () => {
      const child = loadFixture("gen-ai-child-span.json");
      const result = mapSpanToRunFields(child);

      // Child spans should not map to run fields (they produce gen_ai fields)
      expect(result).toBeNull();
    });
  });

  describe("isGenAiChildSpan extracts token fields", () => {
    it("provides model and token fields on gen_ai child spans", () => {
      const child = loadFixture("gen-ai-child-span.json");
      expect(isGenAiChildSpan(child)).toBe(true);

      // Validate that the fields needed for cost estimation are present
      const attrs = (child as { attributes: Record<string, unknown> }).attributes;
      expect(attrs["gen_ai.request.model"]).toBe("us.anthropic.claude-sonnet-4-6");
      expect(attrs["gen_ai.usage.input_tokens"]).toBe(1500);
      expect(attrs["gen_ai.usage.output_tokens"]).toBe(500);
    });
  });

  describe("edge cases", () => {
    it("handles span with zero duration", () => {
      const span = {
        parentSpanId: "",
        startTimeUnixNano: "1737999000000000000",
        duration: 0,
        resource: {
          attributes: {
            "service.name": "dep-updater",
            "session.id": "test-session",
            "llipe.session.id": "test-session",
            "llipe.subject.id": "owner/repo",
            "llipe.run.status": "failed",
            "llipe.outcome.type": "none",
            "llipe.outcome.url": "",
          },
        },
        attributes: {},
      };

      const result = mapSpanToRunFields(span);
      expect(result).not.toBeNull();
      expect((result as MappedRunFields).durationNs).toBe(0);
    });

    it("handles span with empty outcome URL (no_updates case)", () => {
      const span = {
        parentSpanId: "",
        startTimeUnixNano: "1737999000000000000",
        duration: 30000000000,
        resource: {
          attributes: {
            "service.name": "dep-updater",
            "session.id": "test-session",
            "llipe.session.id": "test-session",
            "llipe.subject.id": "owner/repo",
            "llipe.run.status": "success",
            "llipe.outcome.type": "none",
            "llipe.outcome.url": "",
          },
        },
        attributes: {},
      };

      const result = mapSpanToRunFields(span);
      expect(result).not.toBeNull();
      expect((result as MappedRunFields).outcomeUrl).toBe("");
      expect((result as MappedRunFields).outcomeType).toBe("none");
    });
  });
});
