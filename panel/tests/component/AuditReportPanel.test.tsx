import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

import { AuditReportPanel } from "@/components/run-detail/AuditReportPanel";
import { MAX_ROWS } from "@/lib/domain/audit-report";
import type { Json } from "@/lib/supabase/types";

/**
 * Layer 2 (component) — AuditReportPanel (issue #241).
 *
 * Renders an `audit_report` artifact's `metadata` as a findings table. Like
 * `ArtifactLinks` (AC14) it receives the artifact only — never run status —
 * so nothing can hide a report on a failed run. Metadata is untrusted
 * (spec §12): everything renders as text, never as markup or links.
 */

afterEach(() => {
  cleanup();
});

function finding(overrides: Partial<Record<string, Json>> = {}): { [key: string]: Json } {
  return {
    tool: "gitleaks",
    bucket: "unscannable",
    rule_id: "generic-api-key",
    severity: "critical",
    file_path: "workstream/specification-prd-001-mvp.md",
    line_start: 190,
    line_end: 190,
    message: "Detected a Generic API Key (gitleaks rule: generic-api-key)",
    cwe_or_category: "generic-api-key",
    ...overrides,
  };
}

const securityAnalystReport: Json = {
  total_findings: 2,
  by_bucket: {
    mechanical: [
      finding({
        tool: "semgrep",
        bucket: "mechanical",
        rule_id: "js.crypto.md5",
        severity: "high",
        file_path: "src/hash.js",
        line_start: 12,
        message: "MD5 is a weak hash",
      }),
    ],
    manual: [],
    unscannable: [finding()],
  },
  by_tool: { semgrep: 1, gitleaks: 1 },
  by_severity: { high: 1, critical: 1 },
};

describe("AuditReportPanel — security-analyst shape (AC1)", () => {
  it("renders one row per finding with tool, severity, bucket, path:line, rule, message", () => {
    render(<AuditReportPanel title="Security scan findings" metadata={securityAnalystReport} />);

    const section = screen.getByRole("region", { name: /audit report/i });
    const rows = within(section).getAllByRole("row");
    // 1 header row + 2 finding rows.
    expect(rows).toHaveLength(3);

    const gitleaksRow = rows[2];
    expect(within(gitleaksRow).getByText("gitleaks")).toBeInTheDocument();
    expect(within(gitleaksRow).getByText("critical")).toBeInTheDocument();
    expect(within(gitleaksRow).getByText("unscannable")).toBeInTheDocument();
    expect(
      within(gitleaksRow).getByText("workstream/specification-prd-001-mvp.md:190"),
    ).toBeInTheDocument();
    expect(within(gitleaksRow).getByText("generic-api-key")).toBeInTheDocument();
    expect(
      within(gitleaksRow).getByText("Detected a Generic API Key (gitleaks rule: generic-api-key)"),
    ).toBeInTheDocument();

    const semgrepRow = rows[1];
    expect(within(semgrepRow).getByText("src/hash.js:12")).toBeInTheDocument();
    expect(within(semgrepRow).getByText("mechanical")).toBeInTheDocument();
  });

  it("uses the artifact title as the table caption and shows total + per-tool counts", () => {
    render(<AuditReportPanel title="Security scan findings" metadata={securityAnalystReport} />);
    expect(screen.getByText("Security scan findings")).toBeInTheDocument();
    expect(screen.getByText(/2 findings/)).toBeInTheDocument();
    expect(screen.getByText(/semgrep 1/)).toBeInTheDocument();
    expect(screen.getByText(/gitleaks 1/)).toBeInTheDocument();
  });

  it("shows before/after bucket counts when the report is from fix mode", () => {
    render(
      <AuditReportPanel
        title="Security scan findings (after fix)"
        metadata={{
          ...(securityAnalystReport as { [key: string]: Json }),
          findings_before: { mechanical: 1, manual: 0, unscannable: 1 },
          findings_after: { mechanical: 0, manual: 0, unscannable: 1 },
        }}
      />,
    );
    expect(screen.getByText(/before/i)).toBeInTheDocument();
    expect(screen.getByText(/mechanical 1 → 0/)).toBeInTheDocument();
    expect(screen.getByText(/unscannable 1 → 1/)).toBeInTheDocument();
  });

  it("renders a path without a line number when line_start is absent", () => {
    render(
      <AuditReportPanel
        title={null}
        metadata={{
          total_findings: 1,
          by_bucket: {
            mechanical: [],
            manual: [],
            unscannable: [finding({ line_start: null, file_path: "README.md" })],
          },
          by_tool: {},
          by_severity: {},
        }}
      />,
    );
    expect(screen.getByText("README.md")).toBeInTheDocument();
  });

  it("renders an unknown severity as plain text without a tint token", () => {
    render(
      <AuditReportPanel
        title={null}
        metadata={{
          total_findings: 1,
          by_bucket: {
            mechanical: [finding({ severity: "informational" })],
            manual: [],
            unscannable: [],
          },
          by_tool: {},
          by_severity: {},
        }}
      />,
    );
    const sev = screen.getByText("informational");
    expect(sev).not.toHaveAttribute("style");
    expect(sev).not.toHaveAttribute("class");
  });

  it.each(["constructor", "__proto__", "toString"])(
    "does not resolve a prototype-key severity (%s) into a tint",
    (severity) => {
      render(
        <AuditReportPanel
          title={null}
          metadata={{
            total_findings: 1,
            by_bucket: { mechanical: [finding({ severity })], manual: [], unscannable: [] },
            by_tool: {},
            by_severity: {},
          }}
        />,
      );
      const sev = screen.getByText(severity);
      expect(sev).not.toHaveAttribute("style");
      expect(sev).not.toHaveAttribute("class");
    },
  );

  it("renders no heading element (the page owns the outline)", () => {
    const { container } = render(<AuditReportPanel title="x" metadata={{ note: "n" }} />);
    expect(container.querySelector("h1, h2, h3, h4, h5, h6")).toBeNull();
  });

  it("falls back to a generic caption when the artifact has no title", () => {
    render(<AuditReportPanel title={null} metadata={securityAnalystReport} />);
    expect(screen.getByText("Audit report")).toBeInTheDocument();
  });

  it("notes how many rows were cut when the payload exceeds MAX_ROWS", () => {
    const many = Array.from({ length: MAX_ROWS + 3 }, (_, i) => finding({ line_start: i }));
    render(
      <AuditReportPanel
        title="Big"
        metadata={{
          total_findings: many.length,
          by_bucket: { mechanical: [], manual: [], unscannable: many },
          by_tool: {},
          by_severity: {},
        }}
      />,
    );
    expect(screen.getByText(/3 more not shown/)).toBeInTheDocument();
    // header + MAX_ROWS rows
    expect(screen.getAllByRole("row")).toHaveLength(MAX_ROWS + 1);
  });
});

