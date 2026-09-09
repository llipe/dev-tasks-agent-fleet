import { describe, expect, it } from "vitest";

import {
  checkEnvNames,
  checkProtectedRedirect,
  checkSignupRejected,
  checkSseUnauthorized,
  evaluateAuthGate,
  REQUIRED_AUTH_ENV_NAMES,
} from "@/scripts/panel-auth-check.mjs";

/**
 * Auth-gate parser (Story S-122, SR2 inversion / PRD AC17).
 *
 * This suite REPLACES the S-115 privacy-parser suite (`fly-privacy-check.test.ts`).
 * It is the "gate observed failing" evidence at unit level: a CORRECT-deployment
 * fixture MUST pass, and EACH violation fixture — a protected path served 200, an
 * SSE path served 200, a successful signup, a missing env name, malformed/garbage
 * input — MUST make the parser report a failing verdict (which the wrapper turns
 * into a non-zero exit). Fail-closed is asserted directly: anything not positively
 * confirmed fails.
 *
 * Fixtures mirror the shape the live wrapper (`scripts/verify-panel-auth.sh`)
 * collects: env-var NAMES only, HTTP-probe status codes, and a signup outcome.
 */

// ---- Correct-deployment building blocks ----------------------------------
const ENV_OK = [...REQUIRED_AUTH_ENV_NAMES, "SUPABASE_SERVICE_ROLE_KEY", "AGENT_RUNTIME_ROLE_ARN"];
const PROTECTED_OK = { status: 302, location: "/login?redirect=/" };
const SSE_OK = { status: 401 };
const SIGNUP_OK = { rejected: true, message: "Signups not allowed for this instance" };

/** A fully correct deployment: every check passes. */
const GATE_INPUT_OK = {
  envNames: ENV_OK,
  protectedProbe: PROTECTED_OK,
  sseProbe: SSE_OK,
  signupProbe: SIGNUP_OK,
};

describe("checkEnvNames — auth env var NAMES present (names only, never values)", () => {
  it("passes when both required names are present (order/extra names irrelevant)", () => {
    expect(checkEnvNames(ENV_OK).ok).toBe(true);
  });

  it("is case-insensitive on the reported names", () => {
    expect(checkEnvNames(["next_public_supabase_url", "NEXT_PUBLIC_SUPABASE_ANON_KEY"]).ok).toBe(
      true,
    );
  });

  it("FAILS (missing env) when the anon key name is absent", () => {
    const r = checkEnvNames(["NEXT_PUBLIC_SUPABASE_URL"]);
    expect(r.ok).toBe(false);
    expect(r.missing).toEqual(["NEXT_PUBLIC_SUPABASE_ANON_KEY"]);
    expect(r.reason).toMatch(/missing/i);
  });

  it("FAILS when both names are absent", () => {
    expect(checkEnvNames(["SOME_OTHER_VAR"]).ok).toBe(false);
  });

  it("is fail-closed on non-array / garbage / empty input", () => {
    expect(checkEnvNames(null).ok).toBe(false);
    expect(checkEnvNames(undefined).ok).toBe(false);
    expect(checkEnvNames("NEXT_PUBLIC_SUPABASE_URL").ok).toBe(false);
    expect(checkEnvNames([]).ok).toBe(false);
  });
});

describe("checkProtectedRedirect — unauthenticated protected UI path → 302 /login", () => {
  it("passes on a 302 whose Location is /login", () => {
    expect(checkProtectedRedirect({ status: 302, location: "/login" }).ok).toBe(true);
  });

  it("passes on a 302 to /login carrying a redirect query", () => {
    expect(checkProtectedRedirect(PROTECTED_OK).ok).toBe(true);
  });

  it("FAILS when the protected path returns 200 (gate not enforcing)", () => {
    const r = checkProtectedRedirect({ status: 200 });
    expect(r.ok).toBe(false);
    expect(r.reason).toMatch(/200/);
  });

  it("FAILS (edge) when redirecting to a NON-/login location", () => {
    const r = checkProtectedRedirect({ status: 302, location: "/somewhere-else" });
    expect(r.ok).toBe(false);
    expect(r.reason).toMatch(/not \/login/i);
  });

  it("FAILS on an unexpected status (e.g. 500)", () => {
    expect(checkProtectedRedirect({ status: 500 }).ok).toBe(false);
  });

  it("is fail-closed (edge) on a network error/timeout", () => {
    const r = checkProtectedRedirect({ error: "connect ETIMEDOUT" });
    expect(r.ok).toBe(false);
    expect(r.reason).toMatch(/timedout|failed to complete/i);
  });

  it("is fail-closed on a missing/garbage probe", () => {
    expect(checkProtectedRedirect(null).ok).toBe(false);
    expect(checkProtectedRedirect({}).ok).toBe(false);
    expect(checkProtectedRedirect({ status: "not-a-number" }).ok).toBe(false);
  });
});

