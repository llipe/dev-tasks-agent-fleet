import { describe, expect, it } from "vitest";

import {
  MAX_ROWS,
  flattenForFallback,
  parseAuditReport,
  type FindingRow,
} from "@/lib/domain/audit-report";
import type { Json } from "@/lib/supabase/types";

/**
 * Layer 1 (unit) — `audit_report` artifact metadata parser (issue #241).
 *
 * `run_artifacts.metadata` is agent-authored, therefore untrusted (spec §12,
 * same posture as guard #5 for `url`). The parser is pure and TOTAL: for ANY
 * `Json` input it returns either a normalized `AuditReportView` (when the
 * security-analyst shape is recognized) or `null` (any other shape), and it
 * never throws. It never interprets strings — hostile content passes through
 * unchanged as data for the component to render as text.
 */

function finding(overrides: Partial<Record<string, Json>> = {}): { [key: string]: Json } {
  return {
    tool: "gitleaks",
    bucket: "unscannable",
    rule_id: "generic-api-key",
    severity: "critical",
    file_path: "workstream/spec.md",
    line_start: 190,
    line_end: 190,
    message: "Detected a Generic API Key (gitleaks rule: generic-api-key)",
    cwe_or_category: "generic-api-key",
    remediation_kind: null,
    reported_by: ["gitleaks"],
    ...overrides,
  };
}

/** The shape `build_audit_report()` / `build_fix_audit_report()` persist. */
function securityAnalystReport(overrides: Partial<Record<string, Json>> = {}): Json {
  return {
    total_findings: 3,
    by_bucket: {
      mechanical: [
        finding({
          tool: "semgrep",
          bucket: "mechanical",
          rule_id: "js.crypto.md5",
          severity: "high",
          file_path: "src/hash.js",
          line_start: 12,
          line_end: 12,
          message: "MD5 is weak",
          remediation_kind: "semgrep_autofix",
        }),
      ],
      manual: [
        finding({
          tool: "trivy",
          bucket: "manual",
          rule_id: "CVE-2024-0001",
          severity: "medium",
          file_path: "package-lock.json",
          line_start: 0,
          line_end: 0,
          message: "lodash < 4.17.21",
          remediation_kind: "version_bump",
        }),
      ],
      unscannable: [finding()],
    },
    by_tool: { semgrep: 1, trivy: 1, gitleaks: 1 },
    by_severity: { high: 1, medium: 1, critical: 1 },
    ...overrides,
  };
}

describe("parseAuditReport — security-analyst shape", () => {
  it("returns one row per finding, in bucket order mechanical → manual → unscannable", () => {
    const view = parseAuditReport(securityAnalystReport());
    expect(view).not.toBeNull();
    expect(view!.rows.map((r) => r.bucket)).toEqual(["mechanical", "manual", "unscannable"]);
    expect(view!.rows.map((r) => r.tool)).toEqual(["semgrep", "trivy", "gitleaks"]);
  });

  it("normalizes every column of a row", () => {
    const view = parseAuditReport(securityAnalystReport());
    const row: FindingRow = view!.rows[2];
    expect(row).toEqual({
      tool: "gitleaks",
      bucket: "unscannable",
      ruleId: "generic-api-key",
      severity: "critical",
      filePath: "workstream/spec.md",
      lineStart: 190,
      message: "Detected a Generic API Key (gitleaks rule: generic-api-key)",
    });
  });

  it("carries totals, by-tool, and by-severity counts", () => {
    const view = parseAuditReport(securityAnalystReport());
    expect(view!.totalFindings).toBe(3);
    expect(view!.byTool).toEqual([
      ["semgrep", 1],
      ["trivy", 1],
      ["gitleaks", 1],
    ]);
    expect(view!.bySeverity).toEqual([
      ["high", 1],
      ["medium", 1],
      ["critical", 1],
    ]);
  });

  it("surfaces findings_before/findings_after when present (fix mode)", () => {
    const view = parseAuditReport(
      securityAnalystReport({
        findings_before: { mechanical: 1, manual: 1, unscannable: 1 },
        findings_after: { mechanical: 0, manual: 1, unscannable: 1 },
      }),
    );
    expect(view!.beforeAfter).toEqual({
      before: { mechanical: 1, manual: 1, unscannable: 1 },
      after: { mechanical: 0, manual: 1, unscannable: 1 },
    });
  });

  it("leaves beforeAfter null when absent (audit_only mode)", () => {
    expect(parseAuditReport(securityAnalystReport())!.beforeAfter).toBeNull();
  });

  it("leaves beforeAfter null when only one side is present or a bucket count is malformed", () => {
    const onlyBefore = securityAnalystReport({
      findings_before: { mechanical: 1, manual: 1, unscannable: 1 },
    });
    expect(parseAuditReport(onlyBefore)!.beforeAfter).toBeNull();

    const malformedAfter = securityAnalystReport({
      findings_before: { mechanical: 1, manual: 1, unscannable: 1 },
      findings_after: { mechanical: "0", manual: 1, unscannable: 1 },
    });
    expect(parseAuditReport(malformedAfter)!.beforeAfter).toBeNull();
  });

  it("tolerates a missing bucket key and derives total_findings from the rows when absent", () => {
    const view = parseAuditReport({
      by_bucket: { mechanical: [finding(), finding()] },
    });
    expect(view).not.toBeNull();
    expect(view!.rows).toHaveLength(2);
    expect(view!.totalFindings).toBe(2);
  });

  it("returns an empty view (not null) for total_findings: 0", () => {
    const view = parseAuditReport({
      total_findings: 0,
      by_bucket: { mechanical: [], manual: [], unscannable: [] },
      by_tool: {},
      by_severity: {},
    });
    expect(view).not.toBeNull();
    expect(view!.rows).toEqual([]);
    expect(view!.totalFindings).toBe(0);
  });

  it("fills placeholders for missing optional fields instead of throwing", () => {
    const view = parseAuditReport(
      securityAnalystReport({
        total_findings: 1,
        by_bucket: { mechanical: [], manual: [], unscannable: [{ tool: "gitleaks" }] },
      }),
    );
    expect(view!.rows).toHaveLength(1);
    expect(view!.rows[0]).toEqual({
      tool: "gitleaks",
      bucket: "unscannable",
      ruleId: "—",
      severity: "—",
      filePath: "—",
      lineStart: null,
      message: "—",
    });
  });

  it("skips non-object entries inside a bucket rather than throwing", () => {
    const view = parseAuditReport(
      securityAnalystReport({
        total_findings: 2,
        by_bucket: { mechanical: [], manual: ["junk", 42, null], unscannable: [finding()] },
      }),
    );
    expect(view!.rows).toHaveLength(1);
  });

  it("coerces non-string scalars to strings and ignores nested objects in string fields", () => {
    const view = parseAuditReport(
      securityAnalystReport({
        total_findings: 1,
        by_bucket: {
          mechanical: [],
          manual: [],
          unscannable: [finding({ rule_id: 7, message: { nested: true }, line_start: "12" })],
        },
      }),
    );
    expect(view!.rows[0].ruleId).toBe("7");
    expect(view!.rows[0].message).toBe("—");
    expect(view!.rows[0].lineStart).toBeNull();
  });
});

