import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Tag, type TagVariant } from "@/components/Tag";

describe("Tag", () => {
  it.each<TagVariant>(["accent", "neutral", "outline"])("renders the %s variant", (variant) => {
    render(<Tag variant={variant}>FIXED</Tag>);
    expect(screen.getByText("FIXED")).toBeInTheDocument();
  });

  it("renders the small size", () => {
    render(<Tag size="sm">NO VULNS</Tag>);
    expect(screen.getByText("NO VULNS")).toBeInTheDocument();
  });

  it("defaults to the neutral variant, default size", () => {
    render(<Tag>PARTIAL</Tag>);
    expect(screen.getByText("PARTIAL")).toBeInTheDocument();
  });
});
