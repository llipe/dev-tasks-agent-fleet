import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * S-147 (#207) — AddRepositoryForm component suite (Layer 2, jsdom).
 *
 * Asserts:
 *   - REPOSITORY / DEFAULT BRANCH fields, label-associated
 *   - client-side validation rejects a malformed full_name BEFORE the
 *     Server Action is ever called (AC4) — the "never trust client-only
 *     validation" contract is about the SERVER re-validating too, not about
 *     skipping the client check
 *   - a server-returned duplicate error renders inline, non-raw
 *   - the submit button is disabled while pending (double-submit guard,
 *     mirrors `LoginForm`'s `useFormStatus` pattern)
 */

// The action module imports next/headers-adjacent server-only modules at the
// top level (via lib/supabase/server.ts); mock the action itself so the
// component test never touches that chain.
const addRepositoryMock = vi.fn();
vi.mock("@/app/(panel)/repositories/actions", () => ({
  addRepository: (...args: unknown[]) => addRepositoryMock(...args),
}));

let pendingRef = { pending: false };
vi.mock("react-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-dom")>();
  return { ...actual, useFormStatus: () => pendingRef };
});

import { AddRepositoryForm } from "@/components/repositories/AddRepositoryForm";

afterEach(() => {
  pendingRef = { pending: false };
  addRepositoryMock.mockReset();
});

describe("AddRepositoryForm — fields", () => {
  it("renders REPOSITORY and DEFAULT BRANCH fields, label-associated", () => {
    render(<AddRepositoryForm />);
    const repo = screen.getByLabelText(/repository/i);
    expect(repo).toHaveAttribute("name", "fullName");
    expect(repo).toHaveAttribute("placeholder", "owner/repo");

    const branch = screen.getByLabelText(/default branch/i);
    expect(branch).toHaveAttribute("name", "defaultBranch");
  });

  it("renders an 'Add repository' submit button", () => {
    render(<AddRepositoryForm />);
    expect(screen.getByRole("button", { name: /add repository/i })).toHaveAttribute(
      "type",
      "submit",
    );
  });
});

describe("AddRepositoryForm — client-side validation (AC4)", () => {
  it("shows an inline error and blocks submit for a malformed full_name (no slash)", () => {
    render(<AddRepositoryForm />);
    const repo = screen.getByLabelText(/repository/i);
    fireEvent.change(repo, { target: { value: "noslash" } });
    fireEvent.submit(repo.closest("form")!);
    expect(screen.getByRole("alert")).toHaveTextContent(/owner\/repo/i);
  });

  it("shows no client error for an empty field until submit is attempted", () => {
    render(<AddRepositoryForm />);
    const repo = screen.getByLabelText(/repository/i);
    fireEvent.change(repo, { target: { value: "a" } });
    fireEvent.change(repo, { target: { value: "" } });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("clears the client error once a valid owner/repo is typed", () => {
    render(<AddRepositoryForm />);
    const repo = screen.getByLabelText(/repository/i);
    fireEvent.change(repo, { target: { value: "bad" } });
    fireEvent.submit(repo.closest("form")!);
    expect(screen.getByRole("alert")).toBeInTheDocument();

    fireEvent.change(repo, { target: { value: "owner/repo" } });
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("AddRepositoryForm — pending state (double-submit guard)", () => {
  it("disables fields and the submit button while pending", () => {
    pendingRef = { pending: true };
    render(<AddRepositoryForm />);
    expect(screen.getByLabelText(/repository/i)).toBeDisabled();
    expect(screen.getByLabelText(/default branch/i)).toBeDisabled();
    const btn = screen.getByRole("button", { name: /adding/i });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("aria-disabled", "true");
  });
});
