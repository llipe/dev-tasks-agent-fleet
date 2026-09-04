/**
 * A single AWS credential provider for the panel, with two branches (SD9, D12):
 *
 *   On Fly.io → OIDC token from the local Machine socket → AssumeRoleWithWebIdentity
 *   Locally   → the SDK's standard provider chain (SSO profile, ~/.aws/credentials, env vars)
 *
 * The invocation code does not know which branch it is running in — it receives
 * only a provider (`awsCredentials`). `credentialSource()` exposes the active
 * branch for diagnostics.
 *
 * No static AWS keys exist anywhere (D12): on Fly the credentials come from the
 * OIDC exchange, locally from the ambient chain. Nothing here is ever logged —
 * not the token, not the STS response, not the assumed-role credentials.
 *
 * This module MUST stay free of Next.js imports so it is unit-testable in
 * isolation.
 *
 * Requires: @aws-sdk/client-sts, @aws-sdk/credential-providers
 * Env vars: AGENT_RUNTIME_ROLE_ARN (only on Fly), AWS_REGION
 *           AWS_PROFILE (local only, optional)
 */

import * as http from "node:http";
import * as fs from "node:fs";
import type { AwsCredentialIdentity, AwsCredentialIdentityProvider } from "@aws-sdk/types";
import { STSClient, AssumeRoleWithWebIdentityCommand } from "@aws-sdk/client-sts";
import { fromNodeProviderChain } from "@aws-sdk/credential-providers";
import { CredentialsUnavailableError, FlyOidcShapeError } from "./errors";

const FLY_OIDC_SOCKET = "/.fly/api";
const FLY_OIDC_PATH = "/v1/tokens/oidc";
const STS_AUDIENCE = "sts.amazonaws.com";
const REFRESH_MARGIN_MS = 60_000;

/** Running on Fly if the app name is set and the Machine socket exists. */
function isFly(): boolean {
  return Boolean(process.env.FLY_APP_NAME) && fs.existsSync(FLY_OIDC_SOCKET);
}

// --------------------------------------------------------------- Fly OIDC

/**
 * Extracts the OIDC token from the socket's JSON response.
 *
 * Accepts a string `value` or a string `token` and nothing else. Any other
 * shape throws `FlyOidcShapeError` naming the keys received — it does NOT fall
 * back to some other field.
 *
 * This is the F5 fix. The previous chain was
 * `parsed.value ?? parsed.token ?? parsed.aud`, plus a `data.trim()` fallback
 * for unparseable bodies. `aud` is the audience (`sts.amazonaws.com`), not a
 * token: forwarding it to STS as a web-identity token produced a misleading
 * auth error instead of a clear parse failure. Because the real socket shape is
 * unverified until a live Machine probe (SR1/OQ1), the failure mode must name
 * what it actually received.
 *
 * Verify the real shape with:
 *   curl --unix-socket /.fly/api -X POST http://localhost/v1/tokens/oidc \
 *        --data '{"aud":"sts.amazonaws.com"}'
 */
export function extractOidcToken(rawBody: string): string {
  let parsed: unknown;
  try {
    parsed = JSON.parse(rawBody);
  } catch {
    // Unparseable body: no key names to report. Do NOT forward the raw body.
    throw new FlyOidcShapeError([], "response body was not valid JSON");
  }

  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new FlyOidcShapeError([], "response body was not a JSON object");
  }

  const obj = parsed as Record<string, unknown>;
  if (typeof obj.value === "string") return obj.value;
  if (typeof obj.token === "string") return obj.token;

  // No usable token field. Name the keys received (never their values) so the
  // shape mismatch is a one-line diagnosis.
  throw new FlyOidcShapeError(Object.keys(obj));
}

function fetchFlyOidcToken(audience: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ aud: audience });
    const req = http.request(
      {
        socketPath: FLY_OIDC_SOCKET,
        path: FLY_OIDC_PATH,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(body),
        },
      },
      (res) => {
        let data = "";
        res.on("data", (chunk) => (data += chunk));
        res.on("end", () => {
          const ok = res.statusCode !== undefined && res.statusCode >= 200 && res.statusCode < 300;
          if (!ok) {
            reject(
              new CredentialsUnavailableError(
                `Fly OIDC socket returned HTTP ${res.statusCode ?? "unknown"}.`,
              ),
            );
            return;
          }
          try {
            resolve(extractOidcToken(data));
          } catch (err) {
            reject(err);
          }
        });
      },
    );
    // A socket that exists but refuses/errors must fail loudly as a credential
    // failure — never a silent fall-through to the local provider chain (SR1).
    req.on("error", (err) =>
      reject(
        new CredentialsUnavailableError(`Fly OIDC socket is unreachable: ${err.message}`, {
          cause: err,
        }),
      ),
    );
    req.write(body);
    req.end();
  });
}

