import { describe, expect, it } from "vitest";
import {
  CREDENTIALS_UNAVAILABLE,
  CredentialsUnavailableError,
  FlyOidcShapeError,
  INVOCATION_FAILED,
  InvocationFailedError,
} from "@/lib/aws/errors";

// Layer 1 coverage for the AWS error taxonomy (S-111 / issue #124, AC8, §13).
// The two failures MUST stay distinct — the runbooks differ (R6). This suite
// pins the code/status split so a future refactor cannot silently collapse
// them. The route-level mapping test lands in S-112 (#125).

describe("AWS error taxonomy — 500 vs 502 stay distinct (AC8)", () => {
  it("CredentialsUnavailableError is CREDENTIALS_UNAVAILABLE / 500", () => {
    const e = new CredentialsUnavailableError("no creds");
    expect(e.code).toBe(CREDENTIALS_UNAVAILABLE);
    expect(e.code).toBe("CREDENTIALS_UNAVAILABLE");
    expect(e.status).toBe(500);
  });

  it("InvocationFailedError is INVOCATION_FAILED / 502", () => {
    const e = new InvocationFailedError("invoke threw");
    expect(e.code).toBe(INVOCATION_FAILED);
    expect(e.code).toBe("INVOCATION_FAILED");
    expect(e.status).toBe(502);
  });

  it("the two codes and statuses are not equal", () => {
    expect(CREDENTIALS_UNAVAILABLE).not.toBe(INVOCATION_FAILED);
    expect(new CredentialsUnavailableError("a").status).not.toBe(
      new InvocationFailedError("b").status,
    );
  });

  it("FlyOidcShapeError is a credential failure (500) and names received keys, never values", () => {
    const e = new FlyOidcShapeError(["aud", "expires_at"]);
    expect(e.code).toBe(CREDENTIALS_UNAVAILABLE);
    expect(e.status).toBe(500);
    expect(e.receivedKeys).toEqual(["aud", "expires_at"]);
    expect(e.message).toContain("aud");
    expect(e.message).toContain("expires_at");
  });

  it("FlyOidcShapeError reports (none) for an empty key set", () => {
    expect(new FlyOidcShapeError([]).message).toContain("(none)");
  });

  it("retains the cause for the server log without serializing it", () => {
    const cause = new Error("underlying STS AccessDenied");
    const e = new CredentialsUnavailableError("wrap", { cause });
    expect((e as Error & { cause?: unknown }).cause).toBe(cause);
  });
});
