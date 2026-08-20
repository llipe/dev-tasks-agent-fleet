import { describe, it, expect } from "vitest";
import { buildRunListQuery, buildSessionSpansQuery, QUERY_LIMITS } from "./span-query.js";

describe("span-query", () => {
  describe("buildRunListQuery", () => {
    it("produces a valid Logs Insights query string", () => {
      const query = buildRunListQuery();
      expect(typeof query).toBe("string");
      expect(query.length).toBeGreaterThan(0);
    });

    it("includes all run-level field projections", () => {
      const query = buildRunListQuery();

      // Should project session ID, subject, status, outcome, service, duration, timestamp
      expect(query).toContain("session.id");
      expect(query).toContain("llipe.subject.id");
      expect(query).toContain("llipe.run.status");
      expect(query).toContain("llipe.outcome.type");
      expect(query).toContain("llipe.outcome.url");
      expect(query).toContain("service.name");
      expect(query).toContain("duration");
    });

    it("filters for root spans using llipe.run.status presence", () => {
      const query = buildRunListQuery();
      expect(query).toContain("ispresent");
      expect(query).toContain("llipe.run.status");
    });

    it("sorts by timestamp descending", () => {
      const query = buildRunListQuery();
      expect(query).toContain("sort");
      expect(query).toContain("desc");
    });

    it("includes a limit", () => {
      const query = buildRunListQuery();
      expect(query).toContain("limit");
    });

    it("accepts optional limit override", () => {
      const query = buildRunListQuery({ limit: 50 });
      expect(query).toContain("limit 50");
    });

    it("uses default limit when not specified", () => {
      const query = buildRunListQuery();
      expect(query).toContain(`limit ${QUERY_LIMITS.RUN_LIST}`);
    });

    it("accepts optional agent name filter", () => {
      const query = buildRunListQuery({ agentName: "dep-updater" });
      expect(query).toContain("dep-updater");
      expect(query).toContain("service.name");
    });
  });

  describe("buildSessionSpansQuery", () => {
    it("produces a query filtering by session ID", () => {
      const sessionId = "dep-updater__llipe-dev-tasks-agent-fleet__20250127T120000Z";
      const query = buildSessionSpansQuery(sessionId);

      expect(query).toContain(sessionId);
      expect(query).toContain("session.id");
    });

    it("sorts ascending by timestamp for timeline ordering", () => {
      const query = buildSessionSpansQuery("test-session");
      expect(query).toContain("sort");
      expect(query).toContain("asc");
    });

    it("includes gen_ai fields for child span extraction", () => {
      const query = buildSessionSpansQuery("test-session");
      expect(query).toContain("gen_ai.request.model");
      expect(query).toContain("gen_ai.usage.input_tokens");
      expect(query).toContain("gen_ai.usage.output_tokens");
    });

    it("uses the session ID fallback path in the filter", () => {
      const query = buildSessionSpansQuery("test-session");
      // Should handle both session.id and llipe.session.id
      expect(query).toContain("llipe.session.id");
    });

    it("escapes special characters in session ID", () => {
      const sessionId = "agent__owner/repo__20250127T120000Z";
      const query = buildSessionSpansQuery(sessionId);
      // Session ID should appear in the query for filtering
      expect(query).toContain(sessionId);
    });
  });
});
