"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import styles from "./NavItem.module.css";

/**
 * NavItem — /DESIGN.md §3.5. Sidebar navigation row. Interactive (hover/active
 * state, collapse behavior), so it is a client component. Renders as a
 * next/link. Collapsed mode hides the label and badge, showing only the icon;
 * the accessible name is preserved via `aria-label` so the collapsed sidebar
 * is still navigable by assistive tech.
 */
export interface NavItemProps {
  href: string;
  icon: ReactNode;
  label: string;
  badge?: ReactNode;
  active?: boolean;
  collapsed?: boolean;
  className?: string;
}

export function NavItem({
  href,
  icon,
  label,
  badge,
  active = false,
  collapsed = false,
  className,
}: NavItemProps) {
  const classes = [
    styles.navitem,
    active && styles.active,
    collapsed && styles.collapsed,
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <Link
      href={href}
      className={classes}
      aria-current={active ? "page" : undefined}
      aria-label={collapsed ? label : undefined}
      title={collapsed ? label : undefined}
    >
      <span className={styles.icon} aria-hidden="true">
        {icon}
      </span>
      {!collapsed && <span className={styles.label}>{label}</span>}
      {!collapsed && badge != null && <span className={styles.badge}>{badge}</span>}
    </Link>
  );
}
