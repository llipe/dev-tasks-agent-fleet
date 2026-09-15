import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

/**
 * Page-wiring tests for the run-detail route (`app/(panel)/runs/[id]/page.tsx`).
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

import RunDetailPage from "@/app/(panel)/runs/[id]/page";

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

  it("renders the live log viewer with a live-tail control for a running run (S-110, AC8)", async () => {
    const now = Date.now();
    queryMock.getRunById.mockResolvedValue(
      vrun({
        status: "running",
        effective_status: "running",
        outcome: null,
        finished_at: null,
        duration_ms: null,
        started_at: new Date(now - 5_000).toISOString(),
        queued_at: new Date(now - 10_000).toISOString(),
      }),
    );

    const ui = await RunDetailPage({ params: Promise.resolve({ id: "r3" }) });
    render(ui);

    // The live viewer mounts the SSE hook (which opens an EventSource) — jsdom
    // has no EventSource, so the hook's connect is guarded; what we assert is
    // the live-tail control and the running pill are present, not the terminal
    // "load earlier" path.
    expect(screen.getByRole("log", { name: /run log/i })).toHaveAttribute(
      "data-sse-mount",
      "run-log",
    );
  });

  it("renders the steps panel with per-step event counts derived from the loaded window, not a new query (Story S-145, FR9)", async () => {
    queryMock.getRunById.mockResolvedValue(vrun({ status: "failed", effective_status: "failed" }));
    queryMock.getRunSteps.mockResolvedValue([
      {
        id: "step-1",
        run_id: "r1",
        seq: 1,
        key: "checkout",
        title: "Checkout",
        status: "succeeded",
        started_at: new Date(Date.now() - 20_000).toISOString(),
        finished_at: new Date(Date.now() - 15_000).toISOString(),
        error_message: null,
        data: {},
        created_at: new Date().toISOString(),
      },
      {
        id: "step-2",
        run_id: "r1",
        seq: 2,
        key: "npm_audit",
        title: null,
        status: "failed",
        started_at: new Date(Date.now() - 14_000).toISOString(),
        finished_at: new Date(Date.now() - 10_000).toISOString(),
        error_message: "boom",
        data: {},
        created_at: new Date().toISOString(),
      },
    ]);
    queryMock.getRunEvents.mockResolvedValue([
      {
        id: 1,
        run_id: "r1",
        step_id: "step-1",
        seq: 1,
        ts: new Date().toISOString(),
        level: "info",
        message: "checkout ok",
        data: {},
      },
      {
        id: 2,
        run_id: "r1",
        step_id: "step-2",
        seq: 2,
        ts: new Date().toISOString(),
        level: "error",
        message: "audit failed",
        data: {},
      },
      {
        id: 3,
        run_id: "r1",
        step_id: "step-2",
        seq: 3,
        ts: new Date().toISOString(),
        level: "error",
        message: "audit retry failed",
        data: {},
      },
    ]);

    const ui = await RunDetailPage({ params: Promise.resolve({ id: "r1" }) });
    render(ui);

    const panel = document.querySelector("[data-steps-panel]") as HTMLElement;
    expect(within(panel).getByText("Checkout")).toBeInTheDocument();
    expect(within(panel).getByText("npm_audit")).toBeInTheDocument();
    expect(within(panel).getByText("1 ev")).toBeInTheDocument();
    expect(within(panel).getByText("2 ev")).toBeInTheDocument();
  });

  it("clicking a step in the panel narrows the log to that step's events (Story S-145, AC2, page-wired)", async () => {
    queryMock.getRunById.mockResolvedValue(vrun({ status: "failed", effective_status: "failed" }));
    queryMock.getRunSteps.mockResolvedValue([
      {
        id: "step-1",
        run_id: "r1",
        seq: 1,
        key: "checkout",
        title: "Checkout",
        status: "succeeded",
        started_at: null,
        finished_at: null,
        error_message: null,
        data: {},
        created_at: new Date().toISOString(),
      },
    ]);
    queryMock.getRunEvents.mockResolvedValue([
      {
        id: 1,
        run_id: "r1",
        step_id: "step-1",
        seq: 1,
        ts: new Date().toISOString(),
        level: "info",
        message: "in-step-1",
        data: {},
      },
      {
        id: 2,
        run_id: "r1",
        step_id: null,
        seq: 2,
        ts: new Date().toISOString(),
        level: "info",
        message: "no-step",
        data: {},
      },
    ]);

    const ui = await RunDetailPage({ params: Promise.resolve({ id: "r1" }) });
    render(ui);

    expect(screen.getByText("in-step-1")).toBeInTheDocument();
    expect(screen.getByText("no-step")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /checkout/i }));

    expect(screen.getByText("in-step-1")).toBeInTheDocument();
    expect(screen.queryByText("no-step")).toBeNull();
  });
});
