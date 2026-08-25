import { createRemoteJWKSet, jwtVerify, type JWTPayload, type JWTVerifyResult } from "jose";

export interface VerifyTokenConfig {
  certsUrl: string;
  issuer: string;
  audience: string;
}

export interface VerifyTokenSuccess {
  ok: true;
  payload: JWTPayload;
  email?: string;
}

export interface VerifyTokenFailure {
  ok: false;
  reason: string;
}

export type VerifyTokenResult = VerifyTokenSuccess | VerifyTokenFailure;

// Module-level JWKS cache (jose handles caching internally via createRemoteJWKSet)
let jwksCache: ReturnType<typeof createRemoteJWKSet> | null = null;
let jwksCertsUrl: string | null = null;

function getJWKS(certsUrl: string): ReturnType<typeof createRemoteJWKSet> {
  if (jwksCache && jwksCertsUrl === certsUrl) {
    return jwksCache;
  }
  jwksCache = createRemoteJWKSet(new URL(certsUrl));
  jwksCertsUrl = certsUrl;
  return jwksCache;
}

/** Reset the JWKS cache (for testing) */
export function resetJWKSCache(): void {
  jwksCache = null;
  jwksCertsUrl = null;
}

/**
 * Verify a Cloudflare Access JWT token.
 *
 * Fail closed: if JWKS is unreachable, verification fails.
 * Only RS256 algorithm is allowed.
 * Checks iss, aud, exp, and iat claims.
 */
export async function verifyToken(
  token: string,
  config: VerifyTokenConfig,
): Promise<VerifyTokenResult> {
  if (!token || token.trim() === "") {
    return { ok: false, reason: "missing or empty token" };
  }

  try {
    const jwks = getJWKS(config.certsUrl);

    const result: JWTVerifyResult = await jwtVerify(token, jwks, {
      algorithms: ["RS256"],
      issuer: config.issuer,
      audience: config.audience,
    });

    const payload = result.payload;

    // Verify iat is present
    if (payload.iat === undefined) {
      return { ok: false, reason: "missing iat claim" };
    }

    return {
      ok: true,
      payload,
      email: typeof payload.email === "string" ? payload.email : undefined,
    };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "unknown verification error";
    return { ok: false, reason: message };
  }
}
