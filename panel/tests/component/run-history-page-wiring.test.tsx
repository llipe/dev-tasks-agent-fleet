import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

/**
 * Page-wiring test for the run-history route (`app/(panel)/agents/[slug]/page.tsx`).
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
 *
 * Also covers the S-143 pagination footer ("X of Y" + "Load more") wiring,
 * which no other test asserts against the actual page render.
 */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  notFound: () => {
    throw new Error("notFound");
  },
}));

function fixtureRun(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "01J8XQ2F3K4M5N6P7Q8R9S0T1U",
    agent_id: "a1",
    agent_version: "0.1.0",
    repository_id: null,
    installation_id: null,
    trigger_type: "manual",
    triggered_by: null,
    params: {},
    idempotency_key: null,
    session_id: null,
    runtime_invocation_id: null,
    status: "succeeded",
    queued_at: "2026-01-01T11:54:00.000Z",
    started_at: "2026-01-01T11:55:00.000Z",
    finished_at: "2026-01-01T11:59:00.000Z",
    duration_ms: 184_000,
    last_heartbeat_at: null,
    max_runtime_seconds: 900,
    grace_seconds: 60,
    start_timeout_seconds: 300,
    outcome: "fixed",
    error_code: null,
    error_message: null,
    result: {},
    metrics: {},
    created_at: "2026-01-01T11:54:00.000Z",
    updated_at: "2026-01-01T11:59:00.000Z",
    agent_slug: "dependency-update",
    agent_name: "Dependency Update",
    repository_full_name: "acme/web",
    effective_status: "succeeded",
    ...overrides,
  };
}

vi.mock("@/lib/supabase/server", () => ({ createServerClient: () => ({}) }));
const { getFilteredRuns } = vi.hoisted(() => ({
  getFilteredRuns: vi.fn().mockResolvedValue({ rows: [], totalCount: 0 }),
}));
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
  getFilteredRuns,
  getRunStatusCounts: vi.fn().mockResolvedValue({
    all: 0,
    queued: 0,
    running: 0,
    succeeded: 0,
    failed: 0,
    timed_out: 0,
    failed_to_start: 0,
    canceled: 0,
  }),
  getEnabledRepositories: vi.fn().mockResolvedValue([]),
  getStepProgressForRuns: vi.fn().mockResolvedValue(new Map()),
}));

import AgentRunHistoryPage from "@/app/(panel)/agents/[slug]/page";

afterEach(() => {
  cleanup();
  getFilteredRuns.mockReset();
  getFilteredRuns.mockResolvedValue({ rows: [], totalCount: 0 });
});

describe("run-history page wiring — invoke route enabled", () => {
  it("passes a real invokeHref so the Invoke CTA links to the invoke route", async () => {
    const ui = await AgentRunHistoryPage({
      params: Promise.resolve({ slug: "dependency-update" }),
      searchParams: Promise.resolve({}),
    });
    render(ui);

    const link = screen.getByRole("link", { name: /invoke on one repo/i });
    expect(link).toHaveAttribute("href", "/agents/dependency-update/invoke");
  });
});

describe("run-history page wiring — pagination footer (S-143, FR5)", () => {
  it("renders 'X of Y' and a 'Load more' link when more rows exist than are shown", async () => {
    getFilteredRuns.mockResolvedValue({ rows: [fixtureRun()], totalCount: 7 });

    const ui = await AgentRunHistoryPage({
      params: Promise.resolve({ slug: "dependency-update" }),
      searchParams: Promise.resolve({}),
    });
    render(ui);

    expect(screen.getByText("1 of 7")).toBeInTheDocument();
    const loadMore = screen.getByRole("link", { name: /load more/i });
    expect(loadMore).toHaveAttribute("href", "/agents/dependency-update?page=2");
  });

  it("omits 'Load more' once every matching row has already been shown", async () => {
    getFilteredRuns.mockResolvedValue({ rows: [fixtureRun()], totalCount: 1 });

    const ui = await AgentRunHistoryPage({
      params: Promise.resolve({ slug: "dependency-update" }),
      searchParams: Promise.resolve({}),
    });
    render(ui);

    expect(screen.getByText("1 of 1")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /load more/i })).toBeNull();
  });

  it("preserves the active filter's other params when building the 'Load more' href", async () => {
    getFilteredRuns.mockResolvedValue({ rows: [fixtureRun()], totalCount: 5 });

    const ui = await AgentRunHistoryPage({
      params: Promise.resolve({ slug: "dependency-update" }),
      searchParams: Promise.resolve({ status: "succeeded", q: "acme" }),
    });
    render(ui);

    const loadMore = screen.getByRole("link", { name: /load more/i });
    const url = new URL(loadMore.getAttribute("href")!, "http://x");
    expect(url.searchParams.get("status")).toBe("succeeded");
    expect(url.searchParams.get("q")).toBe("acme");
    expect(url.searchParams.get("page")).toBe("2");
  });
});
