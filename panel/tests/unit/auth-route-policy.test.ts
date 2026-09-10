import { describe, expect, it } from "vitest";
import { classifyRoute } from "@/lib/auth/route-policy";

// Layer 1 unit coverage for the pure route classifier (S-116, spec §7.3). The
// redirect-vs-401 split is security-relevant and must be testable without a
// server. Unknown paths are fail-closed to `ui`.

describe("classifyRoute (spec §7.3)", () => {
  it("classifies /login as public", () => {
    expect(classifyRoute("/login")).toBe("public");
  });

  // S-120: logout is a session-ENDING action and MUST reach its handler even
  // when the session is expiring/invalid — otherwise the gate would 401 the
  // POST before it could clear cookies, and logout would be self-defeating. It
  // is POST-only (a GET is not a route), so classifying it `public` does not
  // widen any read surface.
  it("classifies /api/auth/logout as public (S-120 — session-ending, must be reachable)", () => {
    expect(classifyRoute("/api/auth/logout")).toBe("public");
  });

  it.each(["/", "/agents/x", "/agents/foo-bar", "/runs/01J8XQ2F", "/dev/gallery"])(
    "classifies UI page %s as ui",
    (p) => {
      expect(classifyRoute(p)).toBe("ui");
    },
  );

  it.each(["/api", "/api/", "/api/agents/x/invoke", "/api/runs/abc/events/stream"])(
    "classifies API path %s as api",
    (p) => {
      expect(classifyRoute(p)).toBe("api");
    },
  );

  it("still gates other /api/auth/* paths as api (only the exact logout path is public)", () => {
    expect(classifyRoute("/api/auth")).toBe("api");
    expect(classifyRoute("/api/auth/logout/extra")).toBe("api");
    expect(classifyRoute("/api/auth/whoami")).toBe("api");
  });

  it("fails closed: an unknown path defaults to ui", () => {
    expect(classifyRoute("/some/future/route")).toBe("ui");
  });

  it("fails closed: empty or non-string input defaults to ui", () => {
    expect(classifyRoute("")).toBe("ui");
    // @ts-expect-error — exercising the defensive non-string branch
    expect(classifyRoute(undefined)).toBe("ui");
  });

  it("does not treat a path merely containing 'login' as public", () => {
    expect(classifyRoute("/agents/login-service")).toBe("ui");
    expect(classifyRoute("/login/extra")).toBe("ui");
  });

  it("does not treat a path merely starting with 'api' (no slash) as api", () => {
    expect(classifyRoute("/apiary")).toBe("ui");
  });
});
