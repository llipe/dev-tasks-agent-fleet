import { describe, it, expect, beforeAll, afterEach } from "vitest";
import { SignJWT, exportJWK, generateKeyPair } from "jose";
import type { CryptoKey as JoseCryptoKey } from "jose";
import { createServer, type Server, type IncomingMessage, type ServerResponse } from "http";
import { verifyToken, resetJWKSCache, type VerifyTokenConfig } from "./verify-token";

// Test RSA key pair - generated once for the suite
let privateKey: JoseCryptoKey;
let jwksServer: Server;
let jwksPort: number;
let config: VerifyTokenConfig;

const TEST_TEAM = "test-team";
const TEST_AUD = "test-aud-tag-1234";
const TEST_ISS = `https://${TEST_TEAM}.cloudflareaccess.com`;
const TEST_KID = "test-key-id-1";

async function startJWKSServer(keys: object[]): Promise<{ server: Server; port: number }> {
  return new Promise((resolve) => {
    const server = createServer((_req: IncomingMessage, res: ServerResponse) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ keys }));
    });
    server.listen(0, () => {
      const addr = server.address();
      const port = typeof addr === "object" && addr ? addr.port : 0;
      resolve({ server, port });
    });
  });
}

async function signToken(
  overrides: Partial<{
    iss: string;
    aud: string;
    exp: number;
    iat: number;
    email: string;
    sub: string;
  }> = {},
  opts: { key?: JoseCryptoKey; kid?: string; alg?: string } = {},
): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  const payload = {
    sub: overrides.sub ?? "user-id-123",
    email: overrides.email ?? "user@example.com",
    iat: overrides.iat ?? now,
    ...overrides,
  };

  let builder = new SignJWT(payload)
    .setProtectedHeader({
      alg: opts.alg ?? "RS256",
      kid: opts.kid ?? TEST_KID,
    })
    .setIssuedAt(payload.iat)
    .setIssuer(overrides.iss ?? TEST_ISS)
    .setAudience(overrides.aud ?? TEST_AUD);

  if (overrides.exp !== undefined) {
    builder = builder.setExpirationTime(overrides.exp);
  } else {
    builder = builder.setExpirationTime("1h");
  }

  return builder.sign(opts.key ?? privateKey);
}

beforeAll(async () => {
  const keyPair = await generateKeyPair("RS256");
  privateKey = keyPair.privateKey;

  const jwk = await exportJWK(keyPair.publicKey);
  jwk.kid = TEST_KID;
  jwk.alg = "RS256";
  jwk.use = "sig";

  const { server, port } = await startJWKSServer([jwk]);
  jwksServer = server;
  jwksPort = port;

  config = {
    certsUrl: `http://127.0.0.1:${jwksPort}`,
    issuer: TEST_ISS,
    audience: TEST_AUD,
  };
});

afterEach(() => {
  resetJWKSCache();
});

// Cleanup server after all tests
import { afterAll } from "vitest";
afterAll(() => {
  jwksServer?.close();
});

describe("verifyToken", () => {
  // 14.7: valid token → allowed
  it("allows a valid token", async () => {
    const token = await signToken();
    const result = await verifyToken(token, config);

    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.payload.iss).toBe(TEST_ISS);
      expect(result.payload.aud).toBe(TEST_AUD);
      expect(result.email).toBe("user@example.com");
    }
  });

  // 14.8: expired token → denied
  it("denies an expired token", async () => {
    const pastExp = Math.floor(Date.now() / 1000) - 3600; // 1 hour ago
    const token = await signToken({
      exp: pastExp,
      iat: pastExp - 3600,
    });
    const result = await verifyToken(token, config);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toMatch(/exp/i);
    }
  });

  // 14.9: wrong aud → denied
  it("denies a token with wrong audience", async () => {
    const token = await signToken({ aud: "wrong-audience" });
    const result = await verifyToken(token, config);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toMatch(/aud/i);
    }
  });

  // 14.10: wrong iss → denied
  it("denies a token with wrong issuer", async () => {
    const token = await signToken({ iss: "https://evil.cloudflareaccess.com" });
    const result = await verifyToken(token, config);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toMatch(/iss/i);
    }
  });

  // 14.11: missing header → denied
  it("denies when token is empty string", async () => {
    const result = await verifyToken("", config);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toBe("missing or empty token");
    }
  });

  it("denies when token is whitespace only", async () => {
    const result = await verifyToken("   ", config);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toBe("missing or empty token");
    }
  });

  // 14.12: unknown kid → denied
  it("denies a token with unknown kid", async () => {
    const token = await signToken({}, { kid: "unknown-key-id" });
    const result = await verifyToken(token, config);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toBeDefined();
    }
  });

  // 14.13: alg: none → denied
  it("denies a token with alg: none", async () => {
    // Craft a manual token with alg: none (jose won't sign with none, so construct manually)
    const header = Buffer.from(JSON.stringify({ alg: "none", typ: "JWT" })).toString("base64url");
    const now = Math.floor(Date.now() / 1000);
    const payload = Buffer.from(
      JSON.stringify({
        sub: "user",
        iss: TEST_ISS,
        aud: TEST_AUD,
        iat: now,
        exp: now + 3600,
      }),
    ).toString("base64url");
    const token = `${header}.${payload}.`;

    const result = await verifyToken(token, config);

    expect(result.ok).toBe(false);
  });

  // 14.14: JWKS unreachable → denied (fail closed)
  it("denies when JWKS endpoint is unreachable (fail closed)", async () => {
    const token = await signToken();
    const unreachableConfig: VerifyTokenConfig = {
      certsUrl: "http://127.0.0.1:1", // Port 1 should be unreachable
      issuer: TEST_ISS,
      audience: TEST_AUD,
    };

    const result = await verifyToken(token, unreachableConfig);

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toBeDefined();
    }
  });

  // 14.15: malformed token → denied
  it("denies a malformed token (random string)", async () => {
    const result = await verifyToken("not.a.valid.jwt", config);

    expect(result.ok).toBe(false);
  });

  it("denies a malformed token (base64 garbage)", async () => {
    const result = await verifyToken("aGVsbG8.d29ybGQ.Zm9v", config);

    expect(result.ok).toBe(false);
  });

  it("denies a token signed with a different key", async () => {
    const otherKeyPair = await generateKeyPair("RS256");
    const token = await signToken({}, { key: otherKeyPair.privateKey });
    const result = await verifyToken(token, config);

    expect(result.ok).toBe(false);
  });
});
