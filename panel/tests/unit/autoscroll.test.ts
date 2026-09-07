import { describe, expect, it } from "vitest";

import { AUTOSCROLL_THRESHOLD_PX, shouldAutoScroll, distanceFromBottom } from "@/lib/sse/autoscroll";

/**
 * Auto-scroll threshold predicate (Story S-110, AC6 / DESIGN §6.6). Pure so the
 * exact 24px boundary is asserted as a single truth (EC-15). DESIGN §6.6 says
 * "within 24px of bottom" -> 24 is inclusive (follows), 25 pauses.
 */

describe("distanceFromBottom", () => {
  it("computes scrollHeight - scrollTop - clientHeight", () => {
    expect(distanceFromBottom({ scrollHeight: 1000, scrollTop: 800, clientHeight: 200 })).toBe(0);
    expect(distanceFromBottom({ scrollHeight: 1000, scrollTop: 700, clientHeight: 200 })).toBe(100);
  });
});

describe("shouldAutoScroll", () => {
  it("threshold constant is 24px (DESIGN §6.6)", () => {
    expect(AUTOSCROLL_THRESHOLD_PX).toBe(24);
  });

  it("follows when pinned to the bottom (0px)", () => {
    expect(shouldAutoScroll({ scrollHeight: 1000, scrollTop: 800, clientHeight: 200 })).toBe(true);
  });

  it("follows at 23px (within threshold)", () => {
    expect(shouldAutoScroll({ scrollHeight: 1023, scrollTop: 800, clientHeight: 200 })).toBe(true);
  });

  it("follows at exactly 24px (inclusive boundary, EC-15)", () => {
    expect(shouldAutoScroll({ scrollHeight: 1024, scrollTop: 800, clientHeight: 200 })).toBe(true);
  });

  it("pauses at 25px (past threshold, EC-15)", () => {
    expect(shouldAutoScroll({ scrollHeight: 1025, scrollTop: 800, clientHeight: 200 })).toBe(false);
  });

  it("pauses when scrolled far up", () => {
    expect(shouldAutoScroll({ scrollHeight: 5000, scrollTop: 0, clientHeight: 200 })).toBe(false);
  });
});
