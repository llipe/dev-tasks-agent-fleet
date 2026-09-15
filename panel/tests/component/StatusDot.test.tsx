import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusDot } from "@/components/StatusDot";
import type { RunStatus } from "@/lib/domain/status";

describe("StatusDot", () => {
  it.each<[RunStatus, string]>([
    ["running", "running"],
    ["queued", "queued"],
    ["succeeded", "succeeded"],
    ["failed", "failed"],
    ["timed_out", "timed out"],
    ["failed_to_start", "failed to start"],
    ["canceled", "canceled"],
  ])("exposes an accessible label for %s", (status, label) => {
    render(<StatusDot status={status} />);
    // role="img" + aria-label makes the dot itself announce the status.
    expect(screen.getByRole("img", { name: label })).toBeInTheDocument();
  });

  it("is hidden from assistive tech when decorative (text carries the meaning)", () => {
    const { container } = render(<StatusDot status="succeeded" decorative />);
    expect(container.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it.each<[number]>([[5], [6], [7]])("renders at size %spx", (size) => {
    render(<StatusDot status="running" size={size as 5 | 6 | 7} />);
    expect(screen.getByRole("img", { name: "running" })).toBeInTheDocument();
  });

  it("renders a neutral fallback for an unknown status without crashing (EC)", () => {
    render(<StatusDot status={"weird" as RunStatus} />);
    expect(screen.getByRole("img", { name: "weird" })).toBeInTheDocument();
  });

  it("renders queued with the spin class, not the pulse class (AC1/S-142)", () => {
    render(<StatusDot status="queued" />);
    const dot = screen.getByRole("img", { name: "queued" });
    expect(dot.className).toMatch(/spin/);
    expect(dot.className).not.toMatch(/pulse/);
  });

  it("renders running with the pulse class, not the spin class, unchanged (AC2/S-142)", () => {
    render(<StatusDot status="running" />);
    const dot = screen.getByRole("img", { name: "running" });
    expect(dot.className).toMatch(/pulse/);
    expect(dot.className).not.toMatch(/spin/);
  });

  it.each<[RunStatus, string]>([
    ["succeeded", "succeeded"],
    ["failed", "failed"],
    ["timed_out", "timed out"],
    ["failed_to_start", "failed to start"],
    ["canceled", "canceled"],
  ])("does not add pulse or spin classes for %s (AC3/S-142)", (status, label) => {
    render(<StatusDot status={status} />);
    const dot = screen.getByRole("img", { name: label });
    expect(dot.className).not.toMatch(/pulse/);
    expect(dot.className).not.toMatch(/spin/);
  });
});
