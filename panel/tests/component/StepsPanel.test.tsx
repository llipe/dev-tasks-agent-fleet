import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import { StepsPanel } from "@/components/run-detail/StepsPanel";
import type { StepPanelRow } from "@/lib/domain/run-detail";

/**
 * Layer 2 (component) — StepsPanel (Story S-145, FR9/FR10).
 *
 * DESIGN §5.3: a vertical list of step rows (colored dot, mono name,
 * duration, event count). Clicking a row sets the step filter; a visible
 * "All steps" control clears it back to the full tail.
 */

function row(overrides: Partial<StepPanelRow> = {}): StepPanelRow {
  return {
    id: "step-1",
    title: "Checkout",
    status: "succeeded",
    duration: "3m 04s",
    eventCount: 12,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
});

describe("StepsPanel — renders each run_steps row (AC1 / FR9)", () => {
  it("renders the name, duration, and event count for each step", () => {
    render(
      <StepsPanel
        steps={[row(), row({ id: "step-2", title: "npm_audit", duration: "12s", eventCount: 3 })]}
        selectedStepId={null}
        onSelectStep={vi.fn()}
      />,
    );
    expect(screen.getByText("Checkout")).toBeInTheDocument();
    expect(screen.getByText("3m 04s")).toBeInTheDocument();
    expect(screen.getByText("12 ev")).toBeInTheDocument();
    expect(screen.getByText("npm_audit")).toBeInTheDocument();
    expect(screen.getByText("12s")).toBeInTheDocument();
    expect(screen.getByText("3 ev")).toBeInTheDocument();
  });

  it("gives each step row a colored status dot driven by run_steps.status", () => {
    render(
      <StepsPanel
        steps={[row({ id: "s1", status: "failed", title: "Audit" })]}
        selectedStepId={null}
        onSelectStep={vi.fn()}
      />,
    );
    // StatusDot is decorative here (the row's own text carries the meaning);
    // it renders as an aria-hidden element, so query by the accessible name
    // it would have carried instead (aria-label) is skipped — instead confirm
    // the step name/label context is present alongside a dot element.
    const item = screen.getByRole("button", { name: /audit/i });
    expect(within(item).getByLabelText("failed")).toBeInTheDocument();
  });

  it("renders an empty panel for a zero-step run — not an error (edge case)", () => {
    const { container } = render(
      <StepsPanel steps={[]} selectedStepId={null} onSelectStep={vi.fn()} />,
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(container.querySelector("[data-steps-panel]")).toBeInTheDocument();
  });

  it("a zero-event step shows event count 0, not blank or a crash (edge case)", () => {
    render(
      <StepsPanel
        steps={[row({ id: "s1", eventCount: 0 })]}
        selectedStepId={null}
        onSelectStep={vi.fn()}
      />,
    );
    expect(screen.getByText("0 ev")).toBeInTheDocument();
  });
});

describe("StepsPanel — click-to-filter (AC2 / FR10)", () => {
  it("clicking a step calls onSelectStep with that step's id", () => {
    const onSelectStep = vi.fn();
    render(
      <StepsPanel
        steps={[row({ id: "step-1" }), row({ id: "step-2", title: "npm_audit" })]}
        selectedStepId={null}
        onSelectStep={onSelectStep}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /checkout/i }));
    expect(onSelectStep).toHaveBeenCalledWith("step-1");
  });

  it("shows an 'All steps' control that clears the filter (calls onSelectStep with null)", () => {
    const onSelectStep = vi.fn();
    render(<StepsPanel steps={[row()]} selectedStepId="step-1" onSelectStep={onSelectStep} />);
    fireEvent.click(screen.getByRole("button", { name: /all steps/i }));
    expect(onSelectStep).toHaveBeenCalledWith(null);
  });

  it("marks the selected step's row as pressed for a11y/visual state", () => {
    render(
      <StepsPanel
        steps={[row({ id: "step-1" }), row({ id: "step-2", title: "npm_audit" })]}
        selectedStepId="step-1"
        onSelectStep={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /checkout/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: /npm_audit/i })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("'All steps' is pressed when no step is selected", () => {
    render(<StepsPanel steps={[row()]} selectedStepId={null} onSelectStep={vi.fn()} />);
    expect(screen.getByRole("button", { name: /all steps/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
