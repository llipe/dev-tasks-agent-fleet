/**
 * Thin wrapper over Bedrock AgentCore `InvokeAgentRuntime` (spec §9.1).
 *
 * Fire-and-forget from the route handler (D7): the panel invokes the runtime
 * and does not wait for the agent to finish. The target is
 * `agents.runtime_arn` + `runtime_qualifier` snapshotted on the run. There is
 * no retry — on failure the caller (S-112) marks the run `failed_to_start` and
 * stops; the reaper covers accepted-but-never-started.
 *
 * This module stays free of Next.js imports so it is unit-testable in
 * isolation. It never logs the payload, the credentials, or the STS response —
 * only `credentialSource()` and, on failure, the error code (AC6, R6).
 *
 * The route-level guarantee that `credentialSource()` is logged on *every*
 * invoke, and the CREDENTIALS_UNAVAILABLE-vs-INVOCATION_FAILED route mapping,
 * are exercised at the route boundary in S-112 (#125); here they are asserted
 * at this wrapper boundary only (test-plan G5).
 */

import {
  BedrockAgentCoreClient,
  InvokeAgentRuntimeCommand,
} from "@aws-sdk/client-bedrock-agentcore";
import { awsCredentials, credentialSource } from "./credentials";
import { CredentialsUnavailableError, INVOCATION_FAILED, InvocationFailedError } from "./errors";

export interface InvokeTarget {
  /** `agents.runtime_arn` — the InvokeAgentRuntime target. */
  runtimeArn: string;
  /** `agents.runtime_qualifier` — optional endpoint qualifier. */
  runtimeQualifier?: string | null;
}

export interface InvokeOptions {
  /** The JSON payload delivered to the agent (the caller decides `prompt` wrapping). */
  payload: unknown;
  /** Optional injected logger, defaulting to console — keeps the module testable. */
  logger?: Pick<Console, "info" | "error">;
  /** Optional injected client factory, for unit tests. */
  clientFactory?: (region: string) => Pick<BedrockAgentCoreClient, "send">;
}

function defaultClientFactory(region: string): BedrockAgentCoreClient {
  return new BedrockAgentCoreClient({ region, credentials: awsCredentials });
}

/**
 * Invokes the agent runtime. Resolves when AgentCore accepts the call; rejects
 * with `InvocationFailedError` (502) when the SDK call throws, or with
 * `CredentialsUnavailableError` (500) when the credential provider fails first.
 * The two are kept distinct because their runbooks differ (R6).
 *
 * `credentialSource()` is logged on every invoke (AC6) so an operator can tell
 * whether a failure came from the Fly OIDC branch or the local chain.
 */
export async function invokeAgentRuntime(
  target: InvokeTarget,
  options: InvokeOptions,
): Promise<void> {
  const logger = options.logger ?? console;
  const region = process.env.AWS_REGION ?? "us-east-1";

  // AC6: log the active credential branch on every invoke. Never log the
  // payload or any credential material.
  logger.info(
    `[invoke] runtime=${target.runtimeArn} qualifier=${target.runtimeQualifier ?? "(default)"} credentialSource=${credentialSource()}`,
  );

  const client = (options.clientFactory ?? defaultClientFactory)(region);

  const command = new InvokeAgentRuntimeCommand({
    agentRuntimeArn: target.runtimeArn,
    ...(target.runtimeQualifier ? { qualifier: target.runtimeQualifier } : {}),
    payload: new TextEncoder().encode(JSON.stringify(options.payload)),
  });

  try {
    await client.send(command as never);
  } catch (err) {
    // A credential failure surfaced from the provider stays a 500; anything
    // else from the invoke call is a 502.
    if (err instanceof CredentialsUnavailableError) {
      logger.error(`[invoke] credentials unavailable code=${err.code}`);
      throw err;
    }
    logger.error(`[invoke] InvokeAgentRuntime failed code=${INVOCATION_FAILED}`);
    throw new InvocationFailedError("InvokeAgentRuntime failed.", { cause: err });
  }
}
