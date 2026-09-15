import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RepositoryRow } from "@/lib/supabase/types";

/**
 * S-147 (#207) / S-148 (#208) — RepositoryTable component suite (Layer 2, jsdom).
 *
 * Asserts:
 *   - lists `full_name`, `default_branch`, and enabled state (AC1)
 *   - archived rows are hidden by default (the caller — `page.tsx` — already
 *     calls `getRepositories(client)` with archived excluded; this component
 *     just renders whatever rows it is given, so this suite asserts the
 *     component renders exactly the rows passed, with no archived-filtering
 *     logic duplicated here)
 *   - an empty list renders a legible empty state, not a blank region or an
 *     error (EC — empty repositories table)
 *   - S-148: an "Archive" button per row opens a confirm dialog (the panel's
 *     FIRST destructive-action confirm dialog); Cancel closes it without
 *     calling the action; Confirm calls the `archiveRepository` Server
 *     Action and, on success, closes the dialog and refreshes the route
 *     (`router.refresh()`) so the archived row disappears on the next
 *     server render; a server-returned failure keeps the dialog open with an
 *     inline error, never a silent failure.
 *   - no "restore" affordance exists anywhere (AC6, absence check).
 */

// The action module imports next/headers-adjacent server-only modules at the
// top level (via lib/supabase/server.ts); mock the action itself so the
// component test never touches that chain (same pattern as AddRepositoryForm.test.tsx).
const archiveRepositoryMock = vi.fn();
vi.mock("@/app/(panel)/repositories/actions", () => ({
  archiveRepository: (...args: unknown[]) => archiveRepositoryMock(...args),
}));

const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh }),
}));

import { RepositoryTable } from "@/components/repositories/RepositoryTable";

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

afterEach(() => {
  archiveRepositoryMock.mockReset();
  refresh.mockReset();
});

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

describe("RepositoryTable — Archive action + confirm dialog (S-148, AC1/AC2)", () => {
  it("renders an Archive button per row", () => {
    render(<RepositoryTable rows={[row({ id: "r1" }), row({ id: "r2" })]} />);
    expect(screen.getAllByRole("button", { name: /archive/i })).toHaveLength(2);
  });

  it("clicking Archive opens a confirm dialog naming the repository, without calling the action yet", () => {
    render(<RepositoryTable rows={[row({ full_name: "acme/widgets" })]} />);
    fireEvent.click(screen.getByRole("button", { name: /^archive$/i }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveTextContent(/acme\/widgets/);
    expect(archiveRepositoryMock).not.toHaveBeenCalled();
  });

  it("Cancel closes the dialog without calling the action", () => {
    render(<RepositoryTable rows={[row()]} />);
    fireEvent.click(screen.getByRole("button", { name: /^archive$/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(archiveRepositoryMock).not.toHaveBeenCalled();
  });

  it("Confirm calls the archiveRepository action with the row id, then closes the dialog and refreshes the route on success", async () => {
    archiveRepositoryMock.mockResolvedValue({ ok: true });
    render(<RepositoryTable rows={[row({ id: "repo-42" })]} />);

    fireEvent.click(screen.getByRole("button", { name: /^archive$/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));

    await waitFor(() => expect(archiveRepositoryMock).toHaveBeenCalledTimes(1));
    const [, formData] = archiveRepositoryMock.mock.calls[0] as [unknown, FormData];
    expect(formData.get("id")).toBe("repo-42");

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  });

  it("a failed archive keeps the dialog open and shows an inline error, never a silent failure", async () => {
    archiveRepositoryMock.mockResolvedValue({
      ok: false,
      code: "DATABASE_ERROR",
      message: "Could not archive the repository. Try again.",
    });
    render(<RepositoryTable rows={[row()]} />);

    fireEvent.click(screen.getByRole("button", { name: /^archive$/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));

    await waitFor(() => expect(archiveRepositoryMock).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/could not archive/i);
    expect(refresh).not.toHaveBeenCalled();
  });
});

describe("RepositoryTable — no restore affordance anywhere (AC6, absence check)", () => {
  it("never renders a restore button, including for an archived row rendered via includeArchived (defensive)", async () => {
    render(<RepositoryTable rows={[row({ archived_at: "2026-01-02T00:00:00.000Z" })]} />);
    expect(screen.queryByRole("button", { name: /restore/i })).toBeNull();

    // Also confirm the confirm-dialog itself never grows a restore affordance.
    fireEvent.click(screen.getByRole("button", { name: /^archive$/i }));
    expect(screen.queryByRole("button", { name: /restore/i })).toBeNull();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    });
  });
});