describe("AuditReportPanel — untrusted metadata renders as text only (AC2)", () => {
  it("renders <script> and event-handler markup in a message as literal text", () => {
    const hostile = '<script>alert(1)</script><img src=x onerror="alert(1)">';
    const { container } = render(
      <AuditReportPanel
        title="x"
        metadata={{
          total_findings: 1,
          by_bucket: {
            mechanical: [],
            manual: [],
            unscannable: [finding({ message: hostile, file_path: hostile, rule_id: hostile })],
          },
          by_tool: {},
          by_severity: {},
        }}
      />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    // The literal text is present (three cells carry it).
    expect(screen.getAllByText((_c, el) => el?.textContent === hostile).length).toBeGreaterThan(0);
  });

  it("never turns a javascript: or https: path into a link", () => {
    const { container } = render(
      <AuditReportPanel
        title="x"
        metadata={{
          total_findings: 1,
          by_bucket: {
            mechanical: [],
            manual: [],
            unscannable: [
              finding({ file_path: "javascript:alert(1)", message: "https://evil.example" }),
            ],
          },
          by_tool: {},
          by_severity: {},
        }}
      />,
    );
    expect(container.querySelector("a")).toBeNull();
  });

  it("renders hostile strings in the fallback view as text too", () => {
    const { container } = render(
      <AuditReportPanel title="x" metadata={{ note: "<b onmouseover=alert(1)>hi</b>" }} />,
    );
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText("<b onmouseover=alert(1)>hi</b>")).toBeInTheDocument();
  });
});

describe("AuditReportPanel — unknown shape and empty state (AC3)", () => {
  it("renders a generic key/value list for an unrecognized shape instead of erroring", () => {
    render(
      <AuditReportPanel
        title="Audit Report"
        metadata={{ total: 2, major_required: 1, updated: ["lodash", "react"] }}
      />,
    );
    const section = screen.getByRole("region", { name: /audit report/i });
    expect(within(section).queryByRole("table")).toBeNull();
    expect(within(section).getByText("total")).toBeInTheDocument();
    expect(within(section).getByText("2")).toBeInTheDocument();
    expect(within(section).getByText("major_required")).toBeInTheDocument();
    expect(within(section).getByText('["lodash","react"]')).toBeInTheDocument();
  });

  it("renders nothing useful-but-safe for null metadata", () => {
    render(<AuditReportPanel title="Audit Report" metadata={null} />);
    expect(screen.getByText(/no report data/i)).toBeInTheDocument();
  });

  it("renders the empty state for total_findings: 0", () => {
    render(
      <AuditReportPanel
        title="Security scan findings"
        metadata={{
          total_findings: 0,
          by_bucket: { mechanical: [], manual: [], unscannable: [] },
          by_tool: {},
          by_severity: {},
        }}
      />,
    );
    expect(screen.getByText(/no findings/i)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
