import { LogOutIcon } from "../icons";
import styles from "./LogOutItem.module.css";

/**
 * Sidebar footer "Log out" affordance (Story S-120, `/DESIGN.md` §4.1 footer,
 * PRD AC6/AC15).
 *
 * A plain `<form method="post" action="/api/auth/logout">` with a submit button
 * — no client handler, no JS required (progressive enhancement). Logout MUST be
 * a POST (a GET is CSRF-triggerable), and a native form POST is the simplest
 * thing that cannot be fired by a prefetcher.
 *
 * Presentational only: it performs no auth I/O and holds no state. Whether it
 * renders at all is decided by the Sidebar via the `authenticated` prop (SD2
 * preserved — the shell never calls Supabase).
 *
 * Styling reuses the footer-control `.toggle` grid pattern from the Sidebar
 * (icon + label; icon-only when collapsed), token-only CSS (Nocturne
 * discipline). The accessible name stays "Log out" in both states, so the
 * collapsed icon-only control is still labeled for assistive tech.
 */
export interface LogOutItemProps {
  /** Collapsed sidebar → render icon-only (label hidden). */
  collapsed: boolean;
}

export function LogOutItem({ collapsed }: LogOutItemProps) {
  return (
    <form method="post" action="/api/auth/logout" className={styles.form}>
      <button
        type="submit"
        className={`${styles.logout} ${collapsed ? styles.collapsed : ""}`}
        aria-label="Log out"
      >
        <span className={styles.icon} aria-hidden="true">
          <LogOutIcon />
        </span>
        {!collapsed && <span className={styles.label}>Log out</span>}
      </button>
    </form>
  );
}
