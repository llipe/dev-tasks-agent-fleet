import type { CSSProperties } from "react";

import styles from "./StatusBar.module.css";

/**
 * StatusBar — /DESIGN.md §3.8. A thin stacked bar of colored segments sized by
 * percentage (e.g. an agent's ok/fail/timeout run breakdown). Presentational,
 * server-safe.
 *
 * Each segment carries a token color reference (never a literal). An all-zero
 * or empty segment list renders just the empty track (EC: all-zero segments
 * must not crash). Segments are decorative; a caller MUST render an
 * accompanying text legend (formatStatusLegend) for the actual meaning (AC5).
 */
export interface StatusBarSegment {
  /** token reference, e.g. "var(--st-ok)" */
  colorVar: string;
  /** percentage width 0–100 */
  percent: number;
  label?: string;
}

export interface StatusBarProps {
  segments: StatusBarSegment[];
  className?: string;
}

export function StatusBar({ segments, className }: StatusBarProps) {
  const visible = segments.filter((s) => s.percent > 0);
  return (
    <div
      className={[styles.bar, className].filter(Boolean).join(" ")}
      role="presentation"
      aria-hidden="true"
    >
      {visible.map((seg, i) => (
        <span
          key={`${seg.label ?? "seg"}-${i}`}
          className={styles.segment}
          style={{ "--seg-color": seg.colorVar, width: `${seg.percent}%` } as CSSProperties}
        />
      ))}
    </div>
  );
}
