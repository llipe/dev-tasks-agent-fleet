import { describe, expect, it } from "vitest";
import {
  classifySignInError,
  INVALID_CREDENTIALS_MESSAGE,
  userMessageFor,
} from "@/lib/auth/errors";

// Layer 1 unit coverage for the auth error taxonomy (S-116, spec §8.2, AC5).
// The critical invariant: unknown-email and wrong-password are indistinguishable
// and no raw Supabase text leaks into a user-facing message.

describe("classifySignInError — anti-enumeration (AC5)", () => {
  it("maps wrong-password (400) to AUTH_INVALID_CREDENTIALS", () => {
    const code = classifySignInError({ status: 400, message: "Invalid login credentials" });
    expect(code).toBe("AUTH_INVALID_CREDENTIALS");
  });

  it("maps unknown-email (404 user not found) to the SAME code", () => {
    const code = classifySignInError({ status: 404, message: "User not found" });
    expect(code).toBe("AUTH_INVALID_CREDENTIALS");
  });

  it("wrong-password and unknown-email produce an identical user message", () => {
    const wrongPw = userMessageFor(
      classifySignInError({ status: 400, message: "Invalid login credentials" }),
    );
    const unknown = userMessageFor(classifySignInError({ status: 404, message: "User not found" }));
    expect(wrongPw).toBe(unknown);
    expect(wrongPw).toBe(INVALID_CREDENTIALS_MESSAGE);
  });

  it("maps 401 and 403 to invalid credentials too", () => {
    expect(classifySignInError({ status: 401 })).toBe("AUTH_INVALID_CREDENTIALS");
    expect(classifySignInError({ status: 403 })).toBe("AUTH_INVALID_CREDENTIALS");
  });

  it("maps 5xx to service-unavailable", () => {
    expect(classifySignInError({ status: 500 })).toBe("AUTH_SERVICE_UNAVAILABLE");
    expect(classifySignInError({ status: 503 })).toBe("AUTH_SERVICE_UNAVAILABLE");
  });

  it("maps 429 (rate limit) to service-unavailable", () => {
    expect(classifySignInError({ status: 429 })).toBe("AUTH_SERVICE_UNAVAILABLE");
  });

  it("maps a network error (no status) to service-unavailable", () => {
    expect(classifySignInError({ message: "fetch failed" })).toBe("AUTH_SERVICE_UNAVAILABLE");
  });

  it("treats a null error as invalid credentials rather than leaking state", () => {
    expect(classifySignInError(null)).toBe("AUTH_INVALID_CREDENTIALS");
  });
});

describe("userMessageFor — no raw provider text leaks", () => {
  it("returns generic, fixed strings that never include Supabase phrasing", () => {
    const raw = "Invalid login credentials";
    for (const code of [
      "AUTH_INVALID_CREDENTIALS",
      "AUTH_MISSING_FIELDS",
      "AUTH_SERVICE_UNAVAILABLE",
      "AUTH_CONFIG_ERROR",
      "UNAUTHORIZED",
    ] as const) {
      expect(userMessageFor(code)).not.toContain(raw);
      expect(userMessageFor(code).length).toBeGreaterThan(0);
    }
  });

  it("the invalid-credentials message does not reveal which field was wrong", () => {
    expect(INVALID_CREDENTIALS_MESSAGE).toBe("Invalid email or password.");
    expect(INVALID_CREDENTIALS_MESSAGE.toLowerCase()).not.toContain("not found");
    expect(INVALID_CREDENTIALS_MESSAGE.toLowerCase()).not.toContain("email does not");
  });
});
