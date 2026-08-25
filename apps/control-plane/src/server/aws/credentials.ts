/**
 * AWS credentials provider — isolated in this single file.
 *
 * Strategy: use the SDK's default credential provider chain (fromNodeProviderChain).
 * On Fly.io, init detects AWS_ROLE_ARN and sets AWS_WEB_IDENTITY_TOKEN_FILE +
 * AWS_ROLE_SESSION_NAME, which the chain picks up for AssumeRoleWithWebIdentity.
 * Locally, the chain falls through to env vars or shared credentials files.
 *
 * All AWS SDK clients in this app use this provider.
 */

import { fromNodeProviderChain } from "@aws-sdk/credential-providers";
import { readFileSync } from "node:fs";
import type { AwsCredentialIdentityProvider } from "@smithy/types";

/**
 * Log which credential path is active, once at startup.
 *
 * `AssumeRoleWithWebIdentity` failures are not recorded in CloudTrail (there is no
 * authenticated identity to attribute them to), and `fly ssh console` is unavailable on
 * some networks, so without this the only symptom of a bad web-identity token is an opaque
 * `InvalidIdentityTokenException` at first AWS call.
 *
 * Logs the token's `iss`, `aud`, `sub`, `exp` and `iat` claims only. The token itself is a
 * bearer credential and is never logged.
 */
function logCredentialDiagnostics(): void {
  const roleArn = process.env["AWS_ROLE_ARN"];
  const tokenFile = process.env["AWS_WEB_IDENTITY_TOKEN_FILE"];
  const sessionName = process.env["AWS_ROLE_SESSION_NAME"];

  if (!roleArn && !tokenFile) {
    console.warn("[credentials] No web-identity config; relying on env/profile credentials");
    return;
  }

  const base = {
    roleArn,
    tokenFile,
    sessionName,
    hasTokenFile: Boolean(tokenFile),
  };

  if (!tokenFile) {
    console.error(
      "[credentials] AWS_ROLE_ARN is set but AWS_WEB_IDENTITY_TOKEN_FILE is not — " +
        "Fly init did not complete the OIDC token dance",
      base,
    );
    return;
  }

  try {
    const raw = readFileSync(tokenFile, "utf-8").trim();
    const parts = raw.split(".");
    if (parts.length !== 3 || !parts[1]) {
      console.error("[credentials] Web-identity token is not a well-formed JWT", {
        ...base,
        tokenLength: raw.length,
        segments: parts.length,
      });
      return;
    }
    const claims = JSON.parse(Buffer.from(parts[1], "base64url").toString("utf-8")) as Record<
      string,
      unknown
    >;
    const exp = typeof claims["exp"] === "number" ? claims["exp"] : undefined;
    console.info("[credentials] Web-identity token claims", {
      ...base,
      tokenLength: raw.length,
      iss: claims["iss"],
      aud: claims["aud"],
      sub: claims["sub"],
      iat: claims["iat"],
      exp,
      expiresInSeconds: exp === undefined ? undefined : exp - Math.floor(Date.now() / 1000),
    });
  } catch (error: unknown) {
    console.error("[credentials] Could not read or decode the web-identity token", {
      ...base,
      error: error instanceof Error ? error.message : String(error),
    });
  }
}

logCredentialDiagnostics();

/** Singleton credentials provider for all AWS SDK clients */
export const credentialsProvider: AwsCredentialIdentityProvider = fromNodeProviderChain();

/** AWS region — defaults to us-east-1 if not set */
export const awsRegion = process.env["AWS_REGION"] ?? "us-east-1";
