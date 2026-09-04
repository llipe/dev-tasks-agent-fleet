"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import {
  DEFAULT_COLLAPSED,
  readSidebarCollapsed,
  writeSidebarCollapsed,
} from "@/lib/ui/sidebar-state";
import { detectPlatform, isSidebarToggleShortcut, isTypingTarget } from "@/lib/ui/shortcuts";

import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import styles from "./AppShell.module.css";

/**
 * The app shell (`/DESIGN.md` §4.1). Owns the collapse state as the single
 * source the sidebar and grid both react to.
 *
 * Hydration contract (the trap this story is built around): `localStorage` is
 * not readable on the server, so the first client render MUST match the server
 * markup — it renders the fixed default (`DEFAULT_COLLAPSED`, expanded). The
 * stored preference is applied in a mount effect, AFTER hydration, so React
 * never sees a server/client divergence. Reading storage during render
 * (`useState(() => readStoredCollapse())`) would produce exactly the mismatch
 * the S-106 hydration test asserts against — do not do it.
 *
 * The top bar is fixed at the top of the content column and owns the
 * breadcrumb slot; the scrolling region is below it, so the content — not the
 * page — owns the scroll (`/DESIGN.md` §4.1). Pages pass their breadcrumb and
 * optional header actions through `breadcrumb` / `actions`.
 */
export function AppShell({
  children,
  breadcrumb,
  actions,
}: {
  children: ReactNode;
  breadcrumb?: ReactNode;
  actions?: ReactNode;
}) {
  const [collapsed, setCollapsed] = useState<boolean>(DEFAULT_COLLAPSED);

  // Reconcile from storage once, after mount — never during render.
  useEffect(() => {
    const stored = readSidebarCollapsed(typeof window === "undefined" ? null : window.localStorage);
    if (stored !== DEFAULT_COLLAPSED) setCollapsed(stored);
  }, []);

  // Persist on every change (best-effort; a throwing store is swallowed).
  useEffect(() => {
    writeSidebarCollapsed(typeof window === "undefined" ? null : window.localStorage, collapsed);
  }, [collapsed]);

  // Cmd+\ / Ctrl+\ toggle, ignored while a text field has focus.
  useEffect(() => {
    const platform = detectPlatform();
    function onKeyDown(event: KeyboardEvent) {
      if (isTypingTarget(event.target)) return;
      if (isSidebarToggleShortcut(event, platform)) {
        event.preventDefault();
        setCollapsed((c) => !c);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className={styles.shell}>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
      <div className={styles.column}>
        <TopBar breadcrumb={breadcrumb} actions={actions} />
        <main className={styles.content}>{children}</main>
      </div>
    </div>
  );
}
