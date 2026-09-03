import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Breadcrumb } from "@/components/Breadcrumb";

describe("Breadcrumb", () => {
  it("renders a labelled nav region", () => {
    render(<Breadcrumb items={[{ label: "Agents", href: "/" }, { label: "dependency-update" }]} />);
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeInTheDocument();
  });

  it("renders intermediate items as links and the last as current", () => {
    render(
      <Breadcrumb
        items={[
          { label: "Agents", href: "/agents" },
          { label: "dependency-update", href: "/agents/dependency-update" },
          { label: "01J8XQ2F" },
        ]}
      />,
    );
    expect(screen.getByRole("link", { name: "Agents" })).toHaveAttribute("href", "/agents");
    const current = screen.getByText("01J8XQ2F");
    expect(current).toHaveAttribute("aria-current", "page");
  });

  it("renders a single item as current with no separators", () => {
    render(<Breadcrumb items={[{ label: "Agents" }]} />);
    expect(screen.getByText("Agents")).toHaveAttribute("aria-current", "page");
  });
});