async function assumeRoleFromFly(): Promise<AwsCredentialIdentity> {
  const roleArn = process.env.AGENT_RUNTIME_ROLE_ARN;
  if (!roleArn) {
    // Fail with a named configuration error rather than an opaque invoke-time
    // auth failure that reads as an IAM trust-policy problem (EC-11).
    throw new CredentialsUnavailableError(
      "AGENT_RUNTIME_ROLE_ARN is not set. The Fly branch cannot assume a role without it.",
    );
  }

  const token = await fetchFlyOidcToken(STS_AUDIENCE);
  const sts = new STSClient({ region: process.env.AWS_REGION ?? "us-east-1" });

  let out;
  try {
    out = await sts.send(
      new AssumeRoleWithWebIdentityCommand({
        RoleArn: roleArn,
        RoleSessionName: `panel-agentes-${process.env.FLY_MACHINE_ID ?? "local"}`,
        WebIdentityToken: token,
        // DurationSeconds must be compatible with the role's MaxSessionDuration
        // — unverified until the live probe in S-115 (OQ1).
        DurationSeconds: 900,
      }),
    );
  } catch (err) {
    // Any STS rejection (AccessDenied, InvalidIdentityToken, network) is a
    // credential failure (500), never an invocation failure (502) — R6.
    throw new CredentialsUnavailableError(
      "AssumeRoleWithWebIdentity failed while obtaining AWS credentials.",
      { cause: err },
    );
  }

  const c = out.Credentials;
  if (!c?.AccessKeyId || !c.SecretAccessKey || !c.SessionToken || !c.Expiration) {
    throw new CredentialsUnavailableError(
      "AssumeRoleWithWebIdentity returned incomplete credentials.",
    );
  }
  return {
    accessKeyId: c.AccessKeyId,
    secretAccessKey: c.SecretAccessKey,
    sessionToken: c.SessionToken,
    expiration: c.Expiration,
  };
}

// --------------------------------------------------------------- provider

let cached: AwsCredentialIdentity | null = null;
let inFlight: Promise<AwsCredentialIdentity> | null = null;

const localChain = fromNodeProviderChain();

/**
 * The single provider. Passed as-is to any SDK client:
 *   new BedrockAgentCoreClient({ region, credentials: awsCredentials })
 *
 * On Fly: caches the assumed-role credentials in memory and refreshes them
 * REFRESH_MARGIN_MS before expiry. Concurrent calls during a refresh share one
 * in-flight STS request (single-flight), so two simultaneous invokes trigger
 * exactly one AssumeRoleWithWebIdentity call.
 *
 * Locally: delegates to the SDK's provider chain, which manages its own cache
 * and refresh (SSO included).
 */
export const awsCredentials: AwsCredentialIdentityProvider = async () => {
  if (!isFly()) {
    // Locally the SDK manages its own cache and refresh (SSO included).
    return localChain();
  }

  const now = Date.now();
  if (cached?.expiration && cached.expiration.getTime() - REFRESH_MARGIN_MS > now) {
    return cached;
  }

  inFlight ??= assumeRoleFromFly()
    .then((creds) => {
      cached = creds;
      return creds;
    })
    .finally(() => {
      inFlight = null;
    });

  return inFlight;
};

/** Diagnostic: which branch is active. Logged on every invoke (AC6). */
export function credentialSource(): "fly-oidc" | "local-chain" {
  return isFly() ? "fly-oidc" : "local-chain";
}

/**
 * Test-only cache reset. Not part of the runtime contract — exported so unit
 * tests can exercise cache hit/miss and single-flight from a known-cold state
 * without module reloading. Never called by application code.
 */
export function __resetCredentialCacheForTests(): void {
  cached = null;
  inFlight = null;
}
