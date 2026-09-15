import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { RunFilterBar } from "@/components/runs/RunFilterBar";
import type { RunFilter } from "@/lib/domain/run-filter";
import type { RunStatusCounts } from "@/lib/supabase/queries";

/**
 * Layer 2 (component) tests for the Run History filter bar (S-143,
 * `RunFilterBar.test.tsx`, spec §8.1).
 *
 * Covers: segmented control + chips + search drive the URL via
 * `router.replace`; the 300ms search debounce; the debounce-vs-immediate-click
 * race (test-plan §5.3 gap); the empty-state connection indicator's single
 * reachable "Connected" state (spec §8.1 v1.1 addendum).
 */

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));

afterEach(() => {
  cleanup();
  replace.mockClear();
  vi.useRealTimers();
});

function defaultFilter(overrides: Partial<RunFilter> = {}): RunFilter {
  return {
    status: "all",
    repositoryId: null,
    search: null,
    agentSlug: null,
    page: 1,
    ...overrides,
  };
}

function zeroCounts(overrides: Partial<RunStatusCounts> = {}): RunStatusCounts {
  return {
    all: 0,
    queued: 0,
    running: 0,
    succeeded: 0,
    failed: 0,
    timed_out: 0,
    failed_to_start: 0,
    canceled: 0,
    ...overrides,
  };
}

