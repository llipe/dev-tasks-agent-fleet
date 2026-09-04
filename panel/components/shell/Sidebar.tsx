"use client";

import { usePathname } from "next/navigation";

import { NavItem } from "../NavItem";
import {
  AgentsIcon,
  AllRunsIcon,
  CollapseIcon,
  ExpandIcon,
  RepositoriesIcon,
  SettingsIcon,
  SystemHealthIcon,
} from "../icons";
import { DisabledNavItem } from "./DisabledNavItem";
import styles from "./Sidebar.module.css";

/**
 * The app-shell sidebar (`/DESIGN.md` §4.1, §3.5). A labeled `<nav>` holding
 * the single enabled destination (Agents) plus the four PRD §10 deferred ones,
 * rendered disabled. Client component: it reads the active route and drives the
 * collapse toggle. Collapse *state* is owned by the parent AppShell so the
 * whole shell reacts to one source; this component only renders it and reports
 * toggles back up.
 */
export interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname();
  // Agents owns "/" and every "/agents/..." run-history route.
  const agentsActive = pathname === "/" || pathname.startsWith("/agents");

  return (
    <nav
      className={`${styles.sidebar} ${collapsed ? styles.collapsed : ""}`}
      aria-label="Primary"
      data-collapsed={collapsed}
    >
      <div className={styles.brand}>
        <span className={styles.mark} aria-hidden="true">
          <span className={styles.markDot} />
        </span>
        {!collapsed && <span className={styles.brandName}>Agent Fleet</span>}
      </div>

      <div className={styles.scroll}>
        <NavItem
          href="/"
          icon={<AgentsIcon />}
          label="Agents"
          active={agentsActive}
          collapsed={collapsed}
        />
        <DisabledNavItem icon={<AllRunsIcon />} label="All runs" collapsed={collapsed} />
        <DisabledNavItem icon={<RepositoriesIcon />} label="Repositories" collapsed={collapsed} />
        <DisabledNavItem icon={<SettingsIcon />} label="Settings" collapsed={collapsed} />
        <DisabledNavItem icon={<SystemHealthIcon />} label="System health" collapsed={collapsed} />
      </div>

      <div className={styles.footer}>
        <button
          type="button"
          className={styles.toggle}
          onClick={onToggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-pressed={collapsed}
        >
          <span className={styles.toggleIcon} aria-hidden="true">
            {collapsed ? <ExpandIcon /> : <CollapseIcon />}
          </span>
          {!collapsed && <span className={styles.toggleLabel}>Collapse</span>}
          {!collapsed && <span className={styles.toggleHint}>⌘\</span>}
        </button>
      </div>
    </nav>
  );
}
