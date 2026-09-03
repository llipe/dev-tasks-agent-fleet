import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusPill } from "@/components/StatusPill";
import type { RunStatus } from "@/lib/domain/status";

const ALL_STATUSES: { status: RunStatus; label: string }[] = [
  { status: "running", label: "running" },
  { status: "queued", label: "queued" },
  { status: "succeeded", label: "succeeded" },
  { status: "failed", label: "failed" },
  { status: "timed_out", label: "timed out" },
  { status: "failed_to_start", label: "failed to start" },
  { status: "canceled", label: "canceled" },
];

describe("StatusPill", () => {
  it.each(ALL_STATUSES)(
    "renders accessible text for status $status (AC4/AC5 — never color alone)",
    ({ status, label }) => {
      render(<StatusPill status={status} />);
      expect(screen.getByText(label)).toBeInTheDocument();
    },
  );

  it("renders a neutral fallback for an unknown status without crashing (EC)", () => {
    render(<StatusPill status={"some_future_status" as RunStatus} />);
    expect(screen.getByText("some_future_status")).toBeInTheDocument();
  });
});
