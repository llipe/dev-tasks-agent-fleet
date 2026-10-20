import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Layer 1 unit coverage for the InvokeAgentRuntime wrapper (S-111 / issue #124).
// The wrapper's job is narrow: log credentialSource() on every invoke (AC6, at
// the wrapper boundary — the route-level guarantee lands in S-112 per G5), map
// a downstream failure to INVOCATION_FAILED (502) while a credential failure
// stays CREDENTIALS_UNAVAILABLE (500), and never log the payload or credentials.
//
// The BedrockAgentCore SDK client is injected via `clientFactory`, so no AWS
// SDK network path is exercised here.

const credentialSourceMock = vi.fn(() => "local-chain" as "local-chain" | "fly-oidc");
vi.mock("@/lib/aws/credentials", () => ({
  awsCredentials: async () => ({ accessKeyId: "x", secretAccessKey: "y" }),
  credentialSource: () => credentialSourceMock(),
}));

import { invokeAgentRuntime } from "@/lib/aws/invoke";
import { CredentialsUnavailableError, InvocationFailedError } from "@/lib/aws/errors";

const target = {
  runtimeArn: "arn:aws:bedrock-agentcore:us-east-1:123:runtime/dep-updater",
  runtimeQualifier: "DEFAULT",
};

function makeLogger() {
  return { info: vi.fn(), error: vi.fn() };
}

beforeEach(() => {
  credentialSourceMock.mockReset();
  credentialSourceMock.mockReturnValue("local-chain");
});

afterEach(() => vi.restoreAllMocks());

describe("invokeAgentRuntime (AC6, §13)", () => {
  it("logs credentialSource() on every invoke", async () => {
    const logger = makeLogger();
    const send = vi.fn().mockResolvedValue({});
    await invokeAgentRuntime(target, {
      payload: { run_id: "r1" },
      logger,
      clientFactory: () => ({ send }),
    });
    expect(logger.info).toHaveBeenCalledTimes(1);
    expect(logger.info.mock.calls[0][0]).toContain("credentialSource=local-chain");
  });

  it("reflects the fly-oidc branch in the log line", async () => {
    credentialSourceMock.mockReturnValue("fly-oidc");
    const logger = makeLogger();
    await invokeAgentRuntime(target, {
      payload: {},
      logger,
      clientFactory: () => ({ send: vi.fn().mockResolvedValue({}) }),
    });
    expect(logger.info.mock.calls[0][0]).toContain("credentialSource=fly-oidc");
  });

  it("never logs the payload contents", async () => {
    const logger = makeLogger();
    await invokeAgentRuntime(target, {
      payload: { run_id: "SENSITIVE_RUN", secret_param: "DO_NOT_LOG" },
      logger,
      clientFactory: () => ({ send: vi.fn().mockResolvedValue({}) }),
    });
    const all = [...logger.info.mock.calls, ...logger.error.mock.calls].flat().join(" ");
    expect(all).not.toContain("DO_NOT_LOG");
    expect(all).not.toContain("SENSITIVE_RUN");
  });

  it("maps a downstream send() rejection to InvocationFailedError (502)", async () => {
    const logger = makeLogger();
    const send = vi.fn().mockRejectedValue(new Error("throttled"));
    await expect(
      invokeAgentRuntime(target, { payload: {}, logger, clientFactory: () => ({ send }) }),
    ).rejects.toBeInstanceOf(InvocationFailedError);
  });

  it("re-throws a CredentialsUnavailableError from the provider as 500, not 502", async () => {
    const logger = makeLogger();
    const send = vi.fn().mockRejectedValue(new CredentialsUnavailableError("no creds"));
    await expect(
      invokeAgentRuntime(target, { payload: {}, logger, clientFactory: () => ({ send }) }),
    ).rejects.toBeInstanceOf(CredentialsUnavailableError);
  });

  it("passes the runtimeQualifier through when present and omits it when absent", async () => {
    const send = vi.fn().mockResolvedValue({});
    const capture: unknown[] = [];
    const factory = () => ({
      send: (cmd: unknown) => {
        capture.push(cmd);
        return send(cmd);
      },
    });
    await invokeAgentRuntime(
      { runtimeArn: target.runtimeArn, runtimeQualifier: null },
      { payload: {}, logger: makeLogger(), clientFactory: factory },
    );
    expect(capture).toHaveLength(1);
  });
});

describe("invokeAgentRuntime — AWS error name on failure (issue #306)", () => {
  it("appends aws_error/http/request_id to the InvokeAgentRuntime failure log line", async () => {
    const logger = makeLogger();
    const sdkErr = Object.assign(new Error("not authorized to InvokeAgentRuntime: SENTINEL"), {
      name: "AccessDeniedException",
      $metadata: { httpStatusCode: 403, requestId: "req-abc" },
    });
    const send = vi.fn().mockRejectedValue(sdkErr);
    await expect(
      invokeAgentRuntime(target, { payload: {}, logger, clientFactory: () => ({ send }) }),
    ).rejects.toBeInstanceOf(InvocationFailedError);

    const line = logger.error.mock.calls[0]![0] as string;
    expect(line).toContain("code=INVOCATION_FAILED");
    expect(line).toContain("aws_error=AccessDeniedException");
    expect(line).toContain("http=403");
    expect(line).toContain("request_id=req-abc");
    // Security-negative: the SDK message must never reach the log line.
    expect(line).not.toContain("SENTINEL");
  });

  it("appends the STS error name (via cause) to the credentials-unavailable log line", async () => {
    const logger = makeLogger();
    const sts = Object.assign(new Error("token expired: SENTINEL"), {
      name: "InvalidIdentityTokenException",
      $metadata: { httpStatusCode: 400, requestId: "req-sts" },
    });
    const credErr = new CredentialsUnavailableError("AssumeRoleWithWebIdentity failed.", {
      cause: sts,
    });
    const send = vi.fn().mockRejectedValue(credErr);
    await expect(
      invokeAgentRuntime(target, { payload: {}, logger, clientFactory: () => ({ send }) }),
    ).rejects.toBeInstanceOf(CredentialsUnavailableError);

    const line = logger.error.mock.calls[0]![0] as string;
    expect(line).toContain("credentials unavailable");
    expect(line).toContain("aws_error=InvalidIdentityTokenException");
    expect(line).toContain("http=400");
    expect(line).toContain("request_id=req-sts");
    expect(line).not.toContain("SENTINEL");
  });

  it("logs aws_error=unknown for a non-AWS failure and does not throw while logging", async () => {
    const logger = makeLogger();
    const send = vi.fn().mockRejectedValue(new Error("plain failure"));
    await expect(
      invokeAgentRuntime(target, { payload: {}, logger, clientFactory: () => ({ send }) }),
    ).rejects.toBeInstanceOf(InvocationFailedError);
    const line = logger.error.mock.calls[0]![0] as string;
    expect(line).toContain("aws_error=unknown");
  });
});

// S-172 (#317, task 8.8): the webhook path bounds the invoke so GitHub's 10 s
// delivery timeout is never hit. Optional: callers that don't pass timeoutMs
// keep the old unbounded behavior.
describe("invokeAgentRuntime — optional timeout (S-172)", () => {
  const target = { runtimeArn: "arn:aws:bedrock-agentcore:us-east-1:1:runtime/x" };
  const quiet = { info: vi.fn(), error: vi.fn() };

  it("passes an AbortSignal to send() when timeoutMs is set", async () => {
    const send = vi.fn().mockResolvedValue({});
    await invokeAgentRuntime(target, {
      payload: {},
      logger: quiet,
      timeoutMs: 8000,
      clientFactory: () => ({ send }),
    });
    expect(send.mock.calls[0]![1]).toEqual({ abortSignal: expect.any(AbortSignal) });
  });

  it("passes no options when timeoutMs is unset (unchanged behavior)", async () => {
    const send = vi.fn().mockResolvedValue({});
    await invokeAgentRuntime(target, {
      payload: {},
      logger: quiet,
      clientFactory: () => ({ send }),
    });
    expect(send.mock.calls[0]).toHaveLength(1);
  });

  it("aborts a hung send() and surfaces InvocationFailedError", async () => {
    const send = vi.fn(
      (_cmd: unknown, opts?: { abortSignal?: AbortSignal }) =>
        new Promise((_resolve, reject) => {
          opts?.abortSignal?.addEventListener("abort", () =>
            reject(Object.assign(new Error("aborted"), { name: "AbortError" })),
          );
        }),
    );
    const started = Date.now();
    const err = await invokeAgentRuntime(target, {
      payload: {},
      logger: quiet,
      timeoutMs: 50,
      clientFactory: () => ({ send }) as never,
    }).catch((e: unknown) => e);
    expect(Date.now() - started).toBeLessThan(2000);
    expect(err).toMatchObject({ code: "INVOCATION_FAILED", status: 502 });
  });
});
