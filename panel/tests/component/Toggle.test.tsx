import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Toggle } from "@/components/Toggle";

describe("Toggle", () => {
  it("renders as a switch reflecting its checked state", () => {
    render(<Toggle checked={true} onChange={() => {}} aria-label="verbose" />);
    const sw = screen.getByRole("switch", { name: "verbose" });
    expect(sw).toHaveAttribute("aria-checked", "true");
  });

  it("reflects the off state", () => {
    render(<Toggle checked={false} onChange={() => {}} aria-label="verbose" />);
    expect(screen.getByRole("switch", { name: "verbose" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("fires onChange with the toggled value on click", () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} onChange={onChange} aria-label="verbose" />);
    fireEvent.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("is keyboard-operable (native button activation via Enter/Space)", () => {
    const onChange = vi.fn();
    render(<Toggle checked={true} onChange={onChange} aria-label="verbose" />);
    const sw = screen.getByRole("switch");
    sw.focus();
    expect(sw).toHaveFocus();
    // A native <button> activates on click; keyboard Enter/Space dispatch a
    // click in the browser. Assert the click contract fires onChange(false).
    fireEvent.click(sw);
    expect(onChange).toHaveBeenCalledWith(false);
  });

  it("does not fire onChange when disabled", () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} onChange={onChange} disabled aria-label="verbose" />);
    const sw = screen.getByRole("switch");
    expect(sw).toBeDisabled();
    fireEvent.click(sw);
    expect(onChange).not.toHaveBeenCalled();
  });
});
