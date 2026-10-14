import { describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

// The probe's classification logic is pure and unit-testable with NO socket and
// NO network. These tests pin the two security-critical properties of Issue
// #280's regression guard (D-05):
//   1. The status / token-presence verdict is derived EXACTLY as
//      credentials.ts's `extractOidcToken` would see it (string `value` OR
//      `token` → present; anything else → absent), and a pass requires BOTH a
//      2xx status AND a present token.
//   2. The token value is NEVER echoed — the only output is
//      `status=<code> token=<present|absent>`.
// The .mjs helper has no type declarations; allowJs lets TS infer them.
import { classifyProbe, statusIsOk, tokenIsPresent } from "../../scripts/fly-oidc-probe.mjs";
import { extractOidcToken } from "@/lib/aws/credentials";

// A realistic three-segment JWT (header.payload.signature), base64url, no
// padding. Never a real token.
const RAW_JWT =
  "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9." +
  "eyJhdWQiOiJzdHMuYW1hem9uYXdzLmNvbSIsInN1YiI6Im9yZzphcHA6bWFjaGluZSJ9." +
  "c2lnbmF0dXJlLXNlZ21lbnQtYmFzZTY0dXJsLWVuY29kZWQtZGF0YQ";

describe("tokenIsPresent — mirrors extractOidcToken's acceptance rule", () => {
  it("accepts a string `value` key", () => {
    expect(tokenIsPresent(JSON.stringify({ value: "a.b.c" }))).toBe(true);
  });

  it("accepts a string `token` key", () => {
    expect(tokenIsPresent(JSON.stringify({ token: "a.b.c" }))).toBe(true);
  });

  it("accepts a raw JWT body (#280 D-07 — the real Fly shape)", () => {
    expect(tokenIsPresent(RAW_JWT)).toBe(true);
  });

  it("accepts a raw JWT body with surrounding whitespace", () => {
    expect(tokenIsPresent(`\n  ${RAW_JWT}\n`)).toBe(true);
  });

  it("accepts a JSON-encoded string that is itself JWT-shaped", () => {
    expect(tokenIsPresent(JSON.stringify(RAW_JWT))).toBe(true);
  });

  it("rejects a non-string value/token", () => {
    expect(tokenIsPresent(JSON.stringify({ value: 123 }))).toBe(false);
    expect(tokenIsPresent(JSON.stringify({ token: null }))).toBe(false);
  });

  it("rejects the audience-only shape (the F5 trap — `aud` is not a token)", () => {
    expect(tokenIsPresent(JSON.stringify({ aud: "sts.amazonaws.com" }))).toBe(false);
  });

  it("rejects a two-segment string (not a JWT)", () => {
    expect(tokenIsPresent("only.two")).toBe(false);
  });

  it("rejects an HTML error page", () => {
    expect(tokenIsPresent("<html><body>502 Bad Gateway</body></html>")).toBe(false);
  });

  it("rejects a non-object JSON body (array / scalar)", () => {
    expect(tokenIsPresent(JSON.stringify(["a.b.c"]))).toBe(false);
    expect(tokenIsPresent(JSON.stringify("not a jwt"))).toBe(false);
    expect(tokenIsPresent(JSON.stringify(null))).toBe(false);
  });

  it("rejects an unparseable / empty body", () => {
    expect(tokenIsPresent("{not json")).toBe(false);
    expect(tokenIsPresent("")).toBe(false);
    // The runtime guard also tolerates a non-string; cast to exercise it.
    expect((tokenIsPresent as (b: unknown) => boolean)(undefined)).toBe(false);
  });
});

// The probe (a standalone .mjs shipped into the image, no lib/ beside it) and
// credentials.ts duplicate the JWT-shape rule. This test proves they cannot
// drift: the SAME corpus must be accepted/rejected by BOTH. (#280 D-07.)
describe("probe/credentials parity — identical accept/reject corpus (#280 D-07)", () => {
  const ACCEPT: ReadonlyArray<readonly [string, string]> = [
    ["raw JWT", RAW_JWT],
    ["raw JWT with whitespace", `\n ${RAW_JWT} \n`],
    ["JSON {value}", JSON.stringify({ value: RAW_JWT })],
    ["JSON {token}", JSON.stringify({ token: RAW_JWT })],
    ["JSON-encoded JWT string", JSON.stringify(RAW_JWT)],
    ["JWT with empty signature", "eyJhbGciOiJub25lIn0.eyJzdWIiOiJhIn0."],
  ];

  const REJECT: ReadonlyArray<readonly [string, string]> = [
    ["empty", ""],
    ["whitespace only", "   "],
    ["empty object", "{}"],
    ["audience-only", JSON.stringify({ aud: "sts.amazonaws.com" })],
    ["HTML error page", "<html><body>502 Bad Gateway</body></html>"],
    ["two-segment string", "only.two"],
    ["non-string value", JSON.stringify({ value: 123 })],
    ["JSON array", JSON.stringify(["a.b.c"])],
  ];

  it.each(ACCEPT)("both ACCEPT: %s", (_label, body) => {
    expect(tokenIsPresent(body)).toBe(true);
    expect(extractOidcToken(body)).toBeTypeOf("string");
  });

  it.each(REJECT)("both REJECT: %s", (_label, body) => {
    expect(tokenIsPresent(body)).toBe(false);
    expect(() => extractOidcToken(body)).toThrow();
  });
});

describe("statusIsOk — 2xx only", () => {
  it.each([200, 201, 204, 299])("accepts %s", (s) => {
    expect(statusIsOk(s)).toBe(true);
  });

  it.each([0, 100, 301, 400, 401, 403, 404, 500])("rejects %s", (s) => {
    expect(statusIsOk(s)).toBe(false);
  });

  it("rejects a non-number status", () => {
    expect(statusIsOk(undefined)).toBe(false);
  });
});

describe("classifyProbe — verdict line + exit code", () => {
  it("passes (exit 0) on 200 with a present token", () => {
    const v = classifyProbe({ status: 200, body: JSON.stringify({ value: "a.b.c" }) });
    expect(v.ok).toBe(true);
    expect(v.exitCode).toBe(0);
    expect(v.line).toBe("status=200 token=present");
  });

  it("fails (exit 1) on 200 with the WRONG shape (token absent)", () => {
    // A 200 that returns the audience, not a token: credentials.ts would throw
    // FlyOidcShapeError at invoke time, so the probe must call this a failure.
    const v = classifyProbe({ status: 200, body: JSON.stringify({ aud: "sts.amazonaws.com" }) });
    expect(v.ok).toBe(false);
    expect(v.exitCode).toBe(1);
    expect(v.line).toBe("status=200 token=absent");
  });

  it("fails on a 404 (connected as root today) with no token", () => {
    const v = classifyProbe({ status: 404, body: "" });
    expect(v.ok).toBe(false);
    expect(v.line).toBe("status=404 token=absent");
  });

  it("fails on a transport error surfaced as status 0 (EACCES / missing socket)", () => {
    const v = classifyProbe({ status: 0, body: "" });
    expect(v.ok).toBe(false);
    expect(v.exitCode).toBe(1);
    expect(v.line).toBe("status=0 token=absent");
  });

  it("is total — garbage input never throws, verdict is a failure", () => {
    // The JSDoc-inferred param type is narrower than the runtime guard, which
    // is intentionally total; cast through unknown to exercise the guard.
    const call = classifyProbe as (r: unknown) => ReturnType<typeof classifyProbe>;
    expect(call(undefined).ok).toBe(false);
    expect(call(null).line).toBe("status=0 token=absent");
    expect(call({}).ok).toBe(false);
  });
});

describe("no-token-echo — the token value never appears in any output", () => {
  // The whole point of D-05: presence is reported, the token is not. If the
  // secret string appears anywhere in the verdict line, that is a leak.
  const SECRET = "SUPER-SECRET-OIDC-TOKEN-eyJhbGciOi.payload.sig";

  it("classifyProbe never includes the token in its line", () => {
    const v = classifyProbe({ status: 200, body: JSON.stringify({ value: SECRET }) });
    expect(v.line).not.toContain(SECRET);
    expect(v.line).toBe("status=200 token=present");
    // Guard against any future field leaking the value, not just `line`.
    expect(JSON.stringify(v)).not.toContain(SECRET);
  });

  it("the CLI prints only the status/presence line, never the token (stdout+stderr)", () => {
    // Run the probe as a child process against a non-existent socket override
    // (the AC5 negative-demo path). It can never reach a real token, so to
    // prove no-echo we assert the output shape is exactly the one line and
    // carries no JWT-ish material.
    const probePath = fileURLToPath(new URL("../../scripts/fly-oidc-probe.mjs", import.meta.url));
    let stdout = "";
    let combined = "";
    try {
      stdout = execFileSync(process.execPath, [probePath], {
        env: { ...process.env, FLY_OIDC_SOCKET: "/nonexistent/.fly/api-does-not-exist" },
        encoding: "utf8",
      });
      combined = stdout;
    } catch (err) {
      // Non-zero exit is expected (absent token). Capture its output.
      const e = err as { stdout?: unknown; stderr?: unknown; status?: number };
      stdout = String(e.stdout ?? "");
      combined = stdout + String(e.stderr ?? "");
      expect(e.status).toBe(1);
    }
    expect(stdout.trim()).toBe("status=0 token=absent");
    // No token value could exist, but assert the output never carries a bearer-
    // ish blob regardless (defense against a future regression that logs more).
    expect(combined).not.toMatch(/eyJ[A-Za-z0-9_-]{10,}/);
  });
});
