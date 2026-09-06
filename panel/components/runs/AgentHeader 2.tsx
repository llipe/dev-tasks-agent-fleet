import Link from "next/link";

import type { AgentHeader as AgentHeaderData } from "@/lib/domain/run-row";
import { Breadcrumb } from "@/components/Breadcrumb";
import { Button } from "@/components/Button";
import { Tag } from "@/components/Tag";

import styles from "./AgentHeader.module.css";

/**
 * Run-history agent header (`/DESIGN.md` §5.2). Breadcrumb (`agents /
 * <slug>`), the agent name + enabled/disabled tag, its description, and the
 * three metadata values (params count, p50 duration, success rate). An Invoke
 * action links forward to the invoke route (S-113) — rendered disabled until
 * that route exists (task 3.8 analogue), never linking to a 404.
 *
 * Presentational and server-safe. The metrics are pre-derived by
 * `buildAgentHeader`; nothing here computes a metric or reads a clock. The
 * `p50Duration`/`successRate` nulls (zero-run agent) present as legible copy,
 * never `NaN`.
 */
export interface AgentHeaderProps {
  header: AgentHeaderData;
  /** Invoke route target, or null while the route is unbuilt (S-113). */
  invokeHref: string | null;
}

export function AgentHeader({ header, invokeHref }: AgentHeaderProps) {
  const params = `${header.paramsCount} ${header.paramsCount === 1 ? "param" : "params"}`;
  const p50 = header.p50Duration != null ? `p50 ${header.p50Duration}` : "no duration data";
  const success = header.successRate != null ? `${header.successRate}% success` : "no runs yet";

  return (
    <header className={styles.header}>
      <Breadcrumb
        className={styles.breadcrumb}
        items={[
          { label: "agents", href: "/" },
          { label: header.slug, active: true },
        ]}
      />
      <div className={styles.row}>
        <div className={styles.identity}>
          <div className={styles.titleRow}>
            <h1 className={styles.name}>{header.name}</h1>
            <Tag variant={header.isEnabled ? "accent" : "neutral"} size="sm">
              {header.isEnabled ? "ENABLED" : "DISABLED"}
            </Tag>
          </div>
          {header.description != null && <p className={styles.description}>{header.description}</p>}
          <div className={styles.meta}>
            <span>{params}</span>
            <span>{p50}</span>
            <span>{success}</span>
          </div>
        </div>
        <div className={styles.actions}>
          {invokeHref != null ? (
            <Link href={invokeHref} className={styles.invokeLink}>
              <Button variant="primary" size="md">
                Invoke
              </Button>
            </Link>
          ) : (
            <Button variant="primary" size="md" disabled aria-disabled="true">
              Invoke
            </Button>
          )}
        </div>
      </div>
    </header>
  );
}
