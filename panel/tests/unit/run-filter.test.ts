import { describe, expect, it } from "vitest";

import {
  escapeIlikeWildcards,
  parseRunFilter,
  serializeRunFilter,
  STATUS_FILTER_ORDER,
  type RunFilter,
} from "@/lib/domain/run-filter";

/**
 * Layer 1 (unit) tests for the Run History filter/pagination model (S-143,
 * spec §8.1, CT-1).
 *
 * Load-bearing properties:
 *  - `parseRunFilter` is TOTAL — it never throws for any `URLSearchParams`,
 *    including one built from a malformed raw query string, and every unknown
 *    value falls back to its documented default.
 *  - `serializeRunFilter` omits every field at its default so the unfiltered
 *    URL stays bare (`?status=all` is never written).
 *  - `parseRunFilter(serializeRunFilter(f))` round-trips for every valid
 *    `RunFilter` (CT-1).
 *  - `escapeIlikeWildcards` neutralizes `%`/`_`/`\` so search stays a literal
 *    substring match (spec §8.1 v1.1 addendum).
 */

function defaultFilter(): RunFilter {
  return { status: "all", repositoryId: null, search: null, agentSlug: null, page: 1 };
}

describe("parseRunFilter — defaults and fallbacks", () => {
  it("returns the all-default filter for an empty query string", () => {
    expect(parseRunFilter(new URLSearchParams(""))).toEqual(defaultFilter());
  });

  it("parses every known status", () => {
    for (const status of [
      "queued",
      "running",
      "succeeded",
      "failed",
      "timed_out",
      "failed_to_start",
      "canceled",
    ]) {
      expect(parseRunFilter(new URLSearchParams(`status=${status}`)).status).toBe(status);
    }
  });

  it("falls back an unknown status value to 'all', never throwing", () => {
    expect(parseRunFilter(new URLSearchParams("status=bogus")).status).toBe("all");
    expect(parseRunFilter(new URLSearchParams("status=")).status).toBe("all");
  });

  it("reads repositoryId, falling back to null when absent or empty", () => {
    expect(parseRunFilter(new URLSearchParams("repo=abc-123")).repositoryId).toBe("abc-123");
    expect(parseRunFilter(new URLSearchParams("")).repositoryId).toBeNull();
    expect(parseRunFilter(new URLSearchParams("repo=")).repositoryId).toBeNull();
  });

  it("reads search, falling back to null when absent or empty", () => {
    expect(parseRunFilter(new URLSearchParams("q=foo")).search).toBe("foo");
    expect(parseRunFilter(new URLSearchParams("")).search).toBeNull();
    expect(parseRunFilter(new URLSearchParams("q=")).search).toBeNull();
  });

  it("reads agentSlug, falling back to null when absent (meaningful only on /runs)", () => {
    expect(parseRunFilter(new URLSearchParams("agent=dependency-update")).agentSlug).toBe(
      "dependency-update",
    );
    expect(parseRunFilter(new URLSearchParams("")).agentSlug).toBeNull();
  });

  it("parses a valid page number", () => {
    expect(parseRunFilter(new URLSearchParams("page=3")).page).toBe(3);
  });

  it("falls back page to 1 for zero, negative, non-numeric, or missing values", () => {
    expect(parseRunFilter(new URLSearchParams("page=0")).page).toBe(1);
    expect(parseRunFilter(new URLSearchParams("page=-5")).page).toBe(1);
    expect(parseRunFilter(new URLSearchParams("page=abc")).page).toBe(1);
    expect(parseRunFilter(new URLSearchParams("page=")).page).toBe(1);
    expect(parseRunFilter(new URLSearchParams("")).page).toBe(1);
  });

  it("never throws for a malformed raw query string (adversarial table)", () => {
    const adversarial = [
      "%",
      "%%",
      "%zz",
      "?????",
      "status=%&repo=%GG&q=%E0%A4%A",
      "a=b&a=c&a=d",
      "=====",
      "\uD800", // lone surrogate
      "status[]=failed",
      "page=99999999999999999999999999999999",
      "page=1e10",
      "page=Infinity",
      "page=NaN",
      "q=" + "x".repeat(5000),
      "\0\0\0",
      "status=running&status=failed",
      "repo=../../etc/passwd",
    ];
    for (const raw of adversarial) {
      expect(() => parseRunFilter(new URLSearchParams(raw))).not.toThrow();
    }
  });
});

