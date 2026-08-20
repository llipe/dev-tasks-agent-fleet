/**
 * AWS credentials provider — isolated in this single file.
 *
 * Strategy:
 *   1. If FLY_OIDC_TOKEN_PATH and FLY_AWS_ROLE_ARN are set, use Fly OIDC
 *      via `fromWebToken` (AssumeRoleWithWebIdentity).
 *   2. Otherwise, fall back to `fromEnv()` for local development.
 *
 * All AWS SDK clients in this app use this provider.
 */

import { fromEnv, fromWebToken } from "@aws-sdk/credential-providers";
import { readFileSync } from "node:fs";
import type { AwsCredentialIdentityProvider } from "@smithy/types";

function createCredentialsProvider(): AwsCredentialIdentityProvider {
  const tokenPath = process.env["FLY_OIDC_TOKEN_PATH"];
  const roleArn = process.env["FLY_AWS_ROLE_ARN"];

  if (tokenPath && roleArn) {
    return fromWebToken({
      roleArn,
      webIdentityToken: readFileSync(tokenPath, "utf-8"),
      roleSessionName: "control-plane",
    });
  }

  // Local dev fallback
  return fromEnv();
}

/** Singleton credentials provider for all AWS SDK clients */
export const credentialsProvider: AwsCredentialIdentityProvider = createCredentialsProvider();

/** AWS region — defaults to us-east-1 if not set */
export const awsRegion = process.env["AWS_REGION"] ?? "us-east-1";
