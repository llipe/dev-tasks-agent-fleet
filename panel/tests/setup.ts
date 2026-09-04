import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, vi } from "vitest";

import "@testing-library/jest-dom/vitest";

// `act()` called directly (outside RTL's render) requires this global flag in
// React 19, or React warns and may not flush effects. The hydration instrument
// (tests/helpers/hydrate.tsx) uses a bare `act`, so set it for the whole
// component project.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ---------------------------------------------------------------------------
// Standing console.error trap (test-plan G3).
//
// A React hydration mismatch is reported as a development `console.error`,
// which by default fails no test — so the defect ships green. This trap fails
// any component test that emits an unexpected `console.error`, which pays off
// for every wave after this one, not just the shell.
//
// A test that *intends* to exercise an error path opts in explicitly with
// `allowConsoleError("reason")`, rather than the trap carrying a broad filter
// that erodes into nothing. The reason is required and recorded.
// ---------------------------------------------------------------------------

let allowedReason: string | null = null;
let captured: unknown[][] = [];

/**
 * Opt a single test out of the console.error trap. Must name why — the reason
 * is not used programmatically, it exists so the exception is auditable.
 */
export function allowConsoleError(reason: string): void {
  if (!reason || !reason.trim()) {
    throw new Error("allowConsoleError requires a non-empty reason");
  }
  allowedReason = reason;
}

beforeEach(() => {
  allowedReason = null;
  captured = [];
  vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
    captured.push(args);
  });
});

afterEach(() => {
  cleanup();
  const spy = console.error as unknown as { mockRestore?: () => void };
  const errors = captured;
  spy.mockRestore?.();
  if (allowedReason === null && errors.length > 0) {
    const rendered = errors
      .map((a) => a.map((x) => (typeof x === "string" ? x : String(x))).join(" "))
      .join("\n");
    throw new Error(
      `Unexpected console.error in this test (test-plan G3 trap). ` +
        `If intentional, call allowConsoleError("reason") in the test.\n${rendered}`,
    );
  }
});

// Re-export so tests can assert on captured errors when they DID opt in.
export function capturedConsoleErrors(): unknown[][] {
  return captured;
}

// Silence the "unused" lint if a project imports expect from here.
void expect;