describe("serializeRunFilter — default omission", () => {
  it("serializes the all-default filter to an empty URLSearchParams", () => {
    expect(serializeRunFilter(defaultFilter()).toString()).toBe("");
  });

  it("omits status=all but includes a non-default status", () => {
    expect(serializeRunFilter({ ...defaultFilter(), status: "all" }).toString()).toBe("");
    expect(serializeRunFilter({ ...defaultFilter(), status: "failed" }).toString()).toBe(
      "status=failed",
    );
  });

  it("omits page=1 but includes a non-default page", () => {
    expect(serializeRunFilter({ ...defaultFilter(), page: 1 }).toString()).toBe("");
    expect(serializeRunFilter({ ...defaultFilter(), page: 2 }).get("page")).toBe("2");
  });

  it("omits a null/empty repositoryId, search, or agentSlug", () => {
    const s = serializeRunFilter({
      ...defaultFilter(),
      repositoryId: "",
      search: "   ",
      agentSlug: null,
    });
    expect(s.toString()).toBe("");
  });

  it("includes repositoryId, search, and agentSlug when set", () => {
    const s = serializeRunFilter({
      status: "failed",
      repositoryId: "repo-1",
      search: "my_run",
      agentSlug: null,
      page: 2,
    });
    expect(s.get("status")).toBe("failed");
    expect(s.get("repo")).toBe("repo-1");
    expect(s.get("q")).toBe("my_run");
    expect(s.get("page")).toBe("2");
  });
});

describe("round-trip (CT-1)", () => {
  const cases: RunFilter[] = [
    defaultFilter(),
    { status: "failed", repositoryId: null, search: null, agentSlug: null, page: 1 },
    { status: "timed_out", repositoryId: "repo-9", search: "foo", agentSlug: null, page: 3 },
    {
      status: "all",
      repositoryId: "repo-9",
      search: null,
      agentSlug: "dependency-update",
      page: 1,
    },
    { status: "queued", repositoryId: null, search: "org/repo", agentSlug: "sec-scan", page: 12 },
  ];

  it.each(cases)("parseRunFilter(serializeRunFilter(f)) === f for %j", (filter) => {
    const roundTripped = parseRunFilter(serializeRunFilter(filter));
    expect(roundTripped).toEqual(filter);
  });

  it("is idempotent on a second application (fuzz-safe malformed inputs too)", () => {
    const raws = ["status=bogus&page=-1", "repo=&q=%25%25", "agent=x&page=9999"];
    for (const raw of raws) {
      const once = parseRunFilter(new URLSearchParams(raw));
      const twice = parseRunFilter(serializeRunFilter(once));
      expect(twice).toEqual(once);
    }
  });
});

describe("STATUS_FILTER_ORDER", () => {
  it("lists every known status once, plus 'all' last", () => {
    expect(STATUS_FILTER_ORDER).toEqual([
      "queued",
      "running",
      "succeeded",
      "failed",
      "timed_out",
      "failed_to_start",
      "all",
    ]);
  });
});

describe("escapeIlikeWildcards", () => {
  it("escapes % and _ so they match literally", () => {
    expect(escapeIlikeWildcards("my_repo")).toBe("my\\_repo");
    expect(escapeIlikeWildcards("100%done")).toBe("100\\%done");
  });

  it("escapes a literal backslash first, so it is not double-escaped by later steps", () => {
    expect(escapeIlikeWildcards("a\\b")).toBe("a\\\\b");
    expect(escapeIlikeWildcards("a\\_b")).toBe("a\\\\\\_b");
  });

  it("leaves a plain alphanumeric string untouched", () => {
    expect(escapeIlikeWildcards("dependency-update")).toBe("dependency-update");
  });

  it("never throws for unicode/emoji/very-long strings", () => {
    const long = "🔥".repeat(2000) + "%_\\" + "x".repeat(5000);
    expect(() => escapeIlikeWildcards(long)).not.toThrow();
  });
});
