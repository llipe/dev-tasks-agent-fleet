import type { ReactNode } from "react";

import navStyles from "../NavItem.module.css";
import styles from "./DisabledNavItem.module.css";

/**
 * A deferred navigation destination (PRD §10 — All runs, Repositories,
 * Settings, System health). Rendered visibly disabled rather than as a dead
 * link, so the deferral is legible instead of a click that goes nowhere.
 *
 * It reuses the `NavItem` grid/spacing so it sits flush with the enabled rows,
 * but it is a plain `<span>`, not a link: not focusable, not a focus trap, and
 * announced as disabled to assistive technology via `aria-disabled`. The
 * "not available in this phase" reason is exposed through an accessible
 * tooltip (`title` + an `aria-describedby` note) rather than by muting alone,
 * so the state is conveyed by more than color.
 */
export interface DisabledNavItemProps {
  icon: ReactNode;
  label: string;
  badge?: ReactNode;
  collapsed?: boolean;
}

const UNAVAILABLE = "Not available in this phase";

export function DisabledNavItem({ icon, label, badge, collapsed = false }: DisabledNavItemProps) {
  const classes = [navStyles.navitem, styles.disabled, collapsed && navStyles.collapsed]
    .filter(Boolean)
    .join(" ");
  const describedBy = `nav-unavailable-${label.replace(/\s+/g, "-").toLowerCase()}`;
  return (
    <span
      className={classes}
      aria-disabled="true"
      aria-label={`${label} — ${UNAVAILABLE}`}
      title={UNAVAILABLE}
    >
      <span className={navStyles.icon} aria-hidden="true">
        {icon}
      </span>
      {!collapsed && <span className={navStyles.label}>{label}</span>}
      {!collapsed && badge != null && <span className={navStyles.badge}>{badge}</span>}
      <span id={describedBy} hidden>
        {UNAVAILABLE}
      </span>
    </span>
  );
}
