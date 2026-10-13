import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

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

/**
 * Layer 2 (component) — AuditReportPanel disclosure (issue #245).
 *
 * The findings table is wrapped in a native `<details>`/`<summary>` so a large
 * `audit_report` cannot push the steps panel, log toolbar, and log viewer off
 * screen (/DESIGN.md §4.2 "no outer scroll"). The threshold counts RENDERED
 * rows (`view.rows.length`, ≤ MAX_ROWS), not the agent-reported `total_findings`
 * (D-12 / verifier F-3): open by default at ≤10 rows, closed at ≥11. The
 * component stays server-safe (no "use client") and metadata stays escaped text.
 */

/** Build an audit_report with exactly `n` rendered rows (all in `unscannable`). */
function reportWith(n: number, extra: Partial<Record<string, Json>> = {}): Json {
  const rows = Array.from({ length: n }, (_, i) =>
    finding({ rule_id: `rule-${i}`, line_start: i, message: `message ${i}` }),
  );
  return {
    total_findings: n,
    by_bucket: { mechanical: [], manual: [], unscannable: rows },
    by_tool: {},
    by_severity: {},
    ...extra,
  };
}

/** Mulberry32 — a tiny deterministic PRNG (no dependency), for RT-1/RT-2. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

describe("AuditReportPanel — findings disclosure (issue #245)", () => {
  it("renders the summary line inside <summary>, always visible (AC2)", () => {
    const { container } = render(<AuditReportPanel title="x" metadata={reportWith(50)} />);
    const summary = container.querySelector("summary");
    expect(summary).not.toBeNull();
    // The "N findings" summary line lives inside <summary>.
    expect(within(summary as HTMLElement).getByText(/50 findings/)).toBeInTheDocument();
  });

  it("opens by default at exactly 10 rendered rows (EC-245-1, AC3)", () => {
    const { container } = render(<AuditReportPanel title="x" metadata={reportWith(10)} />);
    const details = container.querySelector("details");
    expect(details).not.toBeNull();
    expect(details).toHaveAttribute("open");
  });

  it("is closed by default at exactly 11 rendered rows (EC-245-1, AC3)", () => {
    const { container } = render(<AuditReportPanel title="x" metadata={reportWith(11)} />);
    const details = container.querySelector("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");
  });

  it("50 rows: closed by default, all 50 rows in the DOM, toggles open (AC5)", () => {
    const { container } = render(<AuditReportPanel title="x" metadata={reportWith(50)} />);
    const details = container.querySelector("details") as HTMLDetailsElement;
    expect(details).not.toHaveAttribute("open");

    // All 50 finding rows are in the DOM even while closed (native <details>
    // keeps its children mounted; it only hides them with CSS).
    expect(screen.getAllByRole("row")).toHaveLength(51); // header + 50

    // Toggling open reflects the native `open` attribute.
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
    expect(details.open).toBe(true);
  });

  it("preserves <caption> and column-header semantics inside the disclosure (AC2)", () => {
    render(<AuditReportPanel title="Security scan findings" metadata={reportWith(50)} />);
    const table = screen.getByRole("table");
    // The <caption> survives.
    expect(within(table).getByText("Security scan findings")).toBeInTheDocument();
    // Six scoped column headers.
    const headers = within(table).getAllByRole("columnheader");
    expect(headers).toHaveLength(6);
    for (const h of headers) {
      expect(h).toHaveAttribute("scope", "col");
    }
  });

  it("the empty state renders with no disclosure (AC4)", () => {
    const { container } = render(
      <AuditReportPanel
        title="x"
        metadata={{
          total_findings: 0,
          by_bucket: { mechanical: [], manual: [], unscannable: [] },
          by_tool: {},
          by_severity: {},
        }}
      />,
    );
    expect(screen.getByText(/no findings/i)).toBeInTheDocument();
    expect(container.querySelector("details")).toBeNull();
    expect(container.querySelector("summary")).toBeNull();
  });

  it("the generic fallback renders with no disclosure (AC4)", () => {
    const { container } = render(<AuditReportPanel title="x" metadata={{ note: "n" }} />);
    expect(container.querySelector("details")).toBeNull();
    expect(container.querySelector("summary")).toBeNull();
  });

  it("renders the 'N more not shown.' notice inside the open disclosure body (AC4)", () => {
    const many = Array.from({ length: MAX_ROWS + 3 }, (_, i) => finding({ line_start: i }));
    const { container } = render(
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
    const details = container.querySelector("details") as HTMLDetailsElement;
    // > MAX_ROWS rows ⇒ closed by default (CT-9).
    expect(details).not.toHaveAttribute("open");
    const notice = screen.getByText(/3 more not shown/);
    // The notice is a descendant of the <details>, not a sibling that would
    // float outside the collapsed body.
    expect(details.contains(notice)).toBe(true);
  });

  it("totalFindings=50 but 8 rendered rows ⇒ open (rendered rows decide, EC-245-2/D-12)", () => {
    const { container } = render(
      <AuditReportPanel title="x" metadata={reportWith(8, { total_findings: 50 })} />,
    );
    const details = container.querySelector("details");
    expect(details).toHaveAttribute("open");
    // The summary line still reflects the agent total of 50.
    expect(within(details as HTMLElement).getByText(/50 findings/)).toBeInTheDocument();
  });

  it("renders two independent disclosures for a run surfaced as two panels (EC-245-3)", () => {
    // The component renders one report; two panels are two renders. Assert each
    // is independent: a 12-row panel is closed, a 4-row panel is open.
    const { container: c1 } = render(<AuditReportPanel title="first" metadata={reportWith(12)} />);
    const { container: c2 } = render(<AuditReportPanel title="second" metadata={reportWith(4)} />);
    expect(c1.querySelector("details")).not.toHaveAttribute("open");
    expect(c2.querySelector("details")).toHaveAttribute("open");
  });

  it("keeps hostile markup as literal text and renders exactly one details/summary (EC-245-5)", () => {
    const hostile = "</table><script>alert(1)</script><details open><summary>x</summary>";
    const { container } = render(
      <AuditReportPanel
        title="x"
        metadata={reportWith(50, {
          by_bucket: {
            mechanical: [],
            manual: [],
            unscannable: [finding({ message: hostile, rule_id: hostile })],
          },
          total_findings: 50,
        })}
      />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelectorAll("details")).toHaveLength(1);
    expect(container.querySelectorAll("summary")).toHaveLength(1);
  });

  it("tolerates an unknown extra field per finding without crashing (CT-7)", () => {
    const { container } = render(
      <AuditReportPanel
        title="x"
        metadata={{
          total_findings: 1,
          by_bucket: {
            mechanical: [],
            manual: [],
            unscannable: [finding({ unknown_future_field: { nested: true } })],
          },
          by_tool: {},
          by_severity: {},
        }}
      />,
    );
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(container.querySelector("details")).toHaveAttribute("open");
  });

  it("caps rendered rows at MAX_ROWS with the notice inside the body (CT-9)", () => {
    const { container } = render(
      <AuditReportPanel title="x" metadata={reportWith(MAX_ROWS + 100)} />,
    );
    const details = container.querySelector("details") as HTMLDetailsElement;
    expect(details).not.toHaveAttribute("open");
    // header + MAX_ROWS rows only.
    expect(screen.getAllByRole("row")).toHaveLength(MAX_ROWS + 1);
    expect(details.contains(screen.getByText(/100 more not shown/))).toBe(true);
  });
});

describe("AuditReportPanel — randomized tactics (seeded, no dependency)", () => {
  it("RT-1: default-open state and row count hold across random sizes (seed 245001)", () => {
    const seed = Number(process.env.TEST_SEED ?? 245001);
    const rand = mulberry32(seed);
    // 60 random sizes drawn from [0, 60] (the boundary-rich band) plus the
    // extremes 0, 10, 11, MAX_ROWS, MAX_ROWS+50 so the open/closed flip and the
    // truncation cap are always exercised. Kept small-but-plural so the suite
    // stays well inside the default timeout (jsdom renders are not free).
    const sizes = [
      0,
      10,
      11,
      MAX_ROWS,
      MAX_ROWS + 50,
      ...Array.from({ length: 60 }, () => Math.floor(rand() * 61)),
    ];
    sizes.forEach((n, iter) => {
      const { container, unmount } = render(
        <AuditReportPanel title="x" metadata={reportWith(n)} />,
      );
      const details = container.querySelector("details");
      if (n === 0) {
        expect(details, `seed=${seed} iter=${iter} n=${n}: no details for 0 findings`).toBeNull();
      } else {
        const rendered = Math.min(n, MAX_ROWS);
        const shouldOpen = rendered <= 10;
        expect(
          details?.hasAttribute("open") ?? false,
          `seed=${seed} iter=${iter} n=${n}: open=${rendered <= 10}`,
        ).toBe(shouldOpen);
        // rendered rows in DOM = min(n, MAX_ROWS) (header excluded).
        const rows = within(container).getAllByRole("row").length - 1;
        expect(rows, `seed=${seed} iter=${iter} n=${n}: rows`).toBe(rendered);
      }
      unmount();
    });
  });

  it("RT-2: untrusted strings never break the single details/summary (seed 245002)", () => {
    const seed = Number(process.env.TEST_SEED ?? 245002);
    const rand = mulberry32(seed);
    const pieces = [
      "</table>",
      "<script>alert(1)</script>",
      "<details open>",
      "<summary>x</summary>",
      "__proto__",
      "constructor",
      "\u0000\u202e",
      "😈".repeat(10),
    ];
    for (let iter = 0; iter < 50; iter++) {
      const count = 1 + Math.floor(rand() * 20);
      const rows = Array.from({ length: count }, () => {
        const msg =
          pieces[Math.floor(rand() * pieces.length)] + pieces[Math.floor(rand() * pieces.length)];
        return finding({
          message: msg,
          rule_id: msg,
          severity: pieces[Math.floor(rand() * pieces.length)],
        });
      });
      const { container, unmount } = render(
        <AuditReportPanel
          title="x"
          metadata={{
            total_findings: count,
            by_bucket: { mechanical: [], manual: [], unscannable: rows },
            by_tool: {},
            by_severity: {},
          }}
        />,
      );
      expect(container.querySelector("script"), `seed=${seed} iter=${iter}: no script`).toBeNull();
      expect(
        container.querySelectorAll("details").length,
        `seed=${seed} iter=${iter}: one details`,
      ).toBe(1);
      expect(
        container.querySelectorAll("summary").length,
        `seed=${seed} iter=${iter}: one summary`,
      ).toBe(1);
      unmount();
    }
  });
});

describe("AuditReportPanel — disclosure state across the #244 refresh (EC-245-7)", () => {
  /**
   * EC-245-7 pins the open/closed state of a >10-row disclosure after #244's
   * `router.refresh()` re-renders the server tree. `router.refresh()` re-reads
   * the Server Component output and RECONCILES it into the existing client
   * tree (it does not force a full client remount of unchanged components).
   *
   * Because `AuditReportPanel` sets `open={rows.length <= 10}` server-side and
   * that computed value does NOT change across the refresh (the finding count
   * is unchanged), React does not re-write the native `open` attribute, so a
   * user's manual toggle survives the reconcile. We model `router.refresh()`
   * with `rerender(<same element, same props>)` — the identical reconcile path.
   *
   * Verdict recorded in the PR: the user-opened state is PRESERVED across the
   * refresh (not reset to the server default).
   */
  it("preserves a user-opened >10-row disclosure across a server-tree reconcile", () => {
    const metadata = reportWith(50);
    const { container, rerender } = render(<AuditReportPanel title="x" metadata={metadata} />);

    const details = container.querySelector("details") as HTMLDetailsElement;
    // Default closed for >10 rendered rows.
    expect(details.hasAttribute("open")).toBe(false);

    // The user expands it to read the findings.
    fireEvent.click(container.querySelector("summary") as HTMLElement);
    expect(details.open).toBe(true);

    // #244 refresh: the same server output reconciles in (same props).
    rerender(<AuditReportPanel title="x" metadata={metadata} />);

    // The open state is PRESERVED — the reconcile did not collapse it.
    expect(container.querySelector("details")?.open).toBe(true);
  });
});
