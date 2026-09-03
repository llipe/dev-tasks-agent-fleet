import type { CSSProperties } from "react";

import type { RunStatus } from "@/lib/domain/status";
import { statusMeta } from "./status-meta";
import styles from "./RunStrip.module.css";

/**
 * RunStrip — /DESIGN.md §3.9. A 24-bar sparkline of recent run statuses
 * (newest last). Presentational, server-safe.
 *
 * When fewer than `max` (24) runs are supplied, the remaining slots render as
 * 33%-height empty placeholders (EC). A `running` bar pulses. Bars are
 * decorative (aria-hidden); the surrounding card carries the textual summary
 * (AC5).
 */
export interface RunStripProps {
  runs: { status: RunStatus | (string & {}) }[];
  max?: number;
  className?: string;
}

export function RunStrip({ runs, max = 24, className }: RunStripProps) {
  const filled = runs.slice(-max);
  const emptyCount = Math.max(0, max - filled.length);
  return (
    <div
      className={[styles.strip, className].filter(Boolean).join(" ")}
      role="presentation"
      aria-hidden="true"
    >
      {Array.from({ length: emptyCount }).map((_, i) => (
        <span key={`empty-${i}`} className={`${styles.bar} ${styles.empty}`} />
      ))}
      {filled.map((run, i) => {
        const meta = statusMeta(run.status);
        return (
          <span
            key={`run-${i}`}
            className={[styles.bar, meta.pulse && styles.pulse].filter(Boolean).join(" ")}
            style={{ "--bar-color": meta.colorVar } as CSSProperties}
          />
        );
      })}
    </div>
  );
}
