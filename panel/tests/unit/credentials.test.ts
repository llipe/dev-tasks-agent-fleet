import { EventEmitter } from "node:events";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Layer 1 unit coverage for the AWS credential provider (S-111 / issue #124).
// The module talks to three external boundaries — node:fs (socket existence),
// node:http (the Fly OIDC socket), and @aws-sdk/client-sts
// (AssumeRoleWithWebIdentity) — all mocked here so the suite is deterministic
// and needs no network, no Fly Machine, and no AWS account. There is no
// integration layer by design: the real OIDC socket only exists on a Fly
// Machine (S-115).
//
// Covers: branch detection (CT/AC1), token extraction accept/reject shapes
// (CT-8/AC3), the F5 defect (`{aud}` must throw, never return the audience),
// cache hit/miss (EC-7/AC5), single-flight (EC-6/AC5), STS failure →
// CREDENTIALS_UNAVAILABLE (CT-9/AC8), connection refused / socket 500 (EC-10),
// missing role ARN (EC-11), and the secret-material-absent-from-logs assertion
// (AC6/§13).

// --- module mocks -----------------------------------------------------------

const existsSyncMock = vi.fn<(p: string) => boolean>();
vi.mock("node:fs", () => ({ existsSync: (p: string) => existsSyncMock(p) }));

const httpRequestMock = vi.fn();
vi.mock("node:http", () => ({ request: (...args: unknown[]) => httpRequestMock(...args) }));

const stsSendMock = vi.fn();
const assumeRoleCtor = vi.fn((input: unknown) => ({ input }));
vi.mock("@aws-sdk/client-sts", () => ({
  STSClient: class {
    send = stsSendMock;
  },
  AssumeRoleWithWebIdentityCommand: class {
    input: unknown;
    constructor(input: unknown) {
      assumeRoleCtor(input);
      this.input = input;
    }
  },
}));

const localChainProvider = vi.hoisted(() =>
  vi.fn(async () => ({
    accessKeyId: "LOCAL_AKID",
    secretAccessKey: "LOCAL_SECRET",
  })),
);
vi.mock("@aws-sdk/credential-providers", () => ({
  fromNodeProviderChain: () => localChainProvider,
}));

// Imported after the mocks are registered.
import {
  __resetCredentialCacheForTests,
  awsCredentials,
  credentialSource,
  extractOidcToken,
} from "@/lib/aws/credentials";
import { CredentialsUnavailableError, FlyOidcShapeError } from "@/lib/aws/errors";

// --- helpers ----------------------------------------------------------------

/** Simulate the Fly socket: the response body + status the http mock yields. */
function mockSocketResponse(opts: { statusCode: number; body: string }): void {
  httpRequestMock.mockImplementation((_options: unknown, cb: (res: EventEmitter) => void) => {
    const res = new EventEmitter() as EventEmitter & { statusCode?: number };
    res.statusCode = opts.statusCode;
    const req = new EventEmitter() as EventEmitter & { write: () => void; end: () => void };
    req.write = () => {};
    req.end = () => {
      // Deliver the response asynchronously, like the real socket.
      queueMicrotask(() => {
        cb(res);
        res.emit("data", opts.body);
        res.emit("end");
      });
    };
    return req;
  });
}

/** Simulate a socket-level connection error (ECONNREFUSED etc.). */
function mockSocketError(message: string): void {
  httpRequestMock.mockImplementation(() => {
    const req = new EventEmitter() as EventEmitter & { write: () => void; end: () => void };
    req.write = () => {};
    req.end = () => {
      queueMicrotask(() => req.emit("error", new Error(message)));
    };
    return req;
  });
}

function stsCreds(expiresInMs: number) {
  return {
    Credentials: {
      AccessKeyId: "STS_AKID",
      SecretAccessKey: "STS_SECRET",
      SessionToken: "STS_SESSION",
      Expiration: new Date(Date.now() + expiresInMs),
    },
  };
}

const savedEnv = { ...process.env };

beforeEach(() => {
  __resetCredentialCacheForTests();
  existsSyncMock.mockReset();
  httpRequestMock.mockReset();
  stsSendMock.mockReset();
  assumeRoleCtor.mockClear();
  localChainProvider.mockClear();
  delete process.env.FLY_APP_NAME;
  delete process.env.AGENT_RUNTIME_ROLE_ARN;
  delete process.env.AWS_REGION;
  delete process.env.FLY_MACHINE_ID;
});

afterEach(() => {
  process.env = { ...savedEnv };
  vi.restoreAllMocks();
});

// --- branch detection (AC1) -------------------------------------------------

describe("branch detection — credentialSource() (AC1)", () => {
  it("reports fly-oidc when FLY_APP_NAME is set and the socket exists", () => {
    process.env.FLY_APP_NAME = "panel-agentes";
    existsSyncMock.mockReturnValue(true);
    expect(credentialSource()).toBe("fly-oidc");
  });

  it("reports local-chain when FLY_APP_NAME is set but the socket is absent", () => {
    process.env.FLY_APP_NAME = "panel-agentes";
    existsSyncMock.mockReturnValue(false);
    expect(credentialSource()).toBe("local-chain");
  });

  it("reports local-chain when FLY_APP_NAME is absent", () => {
    existsSyncMock.mockReturnValue(true);
    expect(credentialSource()).toBe("local-chain");
  });
});

// --- token extraction (AC3, CT-8, F5) --------------------------------------

describe("extractOidcToken — accepts value|token only (AC3, CT-8)", () => {
  it("accepts a string `value`", () => {
    expect(extractOidcToken(JSON.stringify({ value: "the-jwt" }))).toBe("the-jwt");
  });

  it("accepts a string `token`", () => {
    expect(extractOidcToken(JSON.stringify({ token: "the-jwt" }))).toBe("the-jwt");
  });

  it("prefers `value` when both are present", () => {
    expect(extractOidcToken(JSON.stringify({ value: "v", token: "t" }))).toBe("v");
  });

  it("throws FlyOidcShapeError on {aud} — the F5 defect (never returns the audience)", () => {
    const body = JSON.stringify({ aud: "sts.amazonaws.com" });
    expect(() => extractOidcToken(body)).toThrow(FlyOidcShapeError);
    try {
      extractOidcToken(body);
    } catch (err) {
      // The message names the received key, not its value.
      expect((err as FlyOidcShapeError).receivedKeys).toEqual(["aud"]);
      expect((err as Error).message).toContain("aud");
      expect((err as Error).message).not.toContain("sts.amazonaws.com");
    }
  });

  it("throws FlyOidcShapeError on an empty object {}", () => {
    expect(() => extractOidcToken("{}")).toThrow(FlyOidcShapeError);
  });

  it("throws FlyOidcShapeError on a non-JSON body (no data.trim() fallback)", () => {
    expect(() => extractOidcToken("not-json-at-all")).toThrow(FlyOidcShapeError);
    try {
      extractOidcToken("not-json-at-all");
    } catch (err) {
      expect((err as FlyOidcShapeError).receivedKeys).toEqual([]);
      expect((err as Error).message).toContain("not valid JSON");
    }
  });

  it("throws FlyOidcShapeError when `value` is a non-string ({value:12345})", () => {
    expect(() => extractOidcToken(JSON.stringify({ value: 12345 }))).toThrow(FlyOidcShapeError);
  });

  it("throws FlyOidcShapeError on a JSON array", () => {
    expect(() => extractOidcToken("[1,2,3]")).toThrow(FlyOidcShapeError);
  });

  it("carries the CREDENTIALS_UNAVAILABLE code on FlyOidcShapeError", () => {
    try {
      extractOidcToken("{}");
    } catch (err) {
      expect((err as FlyOidcShapeError).code).toBe("CREDENTIALS_UNAVAILABLE");
      expect((err as FlyOidcShapeError).status).toBe(500);
    }
  });
});

// --- local branch (AC4) -----------------------------------------------------

describe("local branch (AC4)", () => {
  it("delegates to fromNodeProviderChain() when not on Fly", async () => {
    existsSyncMock.mockReturnValue(false);
    const creds = await awsCredentials();
    expect(localChainProvider).toHaveBeenCalledTimes(1);
    expect(creds).toEqual({ accessKeyId: "LOCAL_AKID", secretAccessKey: "LOCAL_SECRET" });
    // The Fly path must not be touched.
    expect(stsSendMock).not.toHaveBeenCalled();
  });
});

// --- Fly branch: STS exchange + AC2 -----------------------------------------

describe("Fly branch — OIDC → AssumeRoleWithWebIdentity (AC2)", () => {
  beforeEach(() => {
    process.env.FLY_APP_NAME = "panel-agentes";
    process.env.AGENT_RUNTIME_ROLE_ARN = "arn:aws:iam::123456789012:role/panel";
    existsSyncMock.mockReturnValue(true);
  });

  it("requests the socket with aud=sts.amazonaws.com and exchanges the token via STS", async () => {
    let sentBody = "";
    // Capture the exact request options + written body the module sends.
    httpRequestMock.mockImplementation((opts: unknown, cb: (res: EventEmitter) => void) => {
      const options = opts as { socketPath?: string; path?: string; method?: string };
      const res = new EventEmitter() as EventEmitter & { statusCode?: number };
      res.statusCode = 200;
      const req = new EventEmitter() as EventEmitter & {
        write: (b: string) => void;
        end: () => void;
      };
      req.write = (b: string) => {
        sentBody = b;
      };
      req.end = () => {
        queueMicrotask(() => {
          cb(res);
          res.emit("data", JSON.stringify({ value: "the-jwt" }));
          res.emit("end");
        });
      };
      // Assert the request is aimed at the OIDC socket + path.
      expect(options.socketPath).toBe("/.fly/api");
      expect(options.path).toBe("/v1/tokens/oidc");
      expect(options.method).toBe("POST");
      return req;
    });
    stsSendMock.mockResolvedValue(stsCreds(3_600_000));

    const creds = await awsCredentials();

    // The request body carries the audience.
    expect(JSON.parse(sentBody).aud).toBe("sts.amazonaws.com");

    // The extracted token was forwarded to STS.
    expect(assumeRoleCtor).toHaveBeenCalledTimes(1);
    expect(assumeRoleCtor.mock.calls[0][0]).toMatchObject({
      RoleArn: "arn:aws:iam::123456789012:role/panel",
      WebIdentityToken: "the-jwt",
      DurationSeconds: 900,
    });
    expect(creds).toMatchObject({ accessKeyId: "STS_AKID", sessionToken: "STS_SESSION" });
  });

  it("throws CredentialsUnavailableError with a named message when AGENT_RUNTIME_ROLE_ARN is unset (EC-11)", async () => {
    delete process.env.AGENT_RUNTIME_ROLE_ARN;
    await expect(awsCredentials()).rejects.toBeInstanceOf(CredentialsUnavailableError);
    await expect(awsCredentials()).rejects.toThrow(/AGENT_RUNTIME_ROLE_ARN is not set/);
  });
});

// --- cache + single-flight (AC5, EC-6, EC-7) --------------------------------

describe("cache and single-flight (AC5, EC-6, EC-7)", () => {
  beforeEach(() => {
    process.env.FLY_APP_NAME = "panel-agentes";
    process.env.AGENT_RUNTIME_ROLE_ARN = "arn:aws:iam::123456789012:role/panel";
    existsSyncMock.mockReturnValue(true);
    mockSocketResponse({ statusCode: 200, body: JSON.stringify({ value: "the-jwt" }) });
  });

  it("serves a cached credential on the second call within the refresh margin (EC-7: 61s away → hit)", async () => {
    stsSendMock.mockResolvedValue(stsCreds(61_000)); // expiry 61s away, outside the 60s margin
    await awsCredentials();
    await awsCredentials();
    expect(stsSendMock).toHaveBeenCalledTimes(1); // second call hit the cache
  });

  it("refreshes when the cached credential is inside the 60s refresh margin (EC-7: 59s away → miss)", async () => {
    stsSendMock.mockResolvedValue(stsCreds(59_000)); // expiry 59s away, inside the margin
    await awsCredentials();
    await awsCredentials();
    expect(stsSendMock).toHaveBeenCalledTimes(2); // both refreshed
  });

  it("collapses two concurrent cold-cache calls into one STS call (EC-6 single-flight)", async () => {
    // A slow-but-self-resolving STS mock: both concurrent callers must share
    // the one in-flight promise rather than each starting their own exchange.
    stsSendMock.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve(stsCreds(3_600_000)), 20)),
    );
    const [c1, c2] = await Promise.all([awsCredentials(), awsCredentials()]);
    expect(stsSendMock).toHaveBeenCalledTimes(1);
    expect(c1).toBe(c2); // same object, single flight
  });
});

