import { describe, expect, it } from "vitest";

import { INVALID_REPOSITORY_FORMAT, parseFullName } from "@/lib/domain/repository-input";

/**
 * Layer 1 (unit) tests for the Repositories `full_name` validator (S-147,
 * spec §8.4, PRD FR16). Pure module, no I/O.
 *
 * Load-bearing properties:
 *  - Accepts iff the TRIMMED input matches `/^[\w.-]+\/[\w.-]+$/` exactly —
 *    exactly two non-empty halves separated by a single "/" (§6 metamorphic
 *    property from the test plan: agrees with a direct regex re-check for any
 *    input, not just the fixed fixture list below).
 *  - Trims leading/trailing whitespace before validating and before returning
 *    `value` (so a value with accidental padding is stored clean).
 *  - Case-sensitive: never lowercases or otherwise normalizes case (the
 *    uniqueness constraint is a DB concern, not this validator's).
 *  - Never throws — returns a discriminated result.
 */

const REGEX = /^[\w.-]+\/[\w.-]+$/;

describe("parseFullName — valid owner/repo shapes", () => {
  it("accepts a simple owner/repo", () => {
    const result = parseFullName("llipe/dev-tasks-agent-fleet");
    expect(result).toEqual({ ok: true, value: "llipe/dev-tasks-agent-fleet" });
  });

  it("accepts dots, dashes, and underscores in either half", () => {
    const result = parseFullName("my-org.co/repo_name.js");
    expect(result).toEqual({ ok: true, value: "my-org.co/repo_name.js" });
  });

  it("trims leading/trailing whitespace before validating and returns the trimmed value", () => {
    const result = parseFullName("  llipe/dev-tasks-agent-fleet  \n");
    expect(result).toEqual({ ok: true, value: "llipe/dev-tasks-agent-fleet" });
  });

  it("is case-sensitive — preserves case exactly, never normalizes", () => {
    const result = parseFullName("Llipe/Dev-Tasks");
    expect(result).toEqual({ ok: true, value: "Llipe/Dev-Tasks" });
  });
});

describe("parseFullName — invalid shapes", () => {
  it("rejects an empty string", () => {
    expect(parseFullName("")).toEqual({ ok: false, code: INVALID_REPOSITORY_FORMAT });
  });

  it("rejects a whitespace-only string", () => {
    expect(parseFullName("   ")).toEqual({ ok: false, code: INVALID_REPOSITORY_FORMAT });
  });

  it("rejects a string with no slash", () => {
    expect(parseFullName("noslash")).toEqual({ ok: false, code: INVALID_REPOSITORY_FORMAT });
  });

  it("rejects a string with multiple slashes", () => {
    expect(parseFullName("owner/repo/extra")).toEqual({
      ok: false,
      code: INVALID_REPOSITORY_FORMAT,
    });
  });

  it("rejects a leading slash (empty owner half)", () => {
    expect(parseFullName("/repo")).toEqual({ ok: false, code: INVALID_REPOSITORY_FORMAT });
  });

  it("rejects a trailing slash (empty repo half)", () => {
    expect(parseFullName("owner/")).toEqual({ ok: false, code: INVALID_REPOSITORY_FORMAT });
  });

  it("rejects a space inside a half", () => {
    expect(parseFullName("my owner/repo")).toEqual({ ok: false, code: INVALID_REPOSITORY_FORMAT });
  });

  it("never throws for an arbitrary adversarial string", () => {
    const adversarial = [
      "///",
      "a/",
      "/a",
      "a//b",
      "🦀/🦀",
      "a\\b/c",
      "a/b\nc",
      "a".repeat(5000) + "/" + "b".repeat(5000),
      "\t/\t",
      "NaN/undefined",
    ];
    for (const input of adversarial) {
      expect(() => parseFullName(input)).not.toThrow();
    }
  });

  it("metamorphic property — accept/reject decision always agrees with a direct regex re-check", () => {
    const samples = [
      "a/b",
      "a/",
      "/a",
      "a/b/c",
      "",
      "  a/b  ",
      "a.b-c_d/e.f-g_h",
      "a b/c",
      "a/b c",
      "---/___",
      "a/b/",
      "/a/b",
    ];
    for (const raw of samples) {
      const trimmed = raw.trim();
      const expected = REGEX.test(trimmed);
      const result = parseFullName(raw);
      expect(result.ok).toBe(expected);
    }
  });
});
