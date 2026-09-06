import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

/**
 * Page-wiring test for the dashboard route (`app/page.tsx`).
 *
 * The `DashboardClient` component tests already cover both invoke-route states.
 * What THIS asserts is the wiring the component tests cannot: that the page
 * passes `invokeRouteAvailable = true` now that the S-113 invoke route ships,
 * so the dashboard's Invoke action links to `/agents/[slug]/invoke` rather than
 * rendering disabled. Guards against the `INVOKE_ROUTE_AVAILABLE` flag silently
 * regressing to `false`.
 */

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/",
}));

// Mock the server data layer: the page reads once via getDashboardData.
vi.mock("@/lib/supabase/server", () => ({ createServerClient: () => ({}) }));
vi.mock("@/lib/supabase/queries", () => ({
  getDashboardData: vi.fn().mockResolvedValue({
    agents: [
      {
        id: "a1",
        slug: "dependency-update",
        name: "Dependency Update",
        description: "Runs npm audit and opens a PR.",
        requires_repository: true,
      },
    ],
    runs: [],
  }),
}));

import DashboardPage from "@/app/page";

afterEach(cleanup);

describe("dashboard page wiring — invoke route enabled", () => {
  it("passes invokeRouteAvailable=true so Invoke links to the invoke route", async () => {
    // The page is an async server component; await its element then render it.
    const ui = await DashboardPage();
    render(ui);

    const link = screen
      .getAllByRole("link")
      .find((a) => a.getAttribute("href") === "/agents/dependency-update/invoke");
    expect(link, "expected the Invoke action to link to the invoke route").toBeDefined();
    expect(within(link as HTMLElement).getByRole("button", { name: /invoke/i })).toBeEnabled();
  });
});
