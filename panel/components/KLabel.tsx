import type { ReactNode } from "react";

import styles from "./KLabel.module.css";

/**
 * Section label — /DESIGN.md §3.7 `.klabel`.
 * 10px uppercase, 0.08em tracking, `--faint`. Presentational, server-safe.
 * Renders as a <span> by default; pass `as` to render a different element
 * (e.g. a legend or heading eyebrow) without losing the styling.
 */
export interface KLabelProps {
  children: ReactNode;
  className?: string;
}

export function KLabel({ children, className }: KLabelProps) {
  return <span className={[styles.klabel, className].filter(Boolean).join(" ")}>{children}</span>;
}
