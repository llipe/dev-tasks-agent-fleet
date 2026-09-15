import { describe, expect, it } from "vitest";

import { statusMeta } from "@/components/status-meta";
import type { RunStatus } from "@/lib/domain/status";

/**
 * S-142: `queued` must spin (0.9s), distinct from `running`'s pulse (1.6s),
 * per /DESIGN.md §6.1/§8.1. `pulse` and `spin` are mutually exclusive across
 * every known status, and the unknown-status fallback is neutral (both false).
 */
describe("statusMeta", () => {
  it("marks queued as spin:true, pulse:false", () => {
    expect(statusMeta("queued")).toMatchObject({ pulse: false, spin: true });
  });

  it("marks running as pulse:true, spin:false (unchanged)", () => {
    expect(statusMeta("running")).toMatchObject({ pulse: true, spin: false });
  });

  it.each<RunStatus>(["succeeded", "failed", "timed_out", "failed_to_start", "canceled"])(
    "marks %s as spin:false",
    (status) => {
      expect(statusMeta(status).spin).toBe(false);
    },
  );

  it("marks the unknown-status fallback as spin:false", () => {
    expect(statusMeta("some_future_status" as RunStatus).spin).toBe(false);
  });

  it("never sets pulse and spin true simultaneously for any known status", () => {
    const statuses: RunStatus[] = [
      "running",
      "queued",
      "succeeded",
      "failed",
      "timed_out",
      "failed_to_start",
      "canceled",
    ];
    for (const status of statuses) {
      const meta = statusMeta(status);
      expect(meta.pulse && meta.spin).toBe(false);
    }
  });
});
