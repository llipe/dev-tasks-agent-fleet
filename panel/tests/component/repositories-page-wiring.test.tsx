import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

/**
 * Page-wiring test for `app/(panel)/repositories/page.tsx` (Story S-147,
 * issue #207, FR15).
 *
 * Asserts the wiring unique to this route:
 *  - it calls `getRepositories` WITHOUT `includeArchived` (defaults to
 *    excluding archived rows) — the default `/repositories` list view (AC1)
 *  - it renders the returned rows via `RepositoryTable`
 *  - it renders the `AddRepositoryForm`
 *  - an empty repositories table renders the table's own empty state, not a
 *    page-level error (EC)
 *
 * S-148 (#208): `RepositoryTable` now renders a client-side Archive action
 * (`useRouter` + the `archiveRepository` Server Action), so this page-wiring
 * test mocks both `next/navigation` and the actions module — the same
 * boundary-mocking pattern `AddRepositoryForm.test.tsx`/`RepositoryTable.test.tsx`
 * already use — so this suite stays scoped to page-level wiring only.
 */

vi.mock("@/lib/supabase/server", () => ({ createServerClient: () => ({}) }));

const { getRepositories } = vi.hoisted(() => ({
  getRepositories: vi.fn().mockResolvedValue([]),
}));
vi.mock("@/lib/supabase/queries", () => ({ getRepositories }));

vi.mock("@/app/(panel)/repositories/actions", () => ({
  addRepository: vi.fn(),
  archiveRepository: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

import RepositoriesPage from "@/app/(panel)/repositories/page";

afterEach(() => {
  cleanup();
  getRepositories.mockReset();
  getRepositories.mockResolvedValue([]);
});

function fixtureRepo(overrides: Partial<Record<string, unknown>> = {}) {
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

describe("/repositories page wiring (S-147, FR15/FR16/FR18)", () => {
  it("calls getRepositories without includeArchived (defaults to excluding archived)", async () => {
    const ui = await RepositoriesPage();
    render(ui);

    expect(getRepositories).toHaveBeenCalledWith(expect.anything());
    const call = getRepositories.mock.calls[0];
    expect(call.length).toBe(1);
  });

  it("renders the returned rows via RepositoryTable", async () => {
    getRepositories.mockResolvedValue([fixtureRepo({ full_name: "acme/widgets" })]);
    const ui = await RepositoriesPage();
    render(ui);
    expect(screen.getByText("acme/widgets")).toBeInTheDocument();
  });

  it("renders the Add-repository form", async () => {
    const ui = await RepositoriesPage();
    render(ui);
    expect(screen.getByRole("button", { name: /add repository/i })).toBeInTheDocument();
  });

  it("renders an empty state, not an error, when getRepositories returns []", async () => {
    const ui = await RepositoriesPage();
    render(ui);
    expect(screen.getByRole("status")).toHaveTextContent(/no repositories/i);
  });
});
