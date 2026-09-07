import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

/**
 * Page-wiring tests for the run-detail route (`app/runs/[id]/page.tsx`).
 *
 * The component tests cover the presentational pieces; these assert the wiring
 * they cannot — that the server component:
 *  - 404s (calls `notFound()`) for an unknown run id (AC9),
 *  - renders the terminal-state banner + surfaces a `pull_request` artifact on
 *    a FAILED run through the whole page (AC14 end-to-end),
 *  - marks the log region `aria-live` (AC8) via the composed LogViewer.
 *
 * The Supabase server client and query layer are mocked; the domain shaping and
 * component rendering are real.
 */

const notFoundError = new Error("NEXT_NOT_FOUND");

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw notFoundError;
  },
}));

vi.mock("@/lib/supabase/server", () => ({ createServerClient: () => ({}) }));

const queryMock = vi.hoisted(() => ({
  getRunById: vi.fn(),
  getRunSteps: vi.fn().mockResolvedValue([]),
  getRunEvents: vi.fn().mockResolvedValue([]),
  getRunEventsInRange: vi.fn().mockResolvedValue([]),
  getRunArtifacts: vi.fn().mockResolvedValue([]),
  RUN_EVENTS_READ_LIMIT: 2000,
}));

vi.mock("@/lib/supabase/queries", () => queryMock);

import RunDetailPage from "@/app/runs/[id]/page";

function vrun(overrides: Record<string, unknown> = {}) {
  const now = Date.now();
  return {
    id: "01J8XQ2F-3K4M-5N6P-7Q8R-9S0T1U2V3W4X",
    agent_id: "a1",
    agent_slug: "dependency-update",
    agent_name: "Dependency Update",
    agent_version: "0.1.0",
    repository_id: null,
    repository_full_name: "llipe/x",
    installation_id: null,
    trigger_type: "manual",
    triggered_by: null,
    params: { branch: "main" },
    idempotency_key: null,
    session_id: null,
    runtime_invocation_id: null,
    status: "failed",
    effective_status: "failed",
    queued_at: new Date(now - 600_000).toISOString(),
    started_at: new Date(now - 540_000).toISOString(),
    finished_at: new Date(now - 300_000).toISOString(),
    duration_ms: 240_000,
    last_heartbeat_at: null,
    max_runtime_seconds: 900,
    grace_seconds: 60,
    start_timeout_seconds: 300,
    outcome: "needs_review",
    error_code: null,
    error_message: null,
    result: {},
    metrics: {},
    created_at: new Date(now - 600_000).toISOString(),
    updated_at: new Date(now - 300_000).toISOString(),
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  queryMock.getRunSteps.mockResolvedValue([]);
  queryMock.getRunEvents.mockResolvedValue([]);
  queryMock.getRunArtifacts.mockResolvedValue([]);
});

describe("run-detail page wiring", () => {
  it("throws notFound() for an unknown run id (AC9)", async () => {
    queryMock.getRunById.mockResolvedValue(null);
    await expect(RunDetailPage({ params: Promise.resolve({ id: "does-not-exist" }) })).rejects.toBe(
      notFoundError,
    );
  });

  it("surfaces a pull_request artifact on a FAILED run, alongside the failed pill (AC14)", async () => {
    queryMock.getRunById.mockResolvedValue(vrun({ status: "failed", effective_status: "failed" }));
    queryMock.getRunArtifacts.mockResolvedValue([
      {
        id: "art1",
        run_id: "r1",
        type: "pull_request",
        title: "Bump lodash",
        url: "https://github.com/llipe/x/pull/42",
        storage_path: null,
        metadata: {},
        created_at: new Date().toISOString(),
      },
    ]);

    const ui = await RunDetailPage({ params: Promise.resolve({ id: "r1" }) });
    render(ui);

    expect(screen.getByText("failed")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /bump lodash/i });
    expect(link).toHaveAttribute("href", "https://github.com/llipe/x/pull/42");
    // The log region is aria-live (AC8).
    expect(screen.getByRole("log", { name: /run log/i })).toHaveAttribute("aria-live", "polite");
  });

  it("renders a terminal-state banner for a timed_out run with the reaper text (AC6)", async () => {
    queryMock.getRunById.mockResolvedValue(
      vrun({
        status: "timed_out",
        effective_status: "timed_out",
        outcome: null,
        error_message: "No terminal status after 3720s; reaped by reap_stale_runs.",
      }),
    );

    const ui = await RunDetailPage({ params: Promise.resolve({ id: "r2" }) });
    render(ui);

    expect(screen.getByText(/run timed out/i)).toBeInTheDocument();
    expect(screen.getByText(/reaped by reap_stale_runs/i)).toBeInTheDocument();
  });
});
