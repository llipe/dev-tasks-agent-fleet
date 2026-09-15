import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RepositoryTable } from "@/components/repositories/RepositoryTable";
import type { RepositoryRow } from "@/lib/supabase/types";

/**
 * S-147 (#207) — RepositoryTable component suite (Layer 2, jsdom).
 *
 * Asserts:
 *   - lists `full_name`, `default_branch`, and enabled state (AC1)
 *   - archived rows are hidden by default (the caller — `page.tsx` — already
 *     calls `getRepositories(client)` with archived excluded; this component
 *     just renders whatever rows it is given, so this suite asserts the
 *     component renders exactly the rows passed, with no archived-filtering
 *     logic duplicated here — S-148 will extend this file for its own
 *     default-view-excludes-archived regression once the archive action
 *     exists)
 *   - an empty list renders a legible empty state, not a blank region or an
 *     error (EC — empty repositories table)
 *   - no Archive action exists in this story's markup (S-148 scope, not yet
 *     built — confirmed by absence)
 */

function row(overrides: Partial<RepositoryRow> = {}): RepositoryRow {
  return {
    id: "repo-1",
    installation_id: "inst-1",
    github_repo_id: null,
    full_name: "acme/widgets",
    default_branch: "main",
    is_enabled: true,
    metadata: {},
    archived_at: null,
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}

describe("RepositoryTable — lists rows (AC1)", () => {
  it("renders full_name, default_branch, and enabled state for each row", () => {
    render(
      <RepositoryTable
        rows={[
          row({ id: "r1", full_name: "acme/widgets", default_branch: "main", is_enabled: true }),
          row({
            id: "r2",
            full_name: "acme/gadgets",
            default_branch: "develop",
            is_enabled: false,
          }),
        ]}
      />,
    );

    expect(screen.getByText("acme/widgets")).toBeInTheDocument();
    expect(screen.getByText("main")).toBeInTheDocument();
    expect(screen.getByText("acme/gadgets")).toBeInTheDocument();
    expect(screen.getByText("develop")).toBeInTheDocument();

    const enabledTags = screen.getAllByText(/enabled/i);
    const disabledTags = screen.getAllByText(/disabled/i);
    expect(enabledTags.length).toBeGreaterThan(0);
    expect(disabledTags.length).toBeGreaterThan(0);
  });

  it("renders a semantic table for assistive tech", () => {
    render(<RepositoryTable rows={[row()]} />);
    expect(screen.getByRole("table", { name: /repositories/i })).toBeInTheDocument();
  });
});

describe("RepositoryTable — empty state (EC)", () => {
  it("renders a legible empty state, not a blank region or an error, for zero rows", () => {
    render(<RepositoryTable rows={[]} />);
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent(/no repositories/i);
  });
});

describe("RepositoryTable — no Archive action yet (S-148 scope, absence check)", () => {
  it("does not render any Archive button (S-148 has not shipped)", () => {
    render(<RepositoryTable rows={[row()]} />);
    expect(screen.queryByRole("button", { name: /archive/i })).toBeNull();
  });
});
