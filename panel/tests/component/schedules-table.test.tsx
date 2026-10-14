import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SchedulesTable, type ScheduleTableRow } from "@/components/schedules/SchedulesTable";
import { buildScheduleCellModel, type ScheduleRowInput } from "@/lib/domain/schedule-row";

/**
 * S-161 (#273) — SchedulesTable component suite (Layer 2, jsdom), against
 * DESIGN.md §5.7: the seven columns, state pills (incl. the hollow paused dot),
 * cadence formats, the unified reason row + its clearable open_pr control, and
 * the pause/resume/edit/delete action wiring.
 */

const NOW = Date.UTC(2026, 9, 13, 10, 0, 0);

function row(overrides: Partial<ScheduleRowInput> & { id: string }): ScheduleTableRow {
  const input: ScheduleRowInput = {
    id: overrides.id,
    state: overrides.state ?? "active",
    agentName: overrides.agentName ?? "Dependency Update",
    agentSlug: overrides.agentSlug ?? "dependency-update",
    repositoryFullName: overrides.repositoryFullName ?? "llipe/thinkfirst-web",
    repositoryBranch: overrides.repositoryBranch ?? "main",
    cadence: overrides.cadence ?? { kind: "daily", minute: 0, hour: 7 },
    timezone: overrides.timezone ?? "America/Santiago",
    nextRunAtMs: overrides.nextRunAtMs ?? NOW + 3600_000,
    blockReason: overrides.blockReason ?? null,
    lastSkippedReason: overrides.lastSkippedReason ?? null,
    prBlockRunId: overrides.prBlockRunId ?? null,
    lastRunStatus: overrides.lastRunStatus ?? "succeeded",
    lastRunOutcome: overrides.lastRunOutcome ?? "fixed",
    lastRunFinishedAtMs: overrides.lastRunFinishedAtMs ?? NOW - 3600_000,
    lastRunId: overrides.lastRunId ?? "r1",
  };
  return {
    id: input.id,
    agentName: input.agentName,
    agentSlug: input.agentSlug,
    repositoryFullName: input.repositoryFullName,
    repositoryBranch: input.repositoryBranch,
    lastRunId: input.lastRunId,
    lastRunAgo: "1h ago",
    flash: false,
    model: buildScheduleCellModel(input, NOW),
  };
}

function handlers() {
  return {
    onPause: vi.fn(),
    onResume: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    onClearPrBlock: vi.fn(),
  };
}

afterEach(() => vi.clearAllMocks());

describe("SchedulesTable", () => {
  it("renders the seven column headers", () => {
    render(<SchedulesTable rows={[]} {...handlers()} />);
    for (const h of [
      "State",
      "Agent",
      "Repository",
      "Cadence",
      "Next run",
      "Last run",
      "Actions",
    ]) {
      expect(screen.getByRole("columnheader", { name: h })).toBeTruthy();
    }
  });

  it("renders agent, cadence, and the active state pill text", () => {
    render(<SchedulesTable rows={[row({ id: "s1" })]} {...handlers()} />);
    expect(screen.getByText("dependency-update")).toBeTruthy();
    expect(screen.getByText("Daily · 07:00")).toBeTruthy();
    expect(screen.getByText("active")).toBeTruthy();
  });

  it("pause action fires onPause; a paused row shows Resume → onResume", () => {
    const h = handlers();
    const { rerender } = render(<SchedulesTable rows={[row({ id: "s1" })]} {...h} />);
    fireEvent.click(screen.getByRole("button", { name: /Pause/ }));
    expect(h.onPause).toHaveBeenCalledWith("s1");

    rerender(
      <SchedulesTable
        rows={[row({ id: "s1", state: "paused", blockReason: "manual_pause" })]}
        {...h}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Resume/ }));
    expect(h.onResume).toHaveBeenCalledWith("s1");
    expect(screen.getByText("paused")).toBeTruthy();
  });

  it("edit + delete icon buttons fire their handlers", () => {
    const h = handlers();
    render(<SchedulesTable rows={[row({ id: "s1" })]} {...h} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit schedule" }));
    expect(h.onEdit).toHaveBeenCalledWith("s1");
    fireEvent.click(screen.getByRole("button", { name: "Delete schedule" }));
    expect(h.onDelete).toHaveBeenCalledWith("s1");
  });

  it("an open_pr block renders a reason chip + the clearable 'resume anyway' control", () => {
    const h = handlers();
    render(
      <SchedulesTable
        rows={[row({ id: "s1", state: "blocked", blockReason: "open_pr", prBlockRunId: "r9" })]}
        {...h}
      />,
    );
    expect(screen.getByText("blocked")).toBeTruthy();
    const clear = screen.getByRole("button", { name: /PR handled · resume anyway/ });
    fireEvent.click(clear);
    expect(h.onClearPrBlock).toHaveBeenCalledWith("s1");
  });

  it("an auto_paused reason chip has no clear control", () => {
    render(
      <SchedulesTable
        rows={[row({ id: "s1", state: "paused", blockReason: "auto_paused:consecutive_failures" })]}
        {...handlers()}
      />,
    );
    expect(screen.queryByRole("button", { name: /resume anyway/ })).toBeNull();
  });

  it("a blocked row shows the 'held' next-run placeholder", () => {
    render(
      <SchedulesTable
        rows={[row({ id: "s1", state: "blocked", blockReason: "open_pr" })]}
        {...handlers()}
      />,
    );
    expect(screen.getByText("held")).toBeTruthy();
  });
});
