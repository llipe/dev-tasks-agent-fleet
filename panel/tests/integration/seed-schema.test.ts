import { beforeAll, describe, expect, it } from "vitest";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 harness for the seeded params_schema (S-103 / issue #116). Confirms
// the dependency-update agent's params_schema — rendered verbatim by the
// schema-driven invoke form (D2 / S-113) — carries English operator-facing
// labels and no leftover non-ASCII prose, while its STRUCTURE is unchanged.
//
// Reads the REAL seeded row on the live local Postgres (never mocked —
// TESTING.md Layer 2.5 boundary). Docker-gated: skips with a recorded reason
// when the stack is down.

const probe = await probeLocalDb();

interface SchemaProp {
  type: string;
  title?: string;
  description?: string;
  enum?: string[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
}
interface ParamsSchema {
  type: string;
  additionalProperties: boolean;
  required: string[];
  properties: Record<string, SchemaProp>;
}

const NON_ASCII = /[^\x00-\x7F]/;

async function readParamsSchema(): Promise<ParamsSchema> {
  return withDb((c) =>
    c
      .query<{ params_schema: ParamsSchema }>(
        `select params_schema from agents where slug = 'dependency-update'`,
      )
      .then((r) => r.rows[0]?.params_schema),
  );
}

describe.skipIf(!probe.available)("panel Layer 2.5 — seeded params_schema (English)", () => {
  let schema: ParamsSchema;

  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    schema = await readParamsSchema();
  });

  it("has the expected top-level structure (unchanged by S-103)", () => {
    expect(schema).toBeDefined();
    expect(schema.type).toBe("object");
    expect(schema.additionalProperties).toBe(false);
    expect(schema.required).toEqual(["fix_mode"]);
    expect(Object.keys(schema.properties).sort()).toEqual([
      "base_branch",
      "fail_on_findings",
      "fix_mode",
      "max_fix_attempts",
    ]);
  });

  it("carries an English title for all four properties", () => {
    const titles = {
      fix_mode: "Fix mode",
      fail_on_findings: "Fail if findings exist",
      max_fix_attempts: "Max LLM agent attempts",
      base_branch: "PR base branch",
    };
    for (const [key, expected] of Object.entries(titles)) {
      expect(schema.properties[key]?.title, `title for ${key}`).toBe(expected);
    }
  });

  it("has no non-ASCII prose anywhere in the schema", () => {
    // The whole serialized schema (titles + descriptions + keys) must be ASCII.
    const serialized = JSON.stringify(schema);
    const offending = serialized.match(NON_ASCII);
    expect(offending, `non-ASCII char found: ${offending?.[0]}`).toBeNull();
  });

  it("preserves the constraint structure of each property", () => {
    // enums / ranges / defaults are the machine contract — must survive the
    // label translation untouched.
    expect(schema.properties.fix_mode.enum).toEqual(["audit_only", "llm_fix"]);
    expect(schema.properties.fix_mode.default).toBe("audit_only");
    expect(schema.properties.fail_on_findings.type).toBe("boolean");
    expect(schema.properties.fail_on_findings.default).toBe(true);
    expect(schema.properties.max_fix_attempts.minimum).toBe(0);
    expect(schema.properties.max_fix_attempts.maximum).toBe(5);
    expect(schema.properties.max_fix_attempts.default).toBe(3);
    expect(schema.properties.base_branch.default).toBe("main");
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — seeded params_schema (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
