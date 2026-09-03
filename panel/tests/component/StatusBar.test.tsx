import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBar } from "@/components/StatusBar";

describe("StatusBar", () => {
  it("renders one segment element per non-zero segment", () => {
    const { container } = render(
      <StatusBar
        segments={[
          { colorVar: "var(--st-ok)", percent: 65, label: "ok" },
          { colorVar: "var(--st-fail)", percent: 20, label: "fail" },
          { colorVar: "var(--st-timeout)", percent: 15, label: "timeout" },
        ]}
      />,
    );
    // 3 segments inside the track.
    const track = container.firstElementChild as HTMLElement;
    expect(track.children).toHaveLength(3);
  });

  it("renders only the empty track when all segments are zero (EC)", () => {
    const { container } = render(
      <StatusBar
        segments={[
          { colorVar: "var(--st-ok)", percent: 0 },
          { colorVar: "var(--st-fail)", percent: 0 },
        ]}
      />,
    );
    const track = container.firstElementChild as HTMLElement;
    expect(track.children).toHaveLength(0);
    expect(track).toBeInTheDocument();
  });

  it("renders the empty track for an empty segment list without crashing", () => {
    const { container } = render(<StatusBar segments={[]} />);
    expect(container.firstElementChild?.children).toHaveLength(0);
  });
});
