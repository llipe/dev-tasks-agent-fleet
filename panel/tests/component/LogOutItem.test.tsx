import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LogOutItem } from "@/components/shell/LogOutItem";
import { Sidebar } from "@/components/shell/Sidebar";

/**
 * LogOutItem + Sidebar wiring (Story S-120, PRD AC6/AC15) — Layer 2 component.
 *
 * The shell stays presentational: the item is a plain
 * `<form method="post" action="/api/auth/logout">` with a submit button, so it
 * works without JS and needs no client handler. Coverage:
 *   - a POST form pointing at the logout route (AC6 affordance)
 *   - rendered in the Sidebar footer BELOW "System health" and ABOVE "Collapse"
 *     (AC15 ordering)
 *   - icon-only when the sidebar is collapsed (AC15)
 *   - ABSENT when unauthenticated (AC15)
 *   - keyboard-operable submit control (accessibility)
 */

// The Sidebar reads the active route via usePathname.
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
}));

/** The logout `<form>` inside a rendered subtree, located by its action. */
function logoutForm(root: HTMLElement): HTMLFormElement | null {
  return root.querySelector<HTMLFormElement>('form[action="/api/auth/logout"]');
}

describe("LogOutItem — the POST form (AC6)", () => {
  it("renders a POST form whose action is the logout route", () => {
    const { container } = render(<LogOutItem collapsed={false} />);
    const form = logoutForm(container);
    expect(form).not.toBeNull();
    expect(form).toHaveAttribute("method", "post");
    expect(form).toHaveAttribute("action", "/api/auth/logout");
  });

  it("exposes a keyboard-operable submit button labeled Log out", () => {
    render(<LogOutItem collapsed={false} />);
    const button = screen.getByRole("button", { name: /log out/i });
    expect(button).toHaveAttribute("type", "submit");
    // Native <button type=submit> is inherently keyboard-operable (Enter/Space)
    // and focusable; assert it is not removed from the tab order.
    expect(button).not.toHaveAttribute("tabindex", "-1");
    expect(button).not.toBeDisabled();
  });

  it("shows the label when expanded and hides it when collapsed (icon-only)", () => {
    const { rerender } = render(<LogOutItem collapsed={false} />);
    // Expanded: the visible text label is present.
    expect(screen.getByText("Log out")).toBeInTheDocument();

    rerender(<LogOutItem collapsed={true} />);
    // Collapsed: no visible text label, but the control keeps an accessible name.
    expect(screen.queryByText("Log out")).toBeNull();
    expect(screen.getByRole("button", { name: /log out/i })).toBeInTheDocument();
  });
});

describe("Sidebar — Log out placement and gating (AC15)", () => {
  it("renders Log out below System health and above Collapse when authenticated", () => {
    const { container } = render(
      <Sidebar collapsed={false} onToggle={() => {}} authenticated={true} />,
    );

    const logout = screen.getByRole("button", { name: /log out/i });
    const collapse = screen.getByRole("button", { name: /collapse sidebar/i });
    const systemHealth = screen.getByLabelText(/system health — not available/i);

    // DOM order encodes visual order: System health → Log out → Collapse.
    // compareDocumentPosition: FOLLOWING (4) means the argument comes AFTER.
    expect(systemHealth.compareDocumentPosition(logout) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(logout.compareDocumentPosition(collapse) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );

    // And the logout affordance is the POST form.
    expect(logoutForm(container)).not.toBeNull();
  });

  it("does NOT render Log out when unauthenticated", () => {
    const { container } = render(
      <Sidebar collapsed={false} onToggle={() => {}} authenticated={false} />,
    );
    expect(screen.queryByRole("button", { name: /log out/i })).toBeNull();
    expect(logoutForm(container)).toBeNull();
    // The Collapse control is still present (only the logout item is gated).
    expect(screen.getByRole("button", { name: /collapse sidebar/i })).toBeInTheDocument();
  });

  it("renders Log out icon-only when collapsed and authenticated", () => {
    render(<Sidebar collapsed={true} onToggle={() => {}} authenticated={true} />);
    const button = screen.getByRole("button", { name: /log out/i });
    expect(button).toBeInTheDocument();
    // No visible text label in the collapsed footer.
    expect(within(button).queryByText("Log out")).toBeNull();
  });
});
