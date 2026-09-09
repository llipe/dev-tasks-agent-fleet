import type { Metadata } from "next";
import type { ReactNode } from "react";

/**
 * Login route layout (Story S-119, spec §10.1 / §10.3).
 *
 * `/login` lives OUTSIDE the `(panel)` route group (S-118), so it does not
 * inherit the authenticated `AppShell` (sidebar + top bar). This layout renders
 * only a plain wrapper — the public login screen stands alone, with no shell —
 * while the root `app/layout.tsx` still provides `<html>`/`<body>`, the Inter
 * fonts, and the global styles.
 */
export const metadata: Metadata = {
  title: "Sign in · Agent Fleet Control Panel",
  description: "Sign in to the Agent Fleet control panel.",
};

export default function LoginLayout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
