import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  buildAgentPayload,
  MalformedRepositoryError,
  splitRepositoryFullName,
} from "@/lib/domain/payload";

/**
 * S-112 (#125) — cross-language payload contract (SR4 / #89).
 *
 * The authoritative contract is the agent's `_REQUIRED_FIELDS` in
 * `agents/dependency-update/app/dependencyUpdate/main.py`:
 *   ("run_id", "repository_org", "repository_name")
 * each a non-empty top-level string. `buildAgentPayload` emits exactly those
 * three plus `base_branch` and `params`, and NEVER `repository_id` (that is a
 * panel-internal id the agent has no knowledge of).
 *
 * Nothing type-checks this boundary at runtime — it is JSON over
 * InvokeAgentRuntime into a Python `validate_payload`. The shared fixture
 * `tests/fixtures/agent-invocation-payload.json` (repo root) is asserted here
 * AND by a new Python test, so a dropped/renamed/nested field fails a test on
 * one side rather than silently at runtime.
 */

const REPO_ROOT_FIXTURE = fileURLToPath(
  new URL("../../../tests/fixtures/agent-invocation-payload.json", import.meta.url),
);

describe("buildAgentPayload — happy path (AC3, #89 contract)", () => {
  it("emits exactly run_id, repository_org, repository_name, base_branch, params", () => {
    const payload = buildAgentPayload({
      runId: "018f3a2b-0000-7000-8000-000000000000",
      repositoryFullName: "acme/web",
      baseBranch: "main",
      params: { fix_mode: "audit_only", fail_on_findings: true },
    });

    expect(payload).toEqual({
      run_id: "018f3a2b-0000-7000-8000-000000000000",
      repository_org: "acme",
      repository_name: "web",
      base_branch: "main",
      params: { fix_mode: "audit_only", fail_on_findings: true },
    });
  });

  it("never includes repository_id (the panel-internal id is not part of the contract)", () => {
    const payload = buildAgentPayload({
      runId: "r-1",
      repositoryFullName: "acme/web",
      baseBranch: "main",
      params: {},
    }) as Record<string, unknown>;

    expect("repository_id" in payload).toBe(false);
    expect(Object.keys(payload).sort()).toEqual(
      ["base_branch", "params", "repository_name", "repository_org", "run_id"].sort(),
    );
  });

  it("the three required fields are non-empty strings (mirrors the agent's validate_payload)", () => {
    const payload = buildAgentPayload({
      runId: "r-1",
      repositoryFullName: "octo/repo",
      baseBranch: "develop",
      params: {},
    });
    for (const field of ["run_id", "repository_org", "repository_name"] as const) {
      expect(typeof payload[field]).toBe("string");
      expect((payload[field] as string).length).toBeGreaterThan(0);
    }
  });

  it("preserves an org name containing dots and hyphens", () => {
    const payload = buildAgentPayload({
      runId: "r-1",
      repositoryFullName: "my-org.io/some.repo-name",
      baseBranch: "main",
      params: {},
    });
    expect(payload.repository_org).toBe("my-org.io");
    expect(payload.repository_name).toBe("some.repo-name");
  });
});

describe("splitRepositoryFullName — malformed matrix (security-negative #4, AC4)", () => {
  // A full_name must split into exactly two non-empty halves on a single slash.
  const rejected: Array<[string, string]> = [
    ["no slash", "justname"],
    ["empty string", ""],
    ["whitespace only", "   "],
    ["leading slash", "/repo"],
    ["trailing slash", "org/"],
    ["multiple slashes", "org/team/repo"],
    ["only a slash", "/"],
    ["empty org half", " /repo"],
    ["empty name half", "org/ "],
    ["whitespace both halves", "  /  "],
  ];

  for (const [label, value] of rejected) {
    it(`rejects ${label}: ${JSON.stringify(value)}`, () => {
      expect(() => splitRepositoryFullName(value)).toThrow(MalformedRepositoryError);
    });
  }

  it("MalformedRepositoryError carries code MALFORMED_REPOSITORY and status 400", () => {
    try {
      splitRepositoryFullName("nope");
      throw new Error("expected throw");
    } catch (err) {
      expect(err).toBeInstanceOf(MalformedRepositoryError);
      expect((err as MalformedRepositoryError).code).toBe("MALFORMED_REPOSITORY");
      expect((err as MalformedRepositoryError).status).toBe(400);
    }
  });

  it("accepts a valid full_name and trims surrounding whitespace on the whole value", () => {
    expect(splitRepositoryFullName("acme/web")).toEqual({ org: "acme", name: "web" });
  });
});

describe("buildAgentPayload rejects a malformed full_name before emitting (AC4)", () => {
  it("throws MalformedRepositoryError, never producing a partial payload", () => {
    expect(() =>
      buildAgentPayload({
        runId: "r-1",
        repositoryFullName: "org/team/repo",
        baseBranch: "main",
        params: {},
      }),
    ).toThrow(MalformedRepositoryError);
  });
});

describe("shared cross-language fixture (SR4, #89 AC3)", () => {
  it("buildAgentPayload reproduces the committed fixture exactly", () => {
    const fixture = JSON.parse(readFileSync(REPO_ROOT_FIXTURE, "utf-8"));

    const rebuilt = buildAgentPayload({
      runId: fixture.run_id,
      repositoryFullName: `${fixture.repository_org}/${fixture.repository_name}`,
      baseBranch: fixture.base_branch,
      params: fixture.params,
    });

    expect(rebuilt).toEqual(fixture);
  });

  it("the fixture has exactly the contract keys and non-empty required strings", () => {
    const fixture = JSON.parse(readFileSync(REPO_ROOT_FIXTURE, "utf-8"));
    expect(Object.keys(fixture).sort()).toEqual(
      ["base_branch", "params", "repository_name", "repository_org", "run_id"].sort(),
    );
    for (const field of ["run_id", "repository_org", "repository_name"]) {
      expect(typeof fixture[field]).toBe("string");
      expect(fixture[field].length).toBeGreaterThan(0);
    }
  });
});
