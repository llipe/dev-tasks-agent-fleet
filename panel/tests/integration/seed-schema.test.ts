import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
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
      .query<{
        params_schema: ParamsSchema;
      }>(`select params_schema from agents where slug = 'dependency-update'`)
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

// ---------------------------------------------------------------------------
// S-204 (#406) TC-204-15 — the `code-review` agents row, seeded by
// supabase/seed.sql and the `*_seed_code_review_agent.sql` data migration.
// Same Docker gate as above.
// ---------------------------------------------------------------------------

const MIGRATIONS_DIR = fileURLToPath(new URL("../../../supabase/migrations/", import.meta.url));

function codeReviewMigrationSql(): string {
  const found = readdirSync(MIGRATIONS_DIR).filter((f) =>
    f.endsWith("_seed_code_review_agent.sql"),
  );
  expect(found).toHaveLength(1);
  return readFileSync(`${MIGRATIONS_DIR}${found[0]}`, "utf8");
}

function migrationSchema(sql: string): unknown {
  const match = /\$json\$([\s\S]*?)\$json\$/.exec(sql);
  expect(match).not.toBeNull();
  return JSON.parse(match![1]);
}

describe.skipIf(!probe.available)("panel Layer 2.5 — seeded code-review agent (S-204)", () => {
  it("returns the spec §5.1 params_schema and its defaults", async () => {
    const row = await withDb((c) =>
      c
        .query<{
          params_schema: ParamsSchema;
          default_params: Record<string, unknown>;
        }>(`select params_schema, default_params from agents where slug = 'code-review'`)
        .then((r) => r.rows[0]),
    );
    expect(row).toBeDefined();
    expect(row.params_schema).toEqual(migrationSchema(codeReviewMigrationSql()));
    expect(row.params_schema.required).toEqual(["pr_number"]);
    expect(row.default_params).toEqual({
      max_diff_lines: 2000,
      max_context_tokens: 150000,
      max_suggestions: 5,
      run_timeout_seconds: 900,
      reasoning_effort: "high",
    });
  });

  it("applying the migration twice leaves exactly one row", async () => {
    const sql = codeReviewMigrationSql();
    const count = await withDb(async (c) => {
      await c.query(sql);
      await c.query(sql);
      const r = await c.query<{ n: string }>(
        `select count(*)::text as n from agents where slug = 'code-review'`,
      );
      return Number(r.rows[0].n);
    });
    expect(count).toBe(1);
  });
});
