import { describe, it, expect } from "vitest";
import {
  SPANS_LOG_GROUP,
  SPANS_LOG_STREAM,
  SPANS_RETENTION_DAYS,
} from "./observability-config.js";

/**
 * REGRESSION GUARD (issue #62).
 *
 * The span destination has been corrected three times:
 *
 *   1. `/aws/vendedlogs/agentcore/dep-updater/spans` — never existed (D2, #56)
 *   2. `aws/spans` — existed, then was deleted from the account. AWS reserves
 *      that name and rejects manual recreation. (#62 first attempt)
 *   3. Per-agent log group — AgentCore creates and owns this group. Spans land
 *      in the `spans` stream within it. Stable and observable. (#62 final)
 *
 * These assertions pin the current value so any future change is deliberate.
 */
describe("SPANS_LOG_GROUP", () => {
  it("is the dep-updater agent's own log group (per-agent destination)", () => {
    expect(SPANS_LOG_GROUP).toBe(
      "/aws/bedrock-agentcore/runtimes/depupdater_dep_updater-M4gkuL4wSr-DEFAULT",
    );
  });

  it("is not the shared aws/spans group, which no longer exists in the account", () => {
    expect(SPANS_LOG_GROUP).not.toBe("aws/spans");
  });

  it("is not the AgentCore vendedlogs path, which never existed", () => {
    expect(SPANS_LOG_GROUP).not.toContain("vendedlogs");
  });

  it("starts with a leading slash (standard CloudWatch log group format)", () => {
    expect(SPANS_LOG_GROUP.startsWith("/")).toBe(true);
  });
});

describe("SPANS_LOG_STREAM", () => {
  it("is 'spans' — the stream AgentCore writes spans to in per-agent mode", () => {
    expect(SPANS_LOG_STREAM).toBe("spans");
  });
});

describe("SPANS_RETENTION_DAYS", () => {
  it("is 30 days, matching the control plane's maximum date-range filter", () => {
    expect(SPANS_RETENTION_DAYS).toBe(30);
  });
});
