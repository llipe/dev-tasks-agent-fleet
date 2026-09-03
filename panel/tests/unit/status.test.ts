import { describe, expect, it } from "vitest";
import { effectiveStatus, type StatusInput } from "@/lib/domain/status";

// Layer 1 (unit) truth table for SD4 `effectiveStatus`. This is the
// TypeScript half of the SR3 parity contract; the Layer 2.5 test
// (tests/integration/status-parity.test.ts) proves the SQL half agrees over
// the same shapes. Times are epoch ms; `now` is always injected so every case
// is evaluated at a boundary we control (EC-8).

const T0 = Date.UTC(2026, 0, 1, 12, 0, 0); // a fixed reference instant

// A `running` row with a 900s max_runtime + 60s grace = 960s window.
function running(overrides: Partial<StatusInput> = {}): StatusInput {
  return {
    status: "running",
    startedAtMs: T0,
    queuedAtMs: T0 - 60_000,
    maxRuntimeSeconds: 900,
    graceSeconds: 60,
    startTimeoutSeconds: 300,
    ...overrides,
  };
}

// A `queued` row with a 300s start_timeout window.
function queued(overrides: Partial<StatusInput> = {}): StatusInput {
  return {
    status: "queued",
    startedAtMs: null,
    queuedAtMs: T0,
    maxRuntimeSeconds: 900,
    graceSeconds: 60,
    startTimeoutSeconds: 300,
    ...overrides,
  };
}

const RUNNING_WINDOW_MS = (900 + 60) * 1000; // 960_000
const QUEUED_WINDOW_MS = 300 * 1000; // 300_000

describe("effectiveStatus — running clock (timed_out)", () => {
  it("fresh running run stays running", () => {
    expect(effectiveStatus(running(), T0 + 1000)).toBe("running");
  });

  it("running run well past the window derives timed_out", () => {
    expect(effectiveStatus(running(), T0 + RUNNING_WINDOW_MS + 10_000)).toBe("timed_out");
  });

  it("running run at the exact threshold stays running (strict >)", () => {
    // now == started_at + window. SQL uses `now() > …`, so equality is NOT past.
    expect(effectiveStatus(running(), T0 + RUNNING_WINDOW_MS)).toBe("running");
  });

  it("running run one ms before the threshold stays running", () => {
    expect(effectiveStatus(running(), T0 + RUNNING_WINDOW_MS - 1)).toBe("running");
  });

  it("running run one ms past the threshold flips to timed_out", () => {
    expect(effectiveStatus(running(), T0 + RUNNING_WINDOW_MS + 1)).toBe("timed_out");
  });

  it("running run with null started_at never derives timed_out (CT-3)", () => {
    expect(effectiveStatus(running({ startedAtMs: null }), T0 + RUNNING_WINDOW_MS + 10_000)).toBe(
      "running",
    );
  });

  it("running run with null max_runtime_seconds passes through, not reaped (CT-4)", () => {
    // Defensive: the column is `not null` in the live schema, but a null must
    // never coerce to 0 and reap the run.
    expect(effectiveStatus(running({ maxRuntimeSeconds: null }), T0 + 10 * RUNNING_WINDOW_MS)).toBe(
      "running",
    );
  });
});

describe("effectiveStatus — grace_seconds boundaries (EC-16)", () => {
  it("zero grace makes the threshold started_at + max_runtime exactly", () => {
    const r = running({ graceSeconds: 0 });
    const windowMs = 900 * 1000;
    expect(effectiveStatus(r, T0 + windowMs)).toBe("running"); // equality passes through
    expect(effectiveStatus(r, T0 + windowMs + 1)).toBe("timed_out");
  });

  it("negative grace tightens the window", () => {
    const r = running({ graceSeconds: -60 });
    const windowMs = (900 - 60) * 1000;
    expect(effectiveStatus(r, T0 + windowMs)).toBe("running");
    expect(effectiveStatus(r, T0 + windowMs + 1)).toBe("timed_out");
  });
});

describe("effectiveStatus — queued clock (failed_to_start)", () => {
  it("fresh queued run stays queued", () => {
    expect(effectiveStatus(queued(), T0 + 1000)).toBe("queued");
  });

  it("queued run past the start_timeout derives failed_to_start", () => {
    expect(effectiveStatus(queued(), T0 + QUEUED_WINDOW_MS + 5000)).toBe("failed_to_start");
  });

  it("queued run at the exact threshold stays queued (strict >)", () => {
    expect(effectiveStatus(queued(), T0 + QUEUED_WINDOW_MS)).toBe("queued");
  });

  it("queued run one ms past the threshold flips to failed_to_start", () => {
    expect(effectiveStatus(queued(), T0 + QUEUED_WINDOW_MS + 1)).toBe("failed_to_start");
  });
});

describe("effectiveStatus — terminal statuses pass through (EC-4)", () => {
  const terminals = ["succeeded", "failed", "canceled", "timed_out", "failed_to_start"] as const;
  for (const status of terminals) {
    it(`${status} with a far-past clock stays ${status}`, () => {
      const r: StatusInput = {
        status,
        startedAtMs: T0 - 10 * RUNNING_WINDOW_MS,
        queuedAtMs: T0 - 20 * RUNNING_WINDOW_MS,
        maxRuntimeSeconds: 900,
        graceSeconds: 60,
        startTimeoutSeconds: 300,
      };
      expect(effectiveStatus(r, T0)).toBe(status);
    });
  }
});

describe("effectiveStatus — forward compatibility (EC-20)", () => {
  it("an unknown future status passes through unchanged", () => {
    const r: StatusInput = {
      status: "paused_for_review",
      startedAtMs: T0,
      queuedAtMs: T0,
      maxRuntimeSeconds: 900,
      graceSeconds: 60,
      startTimeoutSeconds: 300,
    };
    expect(effectiveStatus(r, T0 + 10 * RUNNING_WINDOW_MS)).toBe("paused_for_review");
  });
});

describe("effectiveStatus — purity (EC-8)", () => {
  it("is stable across repeated calls with the same now and does not mutate input", () => {
    const r = running();
    const snapshot = { ...r };
    const results = new Set<string>();
    for (let i = 0; i < 100; i++) {
      results.add(effectiveStatus(r, T0 + RUNNING_WINDOW_MS + 1) as string);
    }
    expect([...results]).toEqual(["timed_out"]);
    expect(r).toEqual(snapshot); // input untouched
  });
});