describe("checkSseUnauthorized — unauthenticated SSE path → 401", () => {
  it("passes on a 401", () => {
    expect(checkSseUnauthorized({ status: 401 }).ok).toBe(true);
  });

  it("passes on a 401 even when the body is HTML (status is authoritative) — edge", () => {
    expect(checkSseUnauthorized({ status: 401, contentType: "text/html", body: "<html>" }).ok).toBe(
      true,
    );
  });

  it("FAILS when the SSE path returns 200 (reachable anonymously)", () => {
    const r = checkSseUnauthorized({ status: 200 });
    expect(r.ok).toBe(false);
    expect(r.reason).toMatch(/200/);
  });

  it("FAILS on any other status (e.g. 302)", () => {
    expect(checkSseUnauthorized({ status: 302 }).ok).toBe(false);
  });

  it("is fail-closed (edge) on a network timeout and on garbage", () => {
    expect(checkSseUnauthorized({ error: "ETIMEDOUT" }).ok).toBe(false);
    expect(checkSseUnauthorized(null).ok).toBe(false);
    expect(checkSseUnauthorized({}).ok).toBe(false);
  });
});

describe("checkSignupRejected — attempted signUp is rejected (PRD AC17 / R9)", () => {
  it("passes when the signup was rejected (signups disabled)", () => {
    expect(checkSignupRejected(SIGNUP_OK).ok).toBe(true);
  });

  it("FAILS the release when a signup SUCCEEDS (a user was created)", () => {
    const r = checkSignupRejected({ rejected: false, createdUserId: "abc-123" });
    expect(r.ok).toBe(false);
    expect(r.reason).toMatch(/succeeded|enabled|self-register/i);
  });

  it("FAILS when rejected is explicitly false even without a captured id", () => {
    expect(checkSignupRejected({ rejected: false }).ok).toBe(false);
  });

  it("is fail-closed (edge) on an unexpected Supabase error shape it cannot classify", () => {
    const r = checkSignupRejected({ weird: "shape", status: 418 });
    expect(r.ok).toBe(false);
    expect(r.reason).toMatch(/could not be confirmed|fail-closed/i);
  });

  it("is fail-closed on a missing/garbage probe", () => {
    expect(checkSignupRejected(null).ok).toBe(false);
    expect(checkSignupRejected(undefined).ok).toBe(false);
    expect(checkSignupRejected("nope").ok).toBe(false);
  });
});

describe("evaluateAuthGate — the release-gate verdict (both directions)", () => {
  it("PASSES on a fully correct deployment fixture", () => {
    const v = evaluateAuthGate(GATE_INPUT_OK);
    expect(v.pass).toBe(true);
    expect(v.reasons).toEqual([]);
  });

  it("FAILS the release when a protected path returns 200 (gate observed failing)", () => {
    const v = evaluateAuthGate({ ...GATE_INPUT_OK, protectedProbe: { status: 200 } });
    expect(v.pass).toBe(false);
    expect(v.reasons.join(" ")).toMatch(/200/);
  });

  it("FAILS the release when the SSE path returns 200 (gate observed failing)", () => {
    const v = evaluateAuthGate({ ...GATE_INPUT_OK, sseProbe: { status: 200 } });
    expect(v.pass).toBe(false);
    expect(v.reasons.join(" ")).toMatch(/anonymously|200/i);
  });

  it("FAILS the release when a signup SUCCEEDS (AC17, the highest-value check)", () => {
    const v = evaluateAuthGate({
      ...GATE_INPUT_OK,
      signupProbe: { rejected: false, createdUserId: "u-1" },
    });
    expect(v.pass).toBe(false);
    expect(v.reasons.join(" ")).toMatch(/self-register|enabled|succeeded/i);
  });

  it("FAILS the release when a required env name is missing", () => {
    const v = evaluateAuthGate({ ...GATE_INPUT_OK, envNames: ["NEXT_PUBLIC_SUPABASE_URL"] });
    expect(v.pass).toBe(false);
    expect(v.reasons.join(" ")).toMatch(/missing/i);
  });

  it("is fail-closed on entirely malformed/garbage input", () => {
    expect(evaluateAuthGate(null).pass).toBe(false);
    expect(evaluateAuthGate("garbage").pass).toBe(false);
    expect(evaluateAuthGate(42).pass).toBe(false);
  });

  it("is fail-closed on an EMPTY object (no probes collected at all)", () => {
    const v = evaluateAuthGate({});
    expect(v.pass).toBe(false);
    // All four checks should contribute a reason.
    expect(v.reasons.length).toBe(4);
  });

  it("reports EVERY failing reason, not just the first (multiple violations)", () => {
    const v = evaluateAuthGate({
      envNames: [],
      protectedProbe: { status: 200 },
      sseProbe: { status: 200 },
      signupProbe: { rejected: false },
    });
    expect(v.pass).toBe(false);
    expect(v.reasons.length).toBe(4);
  });
});
