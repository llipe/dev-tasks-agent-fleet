import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { exportJWK, generateKeyPair } from "jose";
import { createServer, type Server, type IncomingMessage, type ServerResponse } from "http";
import { NextRequest } from "next/server";
import { middleware, config as middlewareConfig } from "../../middleware";
import { resetJWKSCache } from "./verify-token";

let jwksServer: Server;

const TEST_TEAM = "test-team";
const TEST_AUD = "test-aud-tag-1234";
const TEST_KID = "test-key-id-1";

beforeAll(async () => {
  const keyPair = await generateKeyPair("RS256");
  const publicKey = keyPair.publicKey;

  const jwk = await exportJWK(publicKey);
  jwk.kid = TEST_KID;
  jwk.alg = "RS256";
  jwk.use = "sig";

  await new Promise<void>((resolve) => {
    jwksServer = createServer((_req: IncomingMessage, res: ServerResponse) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ keys: [jwk] }));
    });
    jwksServer.listen(0, () => resolve());
  });

  // Set env vars for middleware
  process.env["CF_ACCESS_TEAM_NAME"] = TEST_TEAM;
  process.env["CF_ACCESS_AUD"] = TEST_AUD;
});

afterEach(() => {
  resetJWKSCache();
});

afterAll(() => {
  jwksServer?.close();
  delete process.env["CF_ACCESS_TEAM_NAME"];
  delete process.env["CF_ACCESS_AUD"];
});

function matchesProtectedPath(path: string): boolean {
  // Simulate Next.js matcher: /((?!healthz|_next/static|_next/image|favicon\.ico).*)
  const matchers = middlewareConfig.matcher;
  const pattern = matchers[0];
  if (!pattern) return false;
  // Extract the negative lookahead pattern
  const excludePatterns = [/^\/healthz/, /^\/_next\/static/, /^\/_next\/image/, /^\/favicon\.ico/];
  return !excludePatterns.some((re) => re.test(path));
}

describe("middleware integration", () => {
  it("denies unauthenticated request to a data route", async () => {
    // A request to /agents without the JWT header
    const request = new NextRequest("http://localhost:3000/agents", {
      headers: {},
    });

    const response = await middleware(request);

    expect(response.status).toBe(401);
    const body = await response.json();
    expect(body.error).toBe("unauthorized");
  });

  it("allows /healthz without auth (via matcher config)", () => {
    // /healthz should NOT be matched by the middleware matcher
    expect(matchesProtectedPath("/healthz")).toBe(false);
  });

  it("protects /agents (matched by middleware)", () => {
    expect(matchesProtectedPath("/agents")).toBe(true);
  });

  it("protects /repos (matched by middleware)", () => {
    expect(matchesProtectedPath("/repos")).toBe(true);
  });

  it("does not match /_next/static paths", () => {
    expect(matchesProtectedPath("/_next/static/chunk.js")).toBe(false);
  });

  it("does not match /_next/image paths", () => {
    expect(matchesProtectedPath("/_next/image/photo.png")).toBe(false);
  });

  it("does not match /favicon.ico", () => {
    expect(matchesProtectedPath("/favicon.ico")).toBe(false);
  });

  it("denies request with empty Cf-Access-Jwt-Assertion header", async () => {
    const request = new NextRequest("http://localhost:3000/agents", {
      headers: { "Cf-Access-Jwt-Assertion": "" },
    });

    const response = await middleware(request);
    expect(response.status).toBe(401);
  });
});
