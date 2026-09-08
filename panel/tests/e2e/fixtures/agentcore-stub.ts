/**
 * AgentCore HTTP-boundary stub (S-114, Context Note: "AgentCore stubbed at the
 * network boundary").
 *
 * The invoke path (`lib/aws/invoke.ts` → `@aws-sdk/client-bedrock-agentcore`)
 * must exercise the REAL credential branch selection (locally:
 * `fromNodeProviderChain` — SSO/env) and the REAL SDK request signing, then be
 * intercepted at the HTTP boundary so no request ever reaches AWS. We do NOT
 * mock `lib/aws/*` — that would bypass exactly the code an E2E run exists to
 * exercise (story Business Rules).
 *
 * Mechanism: a tiny local HTTP server that answers every request with a 200 and
 * an empty `application/json` body (a valid `InvokeAgentRuntime` acceptance —
 * the panel is fire-and-forget, D7, and ignores the response body). The Next.js
 * server under test is launched with `AWS_ENDPOINT_URL_BEDROCK_AGENTCORE`
 * pointed at this server, so the AWS SDK resolves its endpoint here instead of
 * the real `bedrock-agentcore` endpoint.
 *
 * A "fail" mode lets Scenario-style negative tests force a 5xx so the panel
 * takes its `failed_to_start` path (AC12) deterministically.
 *
 * This module is Node-only (http). It is imported by `global-setup.ts` and the
 * specs run against the server it launched — the specs never import the SDK.
 */

import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { AddressInfo } from "node:net";

export interface AgentCoreStubHandle {
  /** The base URL to hand the SDK via AWS_ENDPOINT_URL_BEDROCK_AGENTCORE. */
  endpoint: string;
  /** Requests observed, in arrival order (path + method), for assertions. */
  readonly requests: ReadonlyArray<{ method: string; url: string }>;
  /** Force the next N responses (default: all) to a 500 so the panel marks failed_to_start. */
  failNext(count?: number): void;
  /** Reset to accepting mode and clear the request log. */
  reset(): void;
  /** Stop the server. */
  close(): Promise<void>;
}

const DEFAULT_PORT = 0; // ephemeral

export async function startAgentCoreStub(port = DEFAULT_PORT): Promise<AgentCoreStubHandle> {
  const requests: { method: string; url: string }[] = [];
  let failRemaining = 0;

  const server: Server = createServer((req: IncomingMessage, res: ServerResponse) => {
    // Drain the body (the SDK sends the payload) — we don't need it, but we must
    // consume it so the socket closes cleanly.
    req.on("data", () => {});
    req.on("end", () => {
      requests.push({ method: req.method ?? "?", url: req.url ?? "/" });

      if (failRemaining > 0) {
        failRemaining -= 1;
        res.writeHead(500, { "content-type": "application/json" });
        // Shape the body like an AgentCore/service error so the SDK throws.
        res.end(JSON.stringify({ __type: "InternalServerException", message: "stub forced 500" }));
        return;
      }

      // Accept: 200 + empty JSON. InvokeAgentRuntime returns a streaming body;
      // the panel is fire-and-forget and does not read it, so an empty body is
      // a sufficient "accepted" for the E2E path.
      res.writeHead(200, { "content-type": "application/json" });
      res.end("{}");
    });
  });

  await new Promise<void>((resolve) => server.listen(port, "127.0.0.1", resolve));
  const address = server.address() as AddressInfo;
  const endpoint = `http://127.0.0.1:${address.port}`;

  return {
    endpoint,
    requests,
    failNext(count = Number.MAX_SAFE_INTEGER) {
      failRemaining = count;
    },
    reset() {
      failRemaining = 0;
      requests.length = 0;
    },
    close() {
      return new Promise<void>((resolve, reject) =>
        server.close((err) => (err ? reject(err) : resolve())),
      );
    },
  };
}
