import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunStrip } from "@/components/RunStrip";
import type { RunStatus } from "@/lib/domain/status";

function runs(...statuses: RunStatus[]) {
  return statuses.map((status) => ({ status }));
}

describe("RunStrip", () => {
  it("renders exactly max (24) bars when fewer runs are supplied — rest are placeholders (EC)", () => {
    const { container } = render(<RunStrip runs={runs("succeeded", "failed", "succeeded")} />);
    const strip = container.firstElementChild as HTMLElement;
    // 3 filled + 21 empty placeholders = 24.
    expect(strip.children).toHaveLength(24);
  });

  it("clamps to the newest max runs when more than 24 are supplied", () => {
    const many = runs(...(Array.from({ length: 40 }, () => "succeeded") as RunStatus[]));
    const { container } = render(<RunStrip runs={many} />);
    const strip = container.firstElementChild as HTMLElement;
    expect(strip.children).toHaveLength(24);
  });

  it("renders an all-placeholder strip for zero runs without crashing", () => {
    const { container } = render(<RunStrip runs={[]} />);
    expect((container.firstElementChild as HTMLElement).children).toHaveLength(24);
  });

  it("honors a custom max", () => {
    const { container } = render(<RunStrip runs={runs("running")} max={10} />);
    expect((container.firstElementChild as HTMLElement).children).toHaveLength(10);
  });
});
