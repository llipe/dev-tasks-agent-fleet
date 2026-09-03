import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Input } from "@/components/Input";

describe("Input", () => {
  it("renders a text input associated with a label", () => {
    render(
      <>
        <label htmlFor="repo">Repository</label>
        <Input id="repo" placeholder="owner/name" />
      </>,
    );
    const input = screen.getByLabelText("Repository");
    expect(input).toHaveAttribute("type", "text");
    expect(input).toHaveAttribute("placeholder", "owner/name");
  });

  it("renders the small size", () => {
    render(<Input inputSize="sm" aria-label="filter" />);
    expect(screen.getByLabelText("filter")).toBeInTheDocument();
  });

  it("forwards value/onChange", () => {
    const onChange = vi.fn();
    render(<Input aria-label="q" value="" onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("q"), { target: { value: "x" } });
    expect(onChange).toHaveBeenCalled();
  });

  it("honors an explicit type", () => {
    render(<Input type="number" aria-label="count" />);
    expect(screen.getByLabelText("count")).toHaveAttribute("type", "number");
  });
});
