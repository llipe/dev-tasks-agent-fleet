import { beforeEach, describe, expect, it } from "vitest";
import { __resetValidatorCacheForTests, getValidator, hashSchema } from "@/lib/schema/ajv";
import { validateParams } from "@/lib/schema/validate";
import { buildRunInsert, RunSnapshotError } from "@/lib/domain/run-insert";

/**
 * S-112 (#125) — Ajv params validation (security-negative #3) and the
 * queued-row snapshot builder (OQ3). Task 1.12 / 1.16 edge cases.
 */

const SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["fix_mode"],
  properties: {
    fix_mode: { type: "string", enum: ["audit_only", "llm_fix"], default: "audit_only" },
    fail_on_findings: { type: "boolean", default: true },
    max_fix_attempts: { type: "integer", minimum: 0, maximum: 5, default: 3 },
    base_branch: { type: "string", default: "main" },
  },
};

beforeEach(() => __resetValidatorCacheForTests());

describe("validateParams — accepts valid params", () => {
  it("accepts a schema-valid object and projects to schema-present keys", () => {
    const r = validateParams("a1", SCHEMA, {
      fix_mode: "llm_fix",
      max_fix_attempts: 5,
    });
    expect(r.valid).toBe(true);
    if (r.valid) {
      expect(r.params).toEqual({ fix_mode: "llm_fix", max_fix_attempts: 5 });
    }
  });

  it("max_fix_attempts at the inclusive bounds 0 and 5 pass; 6 fails", () => {
    expect(
      validateParams("a1", SCHEMA, { fix_mode: "audit_only", max_fix_attempts: 0 }).valid,
    ).toBe(true);
    expect(
      validateParams("a1", SCHEMA, { fix_mode: "audit_only", max_fix_attempts: 5 }).valid,
    ).toBe(true);
    expect(
      validateParams("a1", SCHEMA, { fix_mode: "audit_only", max_fix_attempts: 6 }).valid,
    ).toBe(false);
  });
});

describe("validateParams — rejects (security-negative #3)", () => {
  it("rejects an additional property", () => {
    const r = validateParams("a1", SCHEMA, { fix_mode: "audit_only", bogus: true });
    expect(r.valid).toBe(false);
    if (!r.valid) {
      expect(r.errors.some((e) => e.keyword === "additionalProperties")).toBe(true);
    }
  });

  it("rejects a missing required field", () => {
    const r = validateParams("a1", SCHEMA, {});
    expect(r.valid).toBe(false);
  });

  it("rejects a bad enum value", () => {
    const r = validateParams("a1", SCHEMA, { fix_mode: "nope" });
    expect(r.valid).toBe(false);
  });

  it("rejects a non-object params (null, array, scalar)", () => {
    expect(validateParams("a1", SCHEMA, null).valid).toBe(false);
    expect(validateParams("a1", SCHEMA, [1, 2]).valid).toBe(false);
    expect(validateParams("a1", SCHEMA, 42).valid).toBe(false);
  });
});

describe("validateParams — empty schema edge (task 1.16 / 2.17)", () => {
  it("an empty {} schema accepts an empty object and passes it through", () => {
    const r = validateParams("a1", {}, {});
    expect(r.valid).toBe(true);
    if (r.valid) expect(r.params).toEqual({});
  });
});

describe("getValidator — cache", () => {
  it("returns the same compiled validator for an unchanged (agent, schema)", () => {
    const v1 = getValidator("a1", SCHEMA);
    const v2 = getValidator("a1", SCHEMA);
    expect(v1).toBe(v2);
  });

  it("a changed schema yields a new validator (hash key)", () => {
    const v1 = getValidator("a1", SCHEMA);
    const other = { ...SCHEMA, required: [] };
    const v2 = getValidator("a1", other);
    expect(v1).not.toBe(v2);
    expect(hashSchema(SCHEMA)).not.toBe(hashSchema(other));
  });
});

describe("buildRunInsert — snapshot completeness (OQ3)", () => {
  const agent = {
    id: "agent-1",
    version: "0.1.0",
    max_runtime_seconds: 3600,
    grace_seconds: 120,
    start_timeout_seconds: 300,
  };

  it("copies all three timeout columns explicitly and sets triggered_by=panel", () => {
    const row = buildRunInsert({
      runId: "r-1",
      agent,
      repositoryId: "repo-1",
      installationId: "inst-1",
      params: { fix_mode: "audit_only" },
    });
    expect(row.max_runtime_seconds).toBe(3600);
    expect(row.grace_seconds).toBe(120);
    expect(row.start_timeout_seconds).toBe(300);
    expect(row.triggered_by).toBe("panel");
    expect(row.trigger_type).toBe("manual");
    expect(row.status).toBe("queued");
    expect(row.agent_version).toBe("0.1.0");
    expect(row.repository_id).toBe("repo-1");
    expect(row.installation_id).toBe("inst-1");
  });

  it("null repository_id / installation_id for a no-repository agent", () => {
    const row = buildRunInsert({
      runId: "r-1",
      agent,
      repositoryId: null,
      installationId: null,
      params: {},
    });
    expect(row.repository_id).toBeNull();
    expect(row.installation_id).toBeNull();
  });

  it("throws RunSnapshotError rather than write a row with a non-finite timeout", () => {
    expect(() =>
      buildRunInsert({
        runId: "r-1",
        agent: { ...agent, max_runtime_seconds: NaN },
        repositoryId: "repo-1",
        installationId: "inst-1",
        params: {},
      }),
    ).toThrow(RunSnapshotError);
  });
});
