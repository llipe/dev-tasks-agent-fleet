import type { CSSProperties } from "react";

import type { RunStatus } from "@/lib/domain/status";
import { statusMeta } from "./status-meta";
import styles from "./StatusDot.module.css";

/**
 * StatusDot — /DESIGN.md §8.1. A small colored dot. `running`/`queued` pulse;
 * `failed_to_start` is hollow (border only). Presentational, server-safe.
 *
 * Accessibility: the dot alone conveys nothing (AC5). It exposes the status
 * label via `aria-label`; when rendered next to visible status text, pass
 * `decorative` so the dot is hidden from assistive tech and the text carries
 * the meaning (avoids a doubled announcement).
 */
export type StatusDotSize = 5 | 6 | 7;

export interface StatusDotProps {
  status: RunStatus | (string & {});
  size?: StatusDotSize;
  decorative?: boolean;
  className?: string;
}

export function StatusDot({ status, size = 7, decorative = false, className }: StatusDotProps) {
  const meta = statusMeta(status);
  const classes = [
    styles.dot,
    meta.pulse && styles.pulse,
    meta.hollow && styles.hollow,
    className,
  ]
    .filter(Boolean)
    .join(" ");
  const style = {
    "--st-color": meta.colorVar,
    "--st-size": `${size}px`,
  } as CSSProperties;
  return (
    <span
      className={classes}
      style={style}
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : meta.label}
      aria-hidden={decorative ? true : undefined}
    />
  );
}
