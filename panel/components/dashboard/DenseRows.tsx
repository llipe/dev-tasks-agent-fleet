import Link from "next/link";

import type { AgentSummary } from "@/lib/domain/dashboard";
import { formatRelative, formatRunCount, formatStatusLegend } from "@/lib/format";
import { StatusBar, type StatusBarSegment } from "@/components/StatusBar";
import { StatusDot } from "@/components/StatusDot";
import { Tag } from "@/components/Tag";
import { Button } from "@/components/Button";

import { legendSegments, outcomeLabel } from "./summary-view";
import styles from "./DenseRows.module.css";

/**
 * Dashboard variant 1a — dense rows (`/DESIGN.md` §5.1, default). A table-like
 * grid, one row per agent, with a stacked `StatusBar` + text legend per row.
 * Presentational and server-safe: the `nowMs` clock and the pre-shaped
 * summaries are passed in; nothing here reads a clock or a raw status.
 *
 * The status bar is decorative (aria-hidden); the accompanying `formatStatusLegend`
 * text carries the actual meaning (AC5 / §12).
 */
export interface DenseRowsProps {
  agents: AgentSummary[];
  nowMs: number;
  invokeHref: (slug: string) => string | null;
}

export function DenseRows({ agents, nowMs, invokeHref }: DenseRowsProps) {
  return (
    <div className={styles.table} role="table" aria-label="Agents">
      <div className={styles.headRow} role="row">
        <span role="columnheader" aria-label="Status" />
        <span role="columnheader">Agent</span>
        <span role="columnheader">Runs</span>
        <span role="columnheader">Breakdown</span>
        <span role="columnheader">Last run</span>
        <span role="columnheader" aria-label="Actions" />
      </div>
      {agents.map((agent) => {
        const segments: StatusBarSegment[] = legendSegments(agent);
        const href = invokeHref(agent.slug);
        return (
          <div className={styles.row} role="row" key={agent.id}>
            <span className={styles.statusCell} role="cell">
              <StatusDot status={agent.lastRun?.effectiveStatus ?? "queued"} size={7} decorative />
            </span>
            <span className={styles.agentCell} role="cell">
              <Link href={`/agents/${agent.slug}`} className={styles.name}>
                {agent.name}
              </Link>
              <Link href={`/agents/${agent.slug}`} className={styles.slug}>
                {agent.slug}
              </Link>
              {agent.description != null && (
                <span className={styles.description}>{agent.description}</span>
              )}
            </span>
            <span className={styles.runsCell} role="cell">
              {formatRunCount(agent.runCount)}
            </span>
            <span className={styles.breakdownCell} role="cell">
              {agent.runCount > 0 ? (
                <>
                  <StatusBar segments={segments} />
                  <span className={styles.legend}>{formatStatusLegend(agent.legend)}</span>
                </>
              ) : (
                <span className={styles.muted}>no runs yet</span>
              )}
            </span>
            <span className={styles.lastRunCell} role="cell">
              {agent.lastRun != null ? (
                <>
                  <span className={styles.lastRunTime}>
                    {agent.lastRun.atMs != null ? formatRelative(agent.lastRun.atMs, nowMs) : "—"}
                  </span>
                  <Tag variant="outline" size="sm" className={styles.outcomeTag}>
                    {outcomeLabel(agent.lastRun.outcome)}
                  </Tag>
                </>
              ) : (
                <span className={styles.muted}>—</span>
              )}
            </span>
            <span className={styles.actionCell} role="cell">
              {href != null ? (
                <Link href={href} className={styles.invokeLink}>
                  <Button variant="primary" size="sm">
                    Invoke
                  </Button>
                </Link>
              ) : (
                <Button variant="primary" size="sm" disabled aria-disabled="true">
                  Invoke
                </Button>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}
