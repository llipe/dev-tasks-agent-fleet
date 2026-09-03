import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { KLabel } from "@/components/KLabel";

describe("KLabel", () => {
  it("renders its children as text", () => {
    render(<KLabel>Steps</KLabel>);
    expect(screen.getByText("Steps")).toBeInTheDocument();
  });

  it("merges a caller-supplied className", () => {
    render(<KLabel className="extra">Repository</KLabel>);
    expect(screen.getByText("Repository")).toHaveClass("extra");
  });
});
