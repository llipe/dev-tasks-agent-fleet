import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NavItem } from "@/components/NavItem";

describe("NavItem", () => {
  it("renders a link with its label and icon", () => {
    render(<NavItem href="/agents" icon={<svg data-testid="icon" />} label="Agents" />);
    const link = screen.getByRole("link", { name: /Agents/ });
    expect(link).toHaveAttribute("href", "/agents");
    expect(screen.getByTestId("icon")).toBeInTheDocument();
  });

  it("marks the active item with aria-current=page", () => {
    render(<NavItem href="/agents" icon={<svg />} label="Agents" active />);
    expect(screen.getByRole("link", { name: /Agents/ })).toHaveAttribute("aria-current", "page");
  });

  it("renders a badge when supplied and not collapsed", () => {
    render(<NavItem href="/runs" icon={<svg />} label="All runs" badge={12} />);
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("hides the label text but preserves an accessible name when collapsed", () => {
    render(<NavItem href="/agents" icon={<svg />} label="Agents" badge={9} collapsed />);
    const link = screen.getByRole("link", { name: "Agents" });
    // Collapsed: visible label text and badge are not rendered...
    expect(screen.queryByText("9")).not.toBeInTheDocument();
    // ...but the accessible name is still "Agents" (via aria-label).
    expect(link).toHaveAttribute("aria-label", "Agents");
  });
});
