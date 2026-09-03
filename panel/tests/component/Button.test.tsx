import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Button, type ButtonVariant, type ButtonSize } from "@/components/Button";

describe("Button", () => {
  it.each<ButtonVariant>(["primary", "secondary", "ghost"])(
    "renders the %s variant as a button",
    (variant) => {
      render(<Button variant={variant}>Run</Button>);
      expect(screen.getByRole("button", { name: "Run" })).toBeInTheDocument();
    },
  );

  it.each<ButtonSize>(["sm", "md", "default"])("renders the %s size", (size) => {
    render(<Button size={size}>Invoke</Button>);
    expect(screen.getByRole("button", { name: "Invoke" })).toBeInTheDocument();
  });

  it("defaults to type=button so it never submits a form implicitly", () => {
    render(<Button>Cancel</Button>);
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveAttribute("type", "button");
  });

  it("honors an explicit type=submit", () => {
    render(<Button type="submit">Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toHaveAttribute("type", "submit");
  });

  it("renders a disabled state and does not fire onClick", () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Run
      </Button>,
    );
    const btn = screen.getByRole("button", { name: "Run" });
    expect(btn).toBeDisabled();
    fireEvent.click(btn);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("fires onClick when enabled", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Run</Button>);
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
