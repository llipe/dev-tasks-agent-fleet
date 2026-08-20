import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "../status-badge";

describe("StatusBadge", () => {
  it("renders 'Success' text for success status", () => {
    render(<StatusBadge status="success" />);
    expect(screen.getByText("Success")).toBeInTheDocument();
  });

  it("renders 'Running' text for running status", () => {
    render(<StatusBadge status="running" />);
    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it("renders 'Failed' text for failed status", () => {
    render(<StatusBadge status="failed" />);
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("renders 'Incomplete' text for incomplete status", () => {
    render(<StatusBadge status="incomplete" />);
    expect(screen.getByText("Incomplete")).toBeInTheDocument();
  });

  it("applies status-specific background color class for success", () => {
    const { container } = render(<StatusBadge status="success" />);
    const badge = container.firstElementChild as HTMLElement;
    expect(badge.className).toContain("bg-status-success-bg");
    expect(badge.className).toContain("text-status-success-fg");
  });

  it("applies status-specific background color class for running", () => {
    const { container } = render(<StatusBadge status="running" />);
    const badge = container.firstElementChild as HTMLElement;
    expect(badge.className).toContain("bg-status-running-bg");
    expect(badge.className).toContain("text-status-running-fg");
  });

  it("applies status-specific color classes for failed (red)", () => {
    const { container } = render(<StatusBadge status="failed" />);
    const badge = container.firstElementChild as HTMLElement;
    expect(badge.className).toContain("bg-status-failed-bg");
    expect(badge.className).toContain("text-status-failed-fg");
  });

  it("applies status-specific color classes for incomplete (amber)", () => {
    const { container } = render(<StatusBadge status="incomplete" />);
    const badge = container.firstElementChild as HTMLElement;
    expect(badge.className).toContain("bg-status-incomplete-bg");
    expect(badge.className).toContain("text-status-incomplete-fg");
  });

  it("always displays text label (accessibility)", () => {
    const { container } = render(<StatusBadge status="success" />);
    // Badge must have visible text, not be empty or icon-only
    expect(container.textContent).toBe("Success");
  });

  it("does not contain any hardcoded color values", () => {
    const { container } = render(<StatusBadge status="failed" />);
    const badge = container.firstElementChild as HTMLElement;
    // Must not have inline styles with hardcoded colors
    expect(badge.getAttribute("style")).toBeNull();
    // Class names must use token-based utilities, not arbitrary values
    expect(badge.className).not.toMatch(/#[0-9a-fA-F]{3,8}/);
    expect(badge.className).not.toMatch(/rgb\(/);
  });

  it("does not render any animated elements", () => {
    const { container } = render(<StatusBadge status="running" />);
    // Should not have animation classes
    expect(container.innerHTML).not.toContain("animate-");
  });
});
