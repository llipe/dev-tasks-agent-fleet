import Link from "next/link";

import type { AgentSummary } from "@/lib/domain/dashboard";
import { formatRelative, formatRunCount, formatStatusLegendCompact } from "@/lib/format";
import { RunStrip } from "@/components/RunStrip";
import { StatusDot } from "@/components/StatusDot";
import { Tag } from "@/components/Tag";
import { Button } from "@/components/Button";

import { outcomeLabel } from "./summary-view";
import styles from "./AgentCards.module.css";

/**
 * Dashboard variant 1b — cards (`/DESIGN.md` §5.1). A 2-column grid, one card
 * per agent, with the 24-bar `RunStrip` sparkline (newest-last) and a 2-line
 * description clamp (§7.5). Presentational and server-safe.
 */
export interface AgentCardsProps {
  agents: AgentSummary[];
  nowMs: number;
  invokeHref: (slug: string) => string | null;
}

export function AgentCards({ agents, nowMs, invokeHref }: AgentCardsProps) {
  return (
    <div className={styles.grid}>
      {agents.map((agent) => {
        const href = invokeHref(agent.slug);
        return (
          <article className={styles.card} key={agent.id}>
            <header className={styles.header}>
              <StatusDot status={agent.lastRun?.effectiveStatus ?? "queued"} size={7} decorative />
              <div className={styles.titleBlock}>
                <Link href={`/agents/${agent.slug}`} className={styles.name}>
                  {agent.name}
                </Link>
                <span className={styles.slug}>{agent.slug}</span>
              </div>
            </header>

            {agent.description != null && <p className={styles.description}>{agent.description}</p>}

            <div className={styles.strip}>
              <RunStrip
                runs={agent.recentRuns.map((r) => ({ status: r.effectiveStatus }))}
                max={24}
              />
            </div>

            <footer className={styles.footer}>
              <span className={styles.meta}>
                {formatRunCount(agent.runCount)}
                {agent.runCount > 0 && (
                  <>
                    {" · "}
                    <span className={styles.legend}>{formatStatusLegendCompact(agent.legend)}</span>
                  </>
                )}
              </span>
              <span className={styles.lastRun}>
                {agent.lastRun != null ? (
                  <>
                    <span className={styles.lastRunTime}>
                      {agent.lastRun.atMs != null ? formatRelative(agent.lastRun.atMs, nowMs) : "—"}
                    </span>
                    <Tag variant="outline" size="sm">
                      {outcomeLabel(agent.lastRun.outcome)}
                    </Tag>
                  </>
                ) : (
                  <span className={styles.muted}>no runs yet</span>
                )}
              </span>
            </footer>

            <div className={styles.actions}>
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
            </div>
          </article>
        );
      })}
    </div>
  );
}
