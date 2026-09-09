import type { ReactNode } from "react";

import { AppShell } from "@/components/shell/AppShell";

/**
 * Authenticated route-group layout (Story S-118).
 *
 * The `(panel)` route group owns the app shell so that routes outside it — the
 * public `/login` screen (S-119) — can render without the sidebar and top bar.
 * The parentheses in `(panel)` do not appear in URLs, so every path served by
 * this subtree resolves exactly as it did when the shell lived in the root
 * layout (`/`, `/agents/[slug]`, `/runs/[id]`).
 *
 * AppShell's props and behavior are unchanged — including the S-106 hydration
 * contract (fixed server default reconciled from storage after mount). This
 * layout only relocates the wrapping responsibility from the root layout.
 */
export default function PanelLayout({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
