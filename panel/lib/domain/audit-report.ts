/**
 * `audit_report` artifact metadata parser (issue #241).
 *
 * `run_artifacts.metadata` is agent-authored, therefore untrusted (spec §12 —
 * the same posture guard #5 takes for `url`). This module turns that JSON into
 * a view the run-detail page can render as TEXT. It is pure and TOTAL: for any
 * `Json` input it returns a normalized view or `null`, and it never throws.
 * It never interprets strings — a `<script>` in a message is data, passed
 * through unchanged for React to escape.
 *
 * Recognized shape — the security-analyst agent's `build_audit_report()` /
 * `build_fix_audit_report()` (`agents/security-analyst/.../main.py`):
 *
 *   { total_findings, by_bucket: { mechanical: [...], manual: [...],
 *     unscannable: [...] }, by_tool: {tool: n}, by_severity: {sev: n},
 *     findings_before?: {bucket: n}, findings_after?: {bucket: n} }
 *
 * Anything else (dependency-update's flat "Audit Report" summary, a future
 * agent, garbage) returns `null`; the component then shows a generic
 * key/value fallback built by `flattenForFallback()`.
 */

import type { Json } from "@/lib/supabase/types";

/** Hard cap on rendered rows/entries — a hostile payload must not DoS the page. */
export const MAX_ROWS = 500;

export const BUCKETS = ["mechanical", "manual", "unscannable"] as const;
export type Bucket = (typeof BUCKETS)[number];

export interface FindingRow {
  tool: string;
  bucket: Bucket;
  ruleId: string;
  severity: string;
  filePath: string;
  lineStart: number | null;
  message: string;
}

export type BucketCounts = Record<Bucket, number>;

export interface AuditReportView {
  totalFindings: number;
  rows: FindingRow[];
  /** Rows dropped past `MAX_ROWS`; 0 when nothing was cut. */
  truncated: number;
  byTool: [string, number][];
  bySeverity: [string, number][];
  /** Present only for fix-mode reports (`findings_before`/`findings_after`). */
  beforeAfter: { before: BucketCounts; after: BucketCounts } | null;
}

const PLACEHOLDER = "—";

type JsonObject = { [key: string]: Json };

function isObject(value: Json | undefined): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Scalar → string; objects/arrays/null → placeholder. Never interprets content. */
function text(value: Json | undefined): string {
  if (typeof value === "string") return value.length > 0 ? value : PLACEHOLDER;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return PLACEHOLDER;
}

function integer(value: Json | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? Math.trunc(value) : null;
}

function counts(value: Json | undefined): [string, number][] {
  if (!isObject(value)) return [];
  return Object.entries(value)
    .filter((entry): entry is [string, number] => typeof entry[1] === "number")
    .slice(0, MAX_ROWS);
}

function bucketCounts(value: Json | undefined): BucketCounts | null {
  if (!isObject(value)) return null;
  const out = {} as BucketCounts;
  for (const bucket of BUCKETS) {
    const n = integer(value[bucket]);
    if (n === null) return null;
    out[bucket] = n;
  }
  return out;
}

function toRow(entry: Json, bucket: Bucket): FindingRow | null {
  if (!isObject(entry)) return null;
  return {
    tool: text(entry.tool),
    bucket,
    ruleId: text(entry.rule_id),
    severity: text(entry.severity),
    filePath: text(entry.file_path),
    lineStart: integer(entry.line_start),
    message: text(entry.message),
  };
}

export function parseAuditReport(metadata: Json | null | undefined): AuditReportView | null {
  if (!isObject(metadata)) return null;
  const byBucket = metadata.by_bucket;
  if (!isObject(byBucket)) return null;
  if (!BUCKETS.some((b) => Array.isArray(byBucket[b]))) return null;

  const all: FindingRow[] = [];
  for (const bucket of BUCKETS) {
    const entries = byBucket[bucket];
    if (!Array.isArray(entries)) continue;
    for (const entry of entries) {
      const row = toRow(entry, bucket);
      if (row) all.push(row);
    }
  }

  const rows = all.slice(0, MAX_ROWS);
  const before = bucketCounts(metadata.findings_before);
  const after = bucketCounts(metadata.findings_after);
  const total = integer(metadata.total_findings);

  return {
    totalFindings: total ?? all.length,
    rows,
    truncated: all.length - rows.length,
    byTool: counts(metadata.by_tool),
    bySeverity: counts(metadata.by_severity),
    beforeAfter: before && after ? { before, after } : null,
  };
}

/**
 * Generic `[key, string]` pairs for an unrecognized metadata object — the
 * fallback view. Nested values are compact JSON; scalars are stringified.
 */
export function flattenForFallback(metadata: Json | null | undefined): [string, string][] {
  if (!isObject(metadata)) return [];
  return Object.entries(metadata)
    .slice(0, MAX_ROWS)
    .map(([key, value]) => [
      key,
      typeof value === "string" ? value : (JSON.stringify(value) ?? String(value)),
    ]);
}
