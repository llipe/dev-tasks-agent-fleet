"use client";

import { useEffect } from "react";
import type { ReactNode } from "react";

import {
  DEFAULT_COLLAPSED,
  SIDEBAR_STORAGE_KEY,
  readSidebarCollapsed,
  writeSidebarCollapsed,
} from "@/lib/ui/sidebar-state";
import { detectPlatform, isSidebarToggleShortcut, isTypingTarget } from "@/lib/ui/shortcuts";
import { useLocalStorageState } from "@/lib/hooks/useLocalStorageState";

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
  topBarActions,
  authenticated = false,
}: {
  children: ReactNode;
  breadcrumb?: ReactNode;
  actions?: ReactNode;
  /** Always-on top-bar right-cluster content (e.g. the notification bell, S-163). */
  topBarActions?: ReactNode;
  /**
   * Whether the current request is authenticated. Server-provided and static
   * per request (the authenticated layout determines it via the auth-server
   * client and passes it in) — the shell never fetches it client-side, so the
   * S-106 hydration contract is untouched. Gates the sidebar Log out item.
   */
  authenticated?: boolean;
}) {
  // Sidebar collapse is a localStorage-backed preference reconciled
  // hydration-safely via useSyncExternalStore (issue 217): server + first client
  // render use DEFAULT_COLLAPSED, then React reads the stored value and
  // re-renders — the same post-hydration reconcile the former mount effect did,
  // but without a setState-in-effect (react-hooks/set-state-in-effect).
  // `setCollapsed` persists through writeSidebarCollapsed.
  const [collapsed, setCollapsed] = useLocalStorageState<boolean>({
    default: DEFAULT_COLLAPSED,
    read: readSidebarCollapsed,
    write: writeSidebarCollapsed,
    storageKey: SIDEBAR_STORAGE_KEY,
  });

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
  }, [setCollapsed]);

  return (
    <div className={styles.shell}>
      <Sidebar
        collapsed={collapsed}
        onToggle={() => setCollapsed((c) => !c)}
        authenticated={authenticated}
      />
      <div className={styles.column}>
        <TopBar
          breadcrumb={breadcrumb}
          actions={
            topBarActions || actions ? (
              <>
                {actions}
                {topBarActions}
              </>
            ) : undefined
          }
        />
        <main className={styles.content}>{children}</main>
      </div>
    </div>
  );
}
