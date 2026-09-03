import { describe, expect, it } from "vitest";

// The audit gate's decision logic is pure and unit-testable in isolation from
// the network. These tests pin the security-critical distinction: a real
// high/critical advisory MUST be counted as blocking, a clean or
// moderate-only audit MUST NOT, and a registry transport failure MUST be
// recognized so it can be soft-passed (never a vuln swallowed). The .mjs
// helper has no type declarations; allowJs lets TS infer them.
import { countBlocking, looksLikeTransportError, tryParseJson } from "../../scripts/audit.mjs";

describe("countBlocking — severity gate (>= high fails)", () => {
  it("counts high + critical from the metadata.vulnerabilities map", () => {
    const parsed = {
      metadata: { vulnerabilities: { info: 0, low: 2, moderate: 1, high: 3, critical: 1 } },
    };
    expect(countBlocking(parsed)).toBe(4);
  });

  it("returns 0 when only moderate/low advisories exist (below the gate)", () => {
    const parsed = {
      metadata: { vulnerabilities: { info: 1, low: 5, moderate: 1, high: 0, critical: 0 } },
    };
    // This is the current real state (1 moderate ajv advisory) — must pass.
    expect(countBlocking(parsed)).toBe(0);
  });

  it("returns 0 for a fully clean audit", () => {
    const parsed = {
      metadata: { vulnerabilities: { info: 0, low: 0, moderate: 0, high: 0, critical: 0 } },
    };
    expect(countBlocking(parsed)).toBe(0);
  });

  it("falls back to scanning an advisories map when no metadata counts exist", () => {
    const parsed = {
      advisories: {
        "1": { severity: "critical" },
        "2": { severity: "moderate" },
        "3": { severity: "HIGH" }, // case-insensitive
      },
    };
    expect(countBlocking(parsed)).toBe(2);
  });

  it("returns 0 for an empty/absent advisory payload", () => {
    expect(countBlocking({})).toBe(0);
    expect(countBlocking({ advisories: {} })).toBe(0);
  });
});

describe("tryParseJson — verdict extraction", () => {
  it("parses a well-formed pnpm --json object", () => {
    const out = JSON.stringify({ metadata: { vulnerabilities: { high: 0 } } });
    expect(tryParseJson(out)).not.toBeNull();
  });

  it("extracts the JSON object even with surrounding noise", () => {
    const out = `some warning\n${JSON.stringify({ metadata: {} })}\ntrailing`;
    expect(tryParseJson(out)).toEqual({ metadata: {} });
  });

  it("returns null for empty or non-JSON output (a non-verdict)", () => {
    expect(tryParseJson("")).toBeNull();
    expect(tryParseJson("ERR_SOCKET_TIMEOUT")).toBeNull();
    expect(tryParseJson("{not valid json")).toBeNull();
  });
});

describe("looksLikeTransportError — transient network detection", () => {
  it.each([
    "ERR_SOCKET_TIMEOUT",
    "request to https://registry.npmjs.org/-/npm/v1/security/audits failed, reason: Socket timeout",
    "getaddrinfo ENOTFOUND registry.npmjs.org",
    "ECONNRESET",
    "ETIMEDOUT",
  ])("classifies %s as a transport error", (text) => {
    expect(looksLikeTransportError(text)).toBe(true);
  });

  it("does NOT classify a real advisory verdict as a transport error", () => {
    const verdict = JSON.stringify({ metadata: { vulnerabilities: { critical: 1 } } });
    expect(looksLikeTransportError(verdict)).toBe(false);
  });

  it("returns false for empty input", () => {
    expect(looksLikeTransportError("")).toBe(false);
  });
});
