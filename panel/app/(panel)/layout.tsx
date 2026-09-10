import { cookies } from "next/headers";
import type { ReactNode } from "react";

import { AppShell } from "@/components/shell/AppShell";
import { createAuthServerClient } from "@/lib/supabase/auth-server";

/**
 * Authenticated route-group layout (Story S-118, extended in S-120).
 *
 * The `(panel)` route group owns the app shell so that routes outside it — the
 * public `/login` screen (S-119) — can render without the sidebar and top bar.
 * The parentheses in `(panel)` do not appear in URLs, so every path served by
 * this subtree resolves exactly as it did when the shell lived in the root
 * layout (`/`, `/agents/[slug]`, `/runs/[id]`).
 *
 * Auth-state threading (S-120): this SERVER layout resolves whether the current
 * request is authenticated — via the S-116 cookie-backed anon auth client and
 * `getClaims()` (verified identity, never the spoofable `getSession()` user) —
 * and passes it as the `authenticated` prop into `AppShell` → `Sidebar`, which
 * gates the footer "Log out" affordance. The determination happens ENTIRELY
 * server-side; the shell never fetches auth state on the client, so the S-106
 * hydration contract is untouched (SD2 preserved — the shell performs no auth
 * I/O itself). Any real destination is still protected by the middleware gate
 * (S-117); this value only decides whether to show the Log out control.
 *
 * `AppShell`'s collapse behavior and the S-106 hydration contract (fixed server
 * default reconciled from storage after mount) are unchanged.
 */
export default async function PanelLayout({ children }: { children: ReactNode }) {
  const cookieStore = await cookies();
  const supabase = createAuthServerClient(cookieStore);

  let authenticated = false;
  try {
    const { data, error } = await supabase.auth.getClaims();
    authenticated = !error && data?.claims != null;
  } catch {
    // Fail-closed for the affordance: on any auth-check failure, hide Log out.
    authenticated = false;
  }

  return <AppShell authenticated={authenticated}>{children}</AppShell>;
}