describe("RunFilterBar — segmented control", () => {
  it("renders every status option with its live count, plus 'all'", () => {
    render(
      <RunFilterBar
        basePath="/agents/dependency-update"
        filter={defaultFilter()}
        statusCounts={zeroCounts({ failed: 3, all: 5 })}
        repositories={[]}
      />,
    );
    const failedOption = screen.getByRole("button", { name: "failed filter, 3 runs" });
    expect(failedOption).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "all filter, 5 runs" })).toBeInTheDocument();
  });

  it("clicking a status option replaces the URL with that status and resets page to 1", () => {
    render(
      <RunFilterBar
        basePath="/agents/dependency-update"
        filter={defaultFilter({ page: 3 })}
        statusCounts={zeroCounts()}
        repositories={[]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "failed filter, 0 runs" }));
    expect(replace).toHaveBeenCalledWith("/agents/dependency-update?status=failed");
  });

  it("marks the active status option aria-pressed", () => {
    render(
      <RunFilterBar
        basePath="/agents/dependency-update"
        filter={defaultFilter({ status: "succeeded" })}
        statusCounts={zeroCounts()}
        repositories={[]}
      />,
    );
    expect(screen.getByRole("button", { name: "succeeded filter, 0 runs" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "failed filter, 0 runs" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});

describe("RunFilterBar — repository chips", () => {
  it("renders 'All repos' plus one chip per repository", () => {
    render(
      <RunFilterBar
        basePath="/agents/dependency-update"
        filter={defaultFilter()}
        statusCounts={zeroCounts()}
        repositories={[
          { id: "r1", fullName: "org/repo-one" },
          { id: "r2", fullName: "org/repo-two" },
        ]}
      />,
    );
    expect(screen.getByRole("button", { name: "All repos" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "org/repo-one" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "org/repo-two" })).toBeInTheDocument();
  });

  it("clicking a repo chip replaces the URL with that repositoryId", () => {
    render(
      <RunFilterBar
        basePath="/agents/dependency-update"
        filter={defaultFilter()}
        statusCounts={zeroCounts()}
        repositories={[{ id: "r1", fullName: "org/repo-one" }]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "org/repo-one" }));
    expect(replace).toHaveBeenCalledWith("/agents/dependency-update?repo=r1");
  });

  it("combining a repo chip with an existing status filter keeps both in the URL (intersection)", () => {
    render(
      <RunFilterBar
        basePath="/agents/dependency-update"
        filter={defaultFilter({ status: "failed" })}
        statusCounts={zeroCounts()}
        repositories={[{ id: "r1", fullName: "org/repo-one" }]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "org/repo-one" }));
    const url = new URL(replace.mock.calls[0]![0], "http://x");
    expect(url.searchParams.get("status")).toBe("failed");
    expect(url.searchParams.get("repo")).toBe("r1");
  });

  it("does not render a repository chip group when there are no repositories", () => {
    render(
      <RunFilterBar
        basePath="/agents/dependency-update"
        filter={defaultFilter()}
        statusCounts={zeroCounts()}
        repositories={[]}
      />,
    );
    expect(screen.queryByRole("group", { name: "Filter by repository" })).toBeNull();
  });
});

describe("RunFilterBar — search debounce", () => {
  it("debounces the search input by 300ms before replacing the URL", () => {
    vi.useFakeTimers();
    render(
      <RunFilterBar
        basePath="/agents/dependency-update"
        filter={defaultFilter()}
        statusCounts={zeroCounts()}
        repositories={[]}
      />,
    );
    fireEvent.change(screen.getByPlaceholderText(/search repository or run id/i), {
      target: { value: "foo" },
    });
    expect(replace).not.toHaveBeenCalled();
    vi.advanceTimersByTime(299);
    expect(replace).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(replace).toHaveBeenCalledWith("/agents/dependency-update?q=foo");
  });

  it("does not fire a stale debounced write after an immediate status click preempts it (§5.3 race)", () => {
    vi.useFakeTimers();
    render(
      <RunFilterBar
        basePath="/agents/dependency-update"
        filter={defaultFilter()}
        statusCounts={zeroCounts()}
        repositories={[]}
      />,
    );
    fireEvent.change(screen.getByPlaceholderText(/search repository or run id/i), {
      target: { value: "foo" },
    });
    // Click a status chip BEFORE the 300ms debounce fires.
    fireEvent.click(screen.getByRole("button", { name: "failed filter, 0 runs" }));
    expect(replace).toHaveBeenCalledTimes(1);
    const [immediateUrl] = replace.mock.calls[0]!;
    const parsed = new URL(immediateUrl, "http://x");
    // The immediate push folds in the in-flight search value AND the status click.
    expect(parsed.searchParams.get("status")).toBe("failed");
    expect(parsed.searchParams.get("q")).toBe("foo");

    // Advance past the original debounce window — the canceled timer must not fire.
    vi.advanceTimersByTime(1000);
    expect(replace).toHaveBeenCalledTimes(1);
  });
});

describe("RunFilterBar — clear filters", () => {
  it("renders a 'Clear filters' control only when a filter is active", () => {
    const { rerender } = render(
      <RunFilterBar
        basePath="/agents/dependency-update"
        filter={defaultFilter()}
        statusCounts={zeroCounts()}
        repositories={[]}
      />,
    );
    expect(screen.queryByRole("button", { name: /clear filters/i })).toBeNull();

    rerender(
      <RunFilterBar
        basePath="/agents/dependency-update"
        filter={defaultFilter({ status: "failed" })}
        statusCounts={zeroCounts()}
        repositories={[]}
      />,
    );
    expect(screen.getByRole("button", { name: /clear filters/i })).toBeInTheDocument();
  });

  it("clicking 'Clear filters' replaces the URL with the bare unfiltered path", () => {
    render(
      <RunFilterBar
        basePath="/agents/dependency-update"
        filter={defaultFilter({ status: "failed", repositoryId: "r1", search: "foo" })}
        statusCounts={zeroCounts()}
        repositories={[]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /clear filters/i }));
    expect(replace).toHaveBeenCalledWith("/agents/dependency-update");
  });
});

describe("RunFilterBar — connection indicator (spec §8.1 v1.1 addendum)", () => {
  it("renders the single reachable state: 'Connected'", () => {
    render(
      <RunFilterBar
        basePath="/agents/dependency-update"
        filter={defaultFilter()}
        statusCounts={zeroCounts()}
        repositories={[]}
      />,
    );
    expect(screen.getByText(/connected/i)).toBeInTheDocument();
    expect(screen.queryByText(/disconnected/i)).toBeNull();
  });
});
