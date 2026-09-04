import type { AgentSummary } from "@/lib/domain/dashboard";
import type { RunOutcome } from "@/lib/supabase/types";
import type { StatusBarSegment } from "@/components/StatusBar";

/**
 * Presentation helpers shared by the three dashboard variants, kept out of the
 * components so the mapping (outcome → label, breakdown → bar segments) is
 * asserted once in a unit test rather than three times in component tests.
 */

/** Outcome tag text (§8.2, uppercase). `—` for a pending/absent outcome. */
export function outcomeLabel(outcome: RunOutcome | null): string {
  switch (outcome) {
    case "fixed":
      return "FIXED";
    case "no_vulnerabilities":
      return "NO VULNS";
    case "partial":
      return "PARTIAL";
    case "needs_review":
      return "NEEDS REVIEW";
    case "not_applicable":
      return "N/A";
    default:
      return "—";
  }
}

/**
 * The three-bucket StatusBar segments (§3.8), sized by percentage of the
 * ok/fail/timeout legend total. Each segment references a status color token
 * (never a literal). A run count of zero yields an empty segment list, so the
 * bar renders just its empty track (handled by StatusBar).
 */
export function legendSegments(summary: AgentSummary): StatusBarSegment[] {
  const { ok, fail, timeout } = summary.legend;
  const total = ok + fail + timeout;
  if (total === 0) return [];
  const pct = (n: number) => (n / total) * 100;
  const segments: StatusBarSegment[] = [];
  if (ok > 0) segments.push({ colorVar: "var(--st-ok)", percent: pct(ok), label: "succeeded" });
  if (fail > 0) segments.push({ colorVar: "var(--st-fail)", percent: pct(fail), label: "failed" });
  if (timeout > 0)
    segments.push({ colorVar: "var(--st-timeout)", percent: pct(timeout), label: "timed out" });
  return segments;
}