// --- failure modes (CT-9, EC-10) --------------------------------------------

describe("failure modes surface CREDENTIALS_UNAVAILABLE, never a generic error (CT-9, EC-10)", () => {
  beforeEach(() => {
    process.env.FLY_APP_NAME = "panel-agentes";
    process.env.AGENT_RUNTIME_ROLE_ARN = "arn:aws:iam::123456789012:role/panel";
    existsSyncMock.mockReturnValue(true);
  });

  it("maps an STS AccessDenied rejection to CREDENTIALS_UNAVAILABLE", async () => {
    mockSocketResponse({ statusCode: 200, body: JSON.stringify({ value: "the-jwt" }) });
    stsSendMock.mockRejectedValue(
      Object.assign(new Error("AccessDenied"), { name: "AccessDenied" }),
    );
    await expect(awsCredentials()).rejects.toBeInstanceOf(CredentialsUnavailableError);
  });

  it("maps an STS InvalidIdentityToken rejection to CREDENTIALS_UNAVAILABLE", async () => {
    mockSocketResponse({ statusCode: 200, body: JSON.stringify({ value: "the-jwt" }) });
    stsSendMock.mockRejectedValue(new Error("InvalidIdentityToken"));
    await expect(awsCredentials()).rejects.toBeInstanceOf(CredentialsUnavailableError);
  });

  it("maps a socket connection refused to CREDENTIALS_UNAVAILABLE, never a silent local fallback (EC-10)", async () => {
    mockSocketError("connect ECONNREFUSED /.fly/api");
    await expect(awsCredentials()).rejects.toBeInstanceOf(CredentialsUnavailableError);
    await expect(awsCredentials()).rejects.toThrow(/unreachable/);
    // Must NOT fall back to the local chain.
    expect(localChainProvider).not.toHaveBeenCalled();
  });

  it("maps a socket HTTP 500 to CREDENTIALS_UNAVAILABLE (EC-10)", async () => {
    mockSocketResponse({ statusCode: 500, body: "internal error" });
    await expect(awsCredentials()).rejects.toBeInstanceOf(CredentialsUnavailableError);
    await expect(awsCredentials()).rejects.toThrow(/HTTP 500/);
  });

  it("maps incomplete STS credentials to CREDENTIALS_UNAVAILABLE", async () => {
    mockSocketResponse({ statusCode: 200, body: JSON.stringify({ value: "the-jwt" }) });
    stsSendMock.mockResolvedValue({ Credentials: { AccessKeyId: "only-akid" } });
    await expect(awsCredentials()).rejects.toThrow(/incomplete credentials/);
  });
});

// --- no secret material in logs (AC6, §13) ----------------------------------

describe("no secret material leaks into logs (§13)", () => {
  it("emits nothing to console during a successful Fly credential fetch", async () => {
    process.env.FLY_APP_NAME = "panel-agentes";
    process.env.AGENT_RUNTIME_ROLE_ARN = "arn:aws:iam::123456789012:role/panel";
    existsSyncMock.mockReturnValue(true);
    mockSocketResponse({ statusCode: 200, body: JSON.stringify({ value: "super-secret-jwt" }) });
    stsSendMock.mockResolvedValue(stsCreds(3_600_000));

    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const infoSpy = vi.spyOn(console, "info").mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    await awsCredentials();

    const allOutput = [logSpy, infoSpy, errorSpy, warnSpy]
      .flatMap((s) => s.mock.calls.flat())
      .join(" ");
    // The credentials module itself logs nothing; assert no secret material.
    expect(allOutput).not.toContain("super-secret-jwt");
    expect(allOutput).not.toContain("STS_SECRET");
    expect(allOutput).not.toContain("STS_SESSION");
  });
});
