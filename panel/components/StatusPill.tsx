import type { CSSProperties } from "react";

import type { RunStatus } from "@/lib/domain/status";
import { statusMeta } from "./status-meta";
import styles from "./StatusPill.module.css";

/**
 * StatusPill — /DESIGN.md §3.4. A dot + status label in a rounded, tinted
 * pill. Monospace label (§7.4). The `running` variant's dot pulses. Covers all
 * six statuses plus `canceled` and any unknown fallback.
 *
 * The dot is marked decorative because the pill always renders the status
 * label as visible text right beside it (AC5 — status conveyed by text, never
 * color alone).
 */
export interface StatusPillProps {
  status: RunStatus | (string & {});
  className?: string;
}

export function StatusPill({ status, className }: StatusPillProps) {
  const meta = statusMeta(status);
  const classes = [styles.pill, className].filter(Boolean).join(" ");
  const style = { "--st-color": meta.colorVar } as CSSProperties;
  return (
    <span className={classes} style={style}>
      <span
        className={[styles.dot, meta.pulse && styles.pulse, meta.hollow && styles.hollow]
          .filter(Boolean)
          .join(" ")}
        aria-hidden="true"
      />
      <span className={styles.label}>{meta.label}</span>
    </span>
  );
}
