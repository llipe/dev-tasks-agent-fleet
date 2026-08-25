/**
 * credentials.ts — AWS credential provider tests.
 *
 * Asserts the module uses the SDK's default provider chain (fromNodeProviderChain)
 * rather than custom logic with invented env vars.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";

describe("credentials module", () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    // Clear any credential-related vars to get a clean import
    delete process.env["FLY_OIDC_TOKEN_PATH"];
    delete process.env["FLY_AWS_ROLE_ARN"];
    delete process.env["AWS_ACCESS_KEY_ID"];
    delete process.env["AWS_SECRET_ACCESS_KEY"];
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it("does not reference FLY_OIDC_TOKEN_PATH or FLY_AWS_ROLE_ARN", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve, dirname } = await import("node:path");
    const { fileURLToPath } = await import("node:url");
    const dir = dirname(fileURLToPath(import.meta.url));
    const source = readFileSync(resolve(dir, "credentials.ts"), "utf-8");
    expect(source).not.toContain("FLY_OIDC_TOKEN_PATH");
    expect(source).not.toContain("FLY_AWS_ROLE_ARN");
  });

  it("does not use readFileSync for token reading", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve, dirname } = await import("node:path");
    const { fileURLToPath } = await import("node:url");
    const dir = dirname(fileURLToPath(import.meta.url));
    const source = readFileSync(resolve(dir, "credentials.ts"), "utf-8");
    expect(source).not.toContain("readFileSync");
  });

  it("uses fromNodeProviderChain (the SDK default chain)", async () => {
    const { readFileSync } = await import("node:fs");
    const { resolve, dirname } = await import("node:path");
    const { fileURLToPath } = await import("node:url");
    const dir = dirname(fileURLToPath(import.meta.url));
    const source = readFileSync(resolve(dir, "credentials.ts"), "utf-8");
    expect(source).toContain("fromNodeProviderChain");
  });

  it("exports credentialsProvider and awsRegion", async () => {
    const mod = await import("./credentials.js");
    expect(mod.credentialsProvider).toBeDefined();
    expect(typeof mod.credentialsProvider).toBe("function");
    expect(mod.awsRegion).toBe("us-east-1");
  });
});
