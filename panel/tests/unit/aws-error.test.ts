import { describe, expect, it } from "vitest";
import { describeAwsError } from "@/lib/aws/aws-error";

// Layer 1 — issue #306. `describeAwsError(err)` is a pure helper that extracts
// ONLY the safe identifying fields of an AWS SDK error so an operator can
// diagnose a production failure from the logs:
//
//   aws_error  — the SDK error `name` (bounded charset, max 100 chars)
//   http       — `$metadata.httpStatusCode` (integer only)
//   request_id — `$metadata.requestId` (bounded charset)
//
// It NEVER returns the error `message`, the payload, tokens, or credentials. It
// follows `cause` one level (for errors the panel wraps) and never throws.

describe("describeAwsError (issue #306)", () => {
  it("extracts name + httpStatusCode + requestId from an SDK-shaped error", () => {
    const err = {
      name: "AccessDeniedException",
      message: "User: arn:... is not authorized to perform bedrock:InvokeAgentRuntime",
      $metadata: { httpStatusCode: 403, requestId: "r-1" },
    };
    expect(describeAwsError(err)).toEqual({
      aws_error: "AccessDeniedException",
      http: 403,
      request_id: "r-1",
    });
  });

  it("omits http/request_id when $metadata is absent but keeps the name", () => {
    const err = Object.assign(new Error("boom"), { name: "ThrottlingException" });
    expect(describeAwsError(err)).toEqual({ aws_error: "ThrottlingException" });
  });

  it("returns aws_error=unknown for a plain Error with a generic name", () => {
    expect(describeAwsError(new Error("something went wrong"))).toEqual({ aws_error: "unknown" });
  });

  it("returns aws_error=unknown for a non-object and never throws", () => {
    expect(describeAwsError(null)).toEqual({ aws_error: "unknown" });
    expect(describeAwsError(undefined)).toEqual({ aws_error: "unknown" });
    expect(describeAwsError("a string")).toEqual({ aws_error: "unknown" });
    expect(describeAwsError(42)).toEqual({ aws_error: "unknown" });
  });

  it("follows cause one level (errors the panel wraps)", () => {
    const inner = {
      name: "InvalidIdentityTokenException",
      message: "token is expired",
      $metadata: { httpStatusCode: 400, requestId: "r-sts" },
    };
    const wrapper = Object.assign(new Error("AssumeRoleWithWebIdentity failed."), {
      name: "CredentialsUnavailableError",
      cause: inner,
    });
    expect(describeAwsError(wrapper)).toEqual({
      aws_error: "InvalidIdentityTokenException",
      http: 400,
      request_id: "r-sts",
    });
  });

  it("does not recurse past one cause level", () => {
    const deepest = { name: "DeepException", $metadata: { httpStatusCode: 500 } };
    // The middle error is a panel wrapper (generic name) carrying the deepest
    // SDK error as its cause. The outer is ALSO a panel wrapper. Following one
    // level from the outer reaches `middle` (still a generic wrapper name), and
    // we do NOT recurse again into `deepest` — so the result is unknown.
    const middle = Object.assign(new Error("mid"), {
      name: "CredentialsUnavailableError",
      cause: deepest,
    });
    const outer = Object.assign(new Error("out"), {
      name: "InvocationFailedError",
      cause: middle,
    });
    expect(describeAwsError(outer)).toEqual({ aws_error: "unknown" });
  });

  it("surfaces the SDK name through a single panel-wrapper hop", () => {
    const sdk = {
      name: "AccessDeniedException",
      $metadata: { httpStatusCode: 403, requestId: "r-9" },
    };
    const wrapped = Object.assign(new Error("InvokeAgentRuntime failed."), {
      name: "InvocationFailedError",
      cause: sdk,
    });
    expect(describeAwsError(wrapped)).toEqual({
      aws_error: "AccessDeniedException",
      http: 403,
      request_id: "r-9",
    });
  });

  it("never returns the error message", () => {
    const err = {
      name: "ValidationException",
      message: "SECRET-IN-MESSAGE",
      $metadata: { httpStatusCode: 400, requestId: "r-2" },
    };
    const out = describeAwsError(err);
    expect(JSON.stringify(out)).not.toContain("SECRET-IN-MESSAGE");
    expect("message" in out).toBe(false);
  });

  it("drops a name outside the bounded charset (potential injection) to unknown", () => {
    const err = { name: "Bad Name With Spaces!\n$metadata", $metadata: { httpStatusCode: 400 } };
    // Charset violation → name is not trusted; falls back to unknown but still
    // keeps the safe integer http field.
    expect(describeAwsError(err)).toEqual({ aws_error: "unknown", http: 400 });
  });

  it("truncates an over-long name to 100 chars", () => {
    const long = "A".repeat(250);
    const out = describeAwsError({ name: long, $metadata: { httpStatusCode: 500 } });
    expect(out.aws_error).toHaveLength(100);
    expect(out.aws_error).toBe("A".repeat(100));
  });

  it("drops a non-integer httpStatusCode and a non-string/charset-violating requestId", () => {
    const err = {
      name: "ValidationException",
      $metadata: { httpStatusCode: "403", requestId: { nested: "x" } },
    };
    expect(describeAwsError(err)).toEqual({ aws_error: "ValidationException" });
  });

  it("drops a requestId that violates the bounded charset", () => {
    const err = {
      name: "ValidationException",
      $metadata: { httpStatusCode: 400, requestId: "r 1\nwith spaces" },
    };
    expect(describeAwsError(err)).toEqual({ aws_error: "ValidationException", http: 400 });
  });
});
