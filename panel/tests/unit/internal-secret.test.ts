import { describe, expect, it } from "vitest";
import {
  authorizeInternalRequest,
  checkSchedulerSecret,
  constantTimeEqual,
  SCHEDULER_SECRET_HEADER,
} from "@/lib/auth/internal-secret";

// Layer 1 — S-153 (#265): the fail-closed, constant-time shared-secret check
// for /api/internal/** (SD-A1 / AC3). Every negative case denies; the function
// never throws and never surfaces secret material.

describe("constantTimeEqual", () => {
  it("true only for identical strings", () => {
    expect(constantTimeEqual("abc123", "abc123")).toBe(true);
    expect(constantTimeEqual("abc123", "abc124")).toBe(false);
  });
  it("false (no throw) on length mismatch", () => {
    expect(constantTimeEqual("short", "longer-value")).toBe(false);
    expect(constantTimeEqual("", "x")).toBe(false);
  });
});

describe("checkSchedulerSecret — fail-closed", () => {
  const SECRET = "the-configured-secret";

  it("ok only when the presented secret matches the configured one", () => {
    expect(checkSchedulerSecret(SECRET, SECRET)).toEqual({ ok: true, reason: null });
  });

  it("denies when no secret is configured (misconfig is a deny, not a bypass)", () => {
    expect(checkSchedulerSecret(SECRET, undefined).ok).toBe(false);
    expect(checkSchedulerSecret(SECRET, "").ok).toBe(false);
    expect(checkSchedulerSecret(SECRET, undefined).reason).toBe("secret_not_configured");
  });

  it("denies when the header is missing/empty", () => {
    expect(checkSchedulerSecret(null, SECRET)).toEqual({ ok: false, reason: "header_missing" });
    expect(checkSchedulerSecret(undefined, SECRET).ok).toBe(false);
    expect(checkSchedulerSecret("", SECRET).ok).toBe(false);
  });

  it("denies on a wrong secret (and on a length-mismatched one, no throw)", () => {
    expect(checkSchedulerSecret("wrong", SECRET)).toEqual({ ok: false, reason: "secret_mismatch" });
    expect(checkSchedulerSecret("x", SECRET).ok).toBe(false);
  });

  it("never surfaces secret material in the reason", () => {
    for (const r of [
      checkSchedulerSecret("wrong", SECRET),
      checkSchedulerSecret(null, SECRET),
      checkSchedulerSecret(SECRET, undefined),
    ]) {
      expect(r.reason ?? "").not.toContain(SECRET);
    }
  });
});

describe("authorizeInternalRequest", () => {
  function req(headerValue?: string): Request {
    const headers = new Headers();
    if (headerValue !== undefined) headers.set(SCHEDULER_SECRET_HEADER, headerValue);
    return new Request("http://x/api/internal/schedules/abc/fire", { method: "POST", headers });
  }

  it("authorizes a correct-secret request against the env", () => {
    const r = authorizeInternalRequest(req("env-secret"), {
      SCHEDULER_TRIGGER_SECRET: "env-secret",
    } as unknown as NodeJS.ProcessEnv);
    expect(r.ok).toBe(true);
  });

  it("denies a wrong-secret request", () => {
    const r = authorizeInternalRequest(req("nope"), {
      SCHEDULER_TRIGGER_SECRET: "env-secret",
    } as unknown as NodeJS.ProcessEnv);
    expect(r.ok).toBe(false);
  });

  it("denies a request with no header", () => {
    const r = authorizeInternalRequest(req(), {
      SCHEDULER_TRIGGER_SECRET: "env-secret",
    } as unknown as NodeJS.ProcessEnv);
    expect(r.ok).toBe(false);
  });
});
