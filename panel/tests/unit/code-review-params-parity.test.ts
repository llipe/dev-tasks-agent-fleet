import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it } from "vitest";
import { __resetValidatorCacheForTests } from "@/lib/schema/ajv";
import { validateParams } from "@/lib/schema/validate";

/**
 * S-204 (#406) — CT-01, panel side: `params_schema` vs runtime validation
 * parity for the `code-review` agent.
 *
 * One shared case file (owned by the agent package) is evaluated here by the
 * panel's Ajv `validateParams`, on the schema parsed from the seed and from the
 * data migration, and by the Python runtime validator in
 * `agents/code-review/app/codeReview/tests/unit/test_payload.py`. Both sides
 * must reach the same verdict for every case.
 */

const repoRoot = fileURLToPath(new URL("../../../", import.meta.url));
const CASES_PATH = `${repoRoot}agents/code-review/app/codeReview/tests/fixtures/params_cases.json`;
const SEED_PATH = `${repoRoot}supabase/seed.sql`;
const MIGRATIONS_DIR = `${repoRoot}supabase/migrations`;

interface ParamsCase {
  id: string;
  valid: boolean;
  absent?: boolean;
  params?: unknown;
}

/** The dollar-quoted `params_schema` of the `code-review` insert in `sql`. */
function codeReviewSchema(sql: string, source: string): Record<string, unknown> {
  const slugAt = sql.indexOf("'code-review',");
  expect(slugAt, `${source}: no 'code-review' row`).toBeGreaterThanOrEqual(0);
  const match = /\$json\$([\s\S]*?)\$json\$/.exec(sql.slice(slugAt));
  expect(match, `${source}: no $json$ params_schema after the code-review slug`).not.toBeNull();
  return JSON.parse(match![1]) as Record<string, unknown>;
}

function migrationPath(): string {
  const found = readdirSync(MIGRATIONS_DIR).filter((f) =>
    f.endsWith("_seed_code_review_agent.sql"),
  );
  expect(found).toHaveLength(1);
  return `${MIGRATIONS_DIR}/${found[0]}`;
}

const cases = (JSON.parse(readFileSync(CASES_PATH, "utf8")) as { cases: ParamsCase[] }).cases;

const sources: Array<[string, () => Record<string, unknown>]> = [
  ["seed.sql", () => codeReviewSchema(readFileSync(SEED_PATH, "utf8"), "seed.sql")],
  ["migration", () => codeReviewSchema(readFileSync(migrationPath(), "utf8"), "migration")],
];

beforeEach(() => __resetValidatorCacheForTests());

describe("CT-01 — code-review params parity (panel Ajv side)", () => {
  it("the shared case file has a meaningful spread", () => {
    expect(cases.length).toBeGreaterThanOrEqual(40);
    expect(cases.some((c) => c.valid)).toBe(true);
    expect(cases.some((c) => !c.valid)).toBe(true);
    expect(new Set(cases.map((c) => c.id)).size).toBe(cases.length);
  });

  it("seed and migration carry the same params_schema", () => {
    expect(sources[0][1]()).toEqual(sources[1][1]());
  });

  for (const [source, load] of sources) {
    describe(source, () => {
      for (const c of cases) {
        it(`${c.id} -> ${c.valid ? "accept" : "reject"}`, () => {
          const input = c.absent ? undefined : c.params;
          const result = validateParams("code-review", load(), input);
          expect(result.valid).toBe(c.valid);
        });
      }
    });
  }

  it("Ajv rejects a boolean for an integer field (Python must too)", () => {
    const schema = sources[0][1]();
    expect(validateParams("code-review", schema, { pr_number: true }).valid).toBe(false);
    expect(
      validateParams("code-review", schema, { pr_number: 1, max_suggestions: false }).valid,
    ).toBe(false);
  });
});
