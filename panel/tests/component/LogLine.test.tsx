import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LogLine } from "@/components/LogLine";

describe("LogLine", () => {
  it("renders the four columns", () => {
    render(<LogLine timestamp="14:02:13" level="info" step="npm_audit" message="starting audit" />);
    expect(screen.getByText("14:02:13")).toBeInTheDocument();
    expect(screen.getByText("info")).toBeInTheDocument();
    expect(screen.getByText("npm_audit")).toBeInTheDocument();
    expect(screen.getByText("starting audit")).toBeInTheDocument();
  });

  it.each(["debug", "info", "warn", "error"])("renders the %s level", (level) => {
    render(<LogLine timestamp="00:00:01" level={level} message={`${level} line`} />);
    expect(screen.getByText(`${level} line`)).toBeInTheDocument();
  });

  it("wraps rather than truncates an 8 KB message (§7.5)", () => {
    const big = "x".repeat(8 * 1024);
    render(<LogLine timestamp="00:00:01" level="error" message={big} />);
    const el = screen.getByText(big);
    // Full content is present (not truncated) and the CSS wraps it.
    expect(el.textContent).toHaveLength(8 * 1024);
    expect(el.className).toMatch(/message/);
  });

  it("renders without a step", () => {
    render(<LogLine timestamp="00:00:01" level="info" message="no step" />);
    expect(screen.getByText("no step")).toBeInTheDocument();
  });
});
