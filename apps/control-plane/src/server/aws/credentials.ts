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
import type { AwsCredentialIdentityProvider } from "@smithy/types";

/** Singleton credentials provider for all AWS SDK clients */
export const credentialsProvider: AwsCredentialIdentityProvider = fromNodeProviderChain();

/** AWS region — defaults to us-east-1 if not set */
export const awsRegion = process.env["AWS_REGION"] ?? "us-east-1";