describe("parseAuditReport — hostile content is data, never interpreted", () => {
  it("passes <script> and javascript: strings through untouched", () => {
    const hostile = "<script>alert(1)</script> javascript:alert(1) <img src=x onerror=alert(1)>";
    const view = parseAuditReport(
      securityAnalystReport({
        total_findings: 1,
        by_bucket: {
          mechanical: [],
          manual: [],
          unscannable: [finding({ message: hostile, file_path: hostile, rule_id: hostile })],
        },
      }),
    );
    expect(view!.rows[0].message).toBe(hostile);
    expect(view!.rows[0].filePath).toBe(hostile);
    expect(view!.rows[0].ruleId).toBe(hostile);
  });

  it("caps rows at MAX_ROWS and reports how many were truncated", () => {
    const many = Array.from({ length: MAX_ROWS + 25 }, (_, i) => finding({ line_start: i }));
    const view = parseAuditReport(
      securityAnalystReport({
        total_findings: many.length,
        by_bucket: { mechanical: [], manual: [], unscannable: many },
      }),
    );
    expect(view!.rows).toHaveLength(MAX_ROWS);
    expect(view!.truncated).toBe(25);
  });

  it("reports truncated: 0 when under the cap", () => {
    expect(parseAuditReport(securityAnalystReport())!.truncated).toBe(0);
  });
});

describe("parseAuditReport — unknown shapes return null, never throw", () => {
  it.each<[string, Json]>([
    ["null", null],
    ["a string", "audit"],
    ["a number", 3],
    ["an array", [1, 2, 3]],
    ["an empty object", {}],
    ["dependency-update's flat summary", { total: 2, major_required: 1, updated: ["a"] }],
    ["by_bucket that is not an object", { total_findings: 1, by_bucket: "nope" }],
    ["by_bucket missing every bucket", { total_findings: 1, by_bucket: { other: [] } }],
  ])("returns null for %s", (_label, input) => {
    expect(parseAuditReport(input)).toBeNull();
  });
});

describe("flattenForFallback — generic key/value view for unknown shapes", () => {
  it("flattens a shallow object to [key, string] pairs in key order", () => {
    expect(flattenForFallback({ total: 2, ok: true, name: "x", nothing: null })).toEqual([
      ["total", "2"],
      ["ok", "true"],
      ["name", "x"],
      ["nothing", "null"],
    ]);
  });

  it("serializes nested values as compact JSON strings", () => {
    expect(flattenForFallback({ updated: ["a", "b"], meta: { k: 1 } })).toEqual([
      ["updated", '["a","b"]'],
      ["meta", '{"k":1}'],
    ]);
  });

  it("returns [] for non-object input", () => {
    expect(flattenForFallback(null)).toEqual([]);
    expect(flattenForFallback("str")).toEqual([]);
    expect(flattenForFallback([1])).toEqual([]);
  });

  it("caps entries at MAX_ROWS", () => {
    const big: { [key: string]: Json } = {};
    for (let i = 0; i < MAX_ROWS + 5; i++) big[`k${i}`] = i;
    expect(flattenForFallback(big)).toHaveLength(MAX_ROWS);
  });
});
