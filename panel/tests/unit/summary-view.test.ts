import { describe, expect, it } from "vitest";

import { legendSegments, outcomeLabel } from "@/components/dashboard/summary-view";
import type { AgentSummary } from "@/lib/domain/dashboard";

/**
 * Layer 1 tests for the shared dashboard presentation mapping (task 2.6/2.7).
 * The outcome→label table is the DESIGN §8.2 contract; every arm is asserted
 * so a renamed/added outcome is caught here rather than in three component
 * suites.
 */

describe("outcomeLabel — every §8.2 arm", () => {
  it.each([
    ["fixed", "FIXED"],
    ["no_vulnerabilities", "NO VULNS"],
    ["partial", "PARTIAL"],
    ["needs_review", "NEEDS REVIEW"],
    ["not_applicable", "N/A"],
  ] as const)("maps %s → %s", (outcome, label) => {
    expect(outcomeLabel(outcome)).toBe(label);
  });

  it("maps a null/pending outcome to the em-dash placeholder", () => {
    expect(outcomeLabel(null)).toBe("—");
  });
});

describe("legendSegments", () => {
  function summary(legend: { ok: number; fail: number; timeout: number }): AgentSummary {
    return {
      id: "a",
      slug: "s",
      name: "n",
      description: null,
      requiresRepository: false,
      runCount: legend.ok + legend.fail + legend.timeout,
      breakdown: {
        queued: 0,
        running: 0,
        succeeded: legend.ok,
        failed: legend.fail,
        timed_out: legend.timeout,
        failed_to_start: 0,
        canceled: 0,
      },
      legend,
      lastRun: null,
      recentRuns: [],
    };
  }

  it("returns an empty segment list for zero runs (bar renders empty track)", () => {
    expect(legendSegments(summary({ ok: 0, fail: 0, timeout: 0 }))).toEqual([]);
  });

  it("emits one tokenized segment per non-zero bucket, summing to 100%", () => {
    const segs = legendSegments(summary({ ok: 2, fail: 1, timeout: 1 }));
    expect(segs.map((s) => s.colorVar)).toEqual([
      "var(--st-ok)",
      "var(--st-fail)",
      "var(--st-timeout)",
    ]);
    const total = segs.reduce((sum, s) => sum + s.percent, 0);
    expect(Math.round(total)).toBe(100);
    // never a literal color
    for (const s of segs) expect(s.colorVar.startsWith("var(--")).toBe(true);
  });

  it("omits zero buckets", () => {
    const segs = legendSegments(summary({ ok: 3, fail: 0, timeout: 0 }));
    expect(segs).toHaveLength(1);
    expect(segs[0].percent).toBe(100);
  });
});
