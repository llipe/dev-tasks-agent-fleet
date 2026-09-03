import type { ReactNode } from "react";

import styles from "./Tag.module.css";

/**
 * Tag — /DESIGN.md §3.3. Three variants (accent/neutral/outline) and two
 * sizes (sm/default). Presentational, server-safe. Outcome tags in the UI use
 * the `outline` variant with uppercase text (§8.2).
 */
export type TagVariant = "accent" | "neutral" | "outline";
export type TagSize = "sm" | "default";

export interface TagProps {
  children: ReactNode;
  variant?: TagVariant;
  size?: TagSize;
  className?: string;
}

export function Tag({ children, variant = "neutral", size = "default", className }: TagProps) {
  const classes = [styles.tag, styles[variant], size === "sm" && styles.sm, className]
    .filter(Boolean)
    .join(" ");
  return <span className={classes}>{children}</span>;
}
