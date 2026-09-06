import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

/**
 * Page-wiring test for the run-history route (`app/agents/[slug]/page.tsx`).
 *
 * The `AgentHeader` / `RunHistoryTable` component tests already cover both
 * invoke-route states. What THIS asserts is the wiring they cannot: that the
 * page passes a real `invokeHref` (route enabled) now that the S-113 invoke
 * route ships, so the run-history Invoke action links to `/agents/[slug]/invoke`
 * rather than rendering disabled. Guards the page's `INVOKE_ROUTE_AVAILABLE`
 * flag against silently regressing to `false`.
 *
 * Uses the empty-run-list path so the Invoke CTA is the empty-state button,
 * which is present regardless of run data.
 */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  notFound: () => {
    throw new Error("notFound");
  },
}));

vi.mock("@/lib/supabase/server", () => ({ createServerClient: () => ({}) }));
vi.mock("@/lib/supabase/queries", () => ({
  getAgentBySlug: vi.fn().mockResolvedValue({
    id: "a1",
    slug: "dependency-update",
    name: "Dependency Update",
    description: "Runs npm audit and opens a PR.",
    params_schema: { type: "object", properties: { fix_mode: { type: "string" } } },
    is_enabled: true,
  }),
  getAllRunsByAgentSlug: vi.fn().mockResolvedValue([]),
  getStepProgressForRuns: vi.fn().mockResolvedValue(new Map()),
}));

import AgentRunHistoryPage from "@/app/agents/[slug]/page";

afterEach(cleanup);

describe("run-history page wiring — invoke route enabled", () => {
  it("passes a real invokeHref so the Invoke CTA links to the invoke route", async () => {
    const ui = await AgentRunHistoryPage({
      params: Promise.resolve({ slug: "dependency-update" }),
    });
    render(ui);

    const link = screen.getByRole("link", { name: /invoke on one repo/i });
    expect(link).toHaveAttribute("href", "/agents/dependency-update/invoke");
  });
});
