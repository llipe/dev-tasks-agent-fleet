import type { CSSProperties } from "react";

import {
  BUCKETS,
  flattenForFallback,
  parseAuditReport,
  type AuditReportView,
  type FindingRow,
} from "@/lib/domain/audit-report";
import type { Json } from "@/lib/supabase/types";

import styles from "./AuditReportPanel.module.css";

/**
 * AuditReportPanel — /DESIGN.md §5.3 (audit-report findings block, issue #241).
 *
 * Renders an `audit_report` artifact's `metadata` on the run-detail summary:
 * a findings table for the security-analyst shape, a generic key/value list
 * for any other shape, and an explicit empty state for zero findings.
 *
 * Two guarantees, mirroring `ArtifactLinks`:
 *
 *  - **AC14 stance:** this component receives the artifact only — never the
 *    run's status — so a `failed` run's report renders exactly like a
 *    `succeeded` run's. There is no code path that hides it.
 *  - **Untrusted metadata (spec §12):** every value renders as text through
 *    React's default escaping. No `dangerouslySetInnerHTML`, no `<a href>`
 *    built from metadata, no interpretation of any string.
 *
 * Presentational and server-safe.
 */
export interface AuditReportPanelProps {
  title: string | null;
  metadata: Json | null;
}

const DEFAULT_TITLE = "Audit report";

/** Severity → status token tint (§2.4). Unknown severities get no tint. */
const SEVERITY_TOKEN: Record<string, string> = {
  critical: "var(--st-fail)",
  high: "var(--st-fail)",
  medium: "var(--st-timeout)",
  low: "var(--faint)",
};

export function AuditReportPanel({ title, metadata }: AuditReportPanelProps) {
  const caption = title != null && title.length > 0 ? title : DEFAULT_TITLE;
  const view = parseAuditReport(metadata);

  return (
    <section className={styles.panel} aria-label="Audit report">
      {view === null ? (
        <Fallback caption={caption} metadata={metadata} />
      ) : view.totalFindings === 0 && view.rows.length === 0 ? (
        <>
          <h3 className={styles.caption}>{caption}</h3>
          <p className={styles.empty}>No findings.</p>
        </>
      ) : (
        <Findings caption={caption} view={view} />
      )}
    </section>
  );
}

function Findings({ caption, view }: { caption: string; view: AuditReportView }) {
  return (
    <>
      <p className={styles.summaryLine}>
        <span className={styles.total}>
          {view.totalFindings} {view.totalFindings === 1 ? "finding" : "findings"}
        </span>
        {view.byTool.length > 0 && (
          <span className={styles.counts}>
            {view.byTool.map(([tool, n]) => `${tool} ${n}`).join(" · ")}
          </span>
        )}
        {view.bySeverity.length > 0 && (
          <span className={styles.counts}>
            {view.bySeverity.map(([sev, n]) => `${sev} ${n}`).join(" · ")}
          </span>
        )}
      </p>
      {view.beforeAfter && (
        <p className={styles.beforeAfter}>
          <span className={styles.beforeAfterLabel}>before → after</span>
          {BUCKETS.map((bucket) => (
            <span key={bucket} className={styles.counts}>
              {bucket} {view.beforeAfter!.before[bucket]} → {view.beforeAfter!.after[bucket]}
            </span>
          ))}
        </p>
      )}
      <table className={styles.table}>
        <caption className={styles.caption}>{caption}</caption>
        <thead>
          <tr className={`${styles.row} ${styles.headRow}`}>
            <th scope="col" className={styles.headCell}>
              Tool
            </th>
            <th scope="col" className={styles.headCell}>
              Severity
            </th>
            <th scope="col" className={styles.headCell}>
              Bucket
            </th>
            <th scope="col" className={styles.headCell}>
              Location
            </th>
            <th scope="col" className={styles.headCell}>
              Rule
            </th>
            <th scope="col" className={styles.headCell}>
              Message
            </th>
          </tr>
        </thead>
        <tbody>
          {view.rows.map((row, i) => (
            <FindingTr key={i} row={row} />
          ))}
        </tbody>
      </table>
      {view.truncated > 0 && (
        <p className={styles.truncated}>{view.truncated} more not shown.</p>
      )}
    </>
  );
}

function FindingTr({ row }: { row: FindingRow }) {
  const location = row.lineStart === null ? row.filePath : `${row.filePath}:${row.lineStart}`;
  const tint = SEVERITY_TOKEN[row.severity.toLowerCase()];
  const severityStyle = tint ? ({ "--sev-color": tint } as CSSProperties) : undefined;
  return (
    <tr className={styles.row}>
      <td className={styles.cell}>{row.tool}</td>
      <td className={styles.cell}>
        <span className={tint ? styles.severity : undefined} style={severityStyle}>
          {row.severity}
        </span>
      </td>
      <td className={styles.cell}>{row.bucket}</td>
      <td className={`${styles.cell} ${styles.mono}`}>{location}</td>
      <td className={`${styles.cell} ${styles.mono}`}>{row.ruleId}</td>
      <td className={`${styles.cell} ${styles.message}`}>{row.message}</td>
    </tr>
  );
}

function Fallback({ caption, metadata }: { caption: string; metadata: Json | null }) {
  const entries = flattenForFallback(metadata);
  return (
    <>
      <h3 className={styles.caption}>{caption}</h3>
      {entries.length === 0 ? (
        <p className={styles.empty}>No report data.</p>
      ) : (
        <dl className={styles.fallback}>
          {entries.map(([key, value]) => (
            <div key={key} className={styles.fallbackRow}>
              <dt className={styles.fallbackKey}>{key}</dt>
              <dd className={`${styles.fallbackValue} ${styles.mono}`}>{value}</dd>
            </div>
          ))}
        </dl>
      )}
    </>
  );
}
