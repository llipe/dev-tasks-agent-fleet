import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

/**
 * Page-wiring test for the new cross-agent run feed route
 * (`app/(panel)/runs/page.tsx`, Story S-146, issue #206, FR13/FR14).
 *
 * This is almost entirely composition of S-143's `RunFilterBar` +
 * `getFilteredRuns` foundation (already covered by `filtered-runs.test.ts`
 * and `RunFilterBar.test.tsx`) — what THIS asserts is the wiring unique to
 * this new route:
 *  - it calls `getFilteredRuns`/`getRunStatusCounts` with `agentSlug: null`
 *    (no route-slug scoping, unlike `/agents/[slug]`),
 *  - it renders every row with `showAgentColumn` so cross-agent rows are
 *    attributed correctly (AC1),
 *  - the pagination footer / "Load more" href targets `/runs`, not an
 *    `/agents/[slug]` path,
 *  - there is no per-agent header (`AgentHeader`) on this screen — it is not
 *    agent-scoped.
 */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
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
const { getFilteredRuns, getRunStatusCounts } = vi.hoisted(() => ({
  getFilteredRuns: vi.fn().mockResolvedValue({ rows: [], totalCount: 0 }),
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
}));
vi.mock("@/lib/supabase/queries", () => ({
  getFilteredRuns,
  getRunStatusCounts,
  getEnabledRepositories: vi.fn().mockResolvedValue([]),
  getStepProgressForRuns: vi.fn().mockResolvedValue(new Map()),
  getPullRequestArtifactsForRuns: vi.fn().mockResolvedValue({}),
}));

import AllRunsPage from "@/app/(panel)/runs/page";

afterEach(() => {
  cleanup();
  getFilteredRuns.mockReset();
  getFilteredRuns.mockResolvedValue({ rows: [], totalCount: 0 });
  getRunStatusCounts.mockClear();
});

describe("/runs page wiring — cross-agent, unscoped (S-146, FR13)", () => {
  it("calls getFilteredRuns/getRunStatusCounts with agentSlug: null (no route-slug scoping)", async () => {
    const ui = await AllRunsPage({ searchParams: Promise.resolve({}) });
    render(ui);

    expect(getFilteredRuns).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ agentSlug: null }),
      expect.any(Number),
    );
    expect(getRunStatusCounts).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ agentSlug: null }),
    );
  });

  it("renders each row attributed to its own agent via the Agent column (AC1)", async () => {
    getFilteredRuns.mockResolvedValue({
      rows: [
        fixtureRun({
          id: "run-a",
          agent_slug: "dependency-update",
          agent_name: "Dependency Update",
        }),
        fixtureRun({ id: "run-b", agent_slug: "security-analyst", agent_name: "Security Analyst" }),
      ],
      totalCount: 2,
    });

    const ui = await AllRunsPage({ searchParams: Promise.resolve({}) });
    render(ui);

    expect(screen.getByText("Dependency Update")).toBeInTheDocument();
    expect(screen.getByText("dependency-update")).toBeInTheDocument();
    expect(screen.getByText("Security Analyst")).toBeInTheDocument();
    expect(screen.getByText("security-analyst")).toBeInTheDocument();
  });

  it("renders no per-agent header — this screen is not agent-scoped", async () => {
    const ui = await AllRunsPage({ searchParams: Promise.resolve({}) });
    render(ui);
    expect(screen.queryByRole("navigation", { name: /breadcrumb/i })).toBeNull();
  });

  it("builds the 'Load more' href against /runs, preserving the active filter", async () => {
    getFilteredRuns.mockResolvedValue({ rows: [fixtureRun()], totalCount: 7 });

    const ui = await AllRunsPage({ searchParams: Promise.resolve({ status: "succeeded" }) });
    render(ui);

    const loadMore = screen.getByRole("link", { name: /load more/i });
    const url = new URL(loadMore.getAttribute("href")!, "http://x");
    expect(url.pathname).toBe("/runs");
    expect(url.searchParams.get("status")).toBe("succeeded");
    expect(url.searchParams.get("page")).toBe("2");
  });
});
