import { describe, expect, it } from "vitest";
import { safeRedirectTarget } from "@/lib/auth/redirect";

// Layer 1 unit coverage for the open-redirect guard (S-116, spec §8.1, AC4).
// Total, never-throwing: every rejected input collapses to "/". This is a
// security guard, so the rejection table is exhaustive.

describe("safeRedirectTarget — rejects off-origin / unsafe values (→ '/')", () => {
  it.each([
    ["protocol-relative //evil.com", "//evil.com"],
    ["absolute https", "https://evil.com"],
    ["absolute http", "http://x"],
    ["javascript scheme", "javascript:alert(1)"],
    ["backslash-escaped root", "/\\evil"],
    ["scheme smuggled mid-string", "/redirect?next=https://evil.com/../"],
    ["newline injection", "/ok\nSet-Cookie: x=1"],
    ["carriage return injection", "/ok\rHeader: y"],
    ["tab control char", "/ok\ttail"],
    ["null byte", "/ok\u0000"],
    ["not rooted", "relative/path"],
    ["bare word", "dashboard"],
    ["login loop", "/login"],
    ["login loop with query", "/login?redirect=%2F"],
  ])("rejects %s", (_label, input) => {
    expect(safeRedirectTarget(input)).toBe("/");
  });

  it.each([
    ["empty string", ""],
    ["undefined", undefined],
    ["null", null],
    ["number", 42],
    ["object", {}],
  ])("returns '/' for %s", (_label, input) => {
    expect(safeRedirectTarget(input)).toBe("/");
  });
});

describe("safeRedirectTarget — preserves safe same-origin relative paths", () => {
  it("returns a simple rooted path unchanged", () => {
    expect(safeRedirectTarget("/agents/foo")).toBe("/agents/foo");
  });

  it("preserves query and hash", () => {
    expect(safeRedirectTarget("/runs/01J8XQ2F?tab=logs#L42")).toBe("/runs/01J8XQ2F?tab=logs#L42");
  });

  it("allows the root path", () => {
    expect(safeRedirectTarget("/")).toBe("/");
  });

  it("allows a long but legitimate path", () => {
    const long = "/agents/" + "a".repeat(2000);
    expect(safeRedirectTarget(long)).toBe(long);
  });

  it("does not decode percent-encoded slashes into a new meaning", () => {
    // %2F%2F stays a literal path segment; it is not protocol-relative.
    expect(safeRedirectTarget("/x%2F%2Fy")).toBe("/x%2F%2Fy");
  });

  it("never throws for any input", () => {
    const inputs: unknown[] = [Symbol("s"), 0, NaN, [], () => 1, "/\u{1F600}/unicode"];
    for (const i of inputs) {
      expect(() => safeRedirectTarget(i)).not.toThrow();
    }
  });
});
