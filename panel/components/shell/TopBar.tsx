import type { ReactNode } from "react";

import styles from "./TopBar.module.css";

/**
 * The 38px top bar (`/DESIGN.md` §4.1). A thin header owning a breadcrumb slot
 * the Wave 3 screens fill via the `breadcrumb` prop, and a right-aligned slot
 * for status affordances (e.g. the realtime indicator, later). Presentational
 * and server-render-safe.
 */
export interface TopBarProps {
  breadcrumb?: ReactNode;
  actions?: ReactNode;
}

export function TopBar({ breadcrumb, actions }: TopBarProps) {
  return (
    <header className={styles.topbar}>
      <div className={styles.crumbs}>{breadcrumb}</div>
      {actions != null && <div className={styles.actions}>{actions}</div>}
    </header>
  );
}
