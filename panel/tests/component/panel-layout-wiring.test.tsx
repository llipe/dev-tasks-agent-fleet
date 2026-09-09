import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";

/**
 * Auth-state wiring test for the authenticated route-group layout
 * (`app/(panel)/layout.tsx`) — Story S-120.
 *
 * The layout is the auth-reachability seam for the sidebar Log out affordance:
 * it computes `authenticated` SERVER-SIDE (via the S-116 cookie-backed auth
 * client and `getClaims()`, never the spoofable `getSession()`) and threads it
 * into `AppShell` → `Sidebar`, which gates the footer control (SD2 preserved —
 * the shell performs no auth I/O itself). This asserts the three branches the
 * pure/component tests cannot reach directly:
 *   - verified claims present → `authenticated = true`
 *   - no claims / error → `authenticated = false`
 *   - a thrown `getClaims()` → fail-closed `authenticated = false`
 *
 * `next/headers`, the auth-server client, and `AppShell` are mocked so the
 * layout resolves under node without a live Supabase or request context;
 * `AppShell` is stubbed to record the `authenticated` prop it receives.
 */

const getClaims = vi.hoisted(() => vi.fn());
const appShellProps = vi.hoisted(() => ({ current: null as { authenticated?: boolean } | null }));

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({ getAll: () => [], set: () => {} })),
}));

vi.mock("@/lib/supabase/auth-server", () => ({
  createAuthServerClient: () => ({ auth: { getClaims } }),
}));

vi.mock("@/components/shell/AppShell", () => ({
  AppShell: (props: { authenticated?: boolean; children?: unknown }) => {
    appShellProps.current = { authenticated: props.authenticated };
    return null;
  },
}));

import PanelLayout from "@/app/(panel)/layout";

beforeEach(() => {
  getClaims.mockReset();
  appShellProps.current = null;
});

afterEach(() => {
  vi.clearAllMocks();
});

/** Render the async server layout and return the `authenticated` prop AppShell saw. */
async function authProp(): Promise<boolean | undefined> {
  const ui = await PanelLayout({ children: null });
  render(ui);
  return appShellProps.current?.authenticated;
}

describe("(panel) layout — auth-state threading (S-120)", () => {
  it("threads authenticated=true when getClaims returns verified claims", async () => {
    getClaims.mockResolvedValue({ data: { claims: { sub: "user-1" } }, error: null });
    expect(await authProp()).toBe(true);
  });

  it("threads authenticated=false when there are no claims", async () => {
    getClaims.mockResolvedValue({ data: { claims: null }, error: null });
    expect(await authProp()).toBe(false);
  });

  it("threads authenticated=false when getClaims returns an error", async () => {
    getClaims.mockResolvedValue({ data: null, error: { message: "bad token" } });
    expect(await authProp()).toBe(false);
  });

  it("fails closed to authenticated=false when getClaims throws", async () => {
    getClaims.mockRejectedValue(new Error("auth server unreachable"));
    expect(await authProp()).toBe(false);
  });
});
