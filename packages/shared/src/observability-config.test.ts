import { describe, it, expect } from "vitest";
import { SPANS_LOG_GROUP, SPANS_RETENTION_DAYS } from "./observability-config.js";

/**
 * REGRESSION GUARD (issue #56, defect D2).
 *
 * `SPANS_LOG_GROUP` used to read `/aws/vendedlogs/agentcore/dep-updater/spans`,
 * a group that does not exist in the account. Spans actually land in `aws/spans`
 * — which is what the specification resolved PRD open question #1 to ("Shared
 * `aws/spans` log group"). Because every control-plane query builder asserts
 * against the constant rather than a literal, no existing test could catch the
 * drift, and the runs view (S-016, S-017) could only ever return empty.
 *
 * These assertions pin the value itself, so a future edit has to change this
 * test deliberately.
 */
describe("SPANS_LOG_GROUP", () => {
  it("is the shared aws/spans group", () => {
    expect(SPANS_LOG_GROUP).toBe("aws/spans");
  });

  it("is not the AgentCore vendedlogs path, which does not exist", () => {
    expect(SPANS_LOG_GROUP).not.toContain("vendedlogs");
  });

  it("is not per-agent — spans from every agent share one group", () => {
    expect(SPANS_LOG_GROUP).not.toContain("dep-updater");
  });

  /**
   * `aws/spans` is intentionally unprefixed by a leading slash: that is the
   * literal name CloudWatch Transaction Search creates, and Logs Insights
   * `StartQuery` rejects a name that does not match exactly.
   */
  it("has no leading slash", () => {
    expect(SPANS_LOG_GROUP.startsWith("/")).toBe(false);
  });
});

describe("SPANS_RETENTION_DAYS", () => {
  it("is 30 days, matching the control plane's maximum date-range filter", () => {
    expect(SPANS_RETENTION_DAYS).toBe(30);
  });
});
