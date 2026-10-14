import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentHeader } from "@/components/runs/AgentHeader";
import type { AgentHeader as AgentHeaderData } from "@/lib/domain/run-row";

/**
 * S-164 (#276) — the agent-page scheduled indicator (DESIGN.md §5.7.1): a
 * read-only `N schedules` count in the run-history header linking to
 * `/schedules?agent=<slug>`, with a zero-state. Link-only, no CRUD.
 */

const header: AgentHeaderData = {
  name: "Dependency Update",
  slug: "dependency-update",
  description: "Bumps deps and opens PRs.",
  paramsCount: 2,
  isEnabled: true,
  p50Duration: "2m 10s",
  successRate: 88,
  runCount: 42,
};

describe("AgentHeader scheduled indicator (S-164)", () => {
  it("links `N schedules` to the agent-filtered schedules view", () => {
    render(
      <AgentHeader
        header={header}
        invokeHref="/agents/dependency-update/invoke"
        scheduleCount={3}
      />,
    );
    const link = screen.getByRole("link", { name: "3 schedules" });
    expect(link.getAttribute("href")).toBe("/schedules?agent=dependency-update");
  });

  it("singularizes for exactly one schedule", () => {
    render(<AgentHeader header={header} invokeHref={null} scheduleCount={1} />);
    expect(screen.getByRole("link", { name: "1 schedule" })).toBeTruthy();
  });

  it("renders the zero-state 'No schedules' (still a link to the create view)", () => {
    render(<AgentHeader header={header} invokeHref={null} scheduleCount={0} />);
    const link = screen.getByRole("link", { name: "No schedules" });
    expect(link.getAttribute("href")).toBe("/schedules?agent=dependency-update");
  });

  it("omits the indicator entirely when no count is provided", () => {
    render(<AgentHeader header={header} invokeHref={null} />);
    expect(screen.queryByText(/schedules?/)).toBeNull();
  });
});
