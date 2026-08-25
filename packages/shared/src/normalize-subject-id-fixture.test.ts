/**
 * Fixture-driven test: validates normalizeSubjectId against shared fixture
 * for cross-language equivalence with Python (S-009 sub-task 9.8).
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { normalizeSubjectId } from "./normalize-subject-id.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const fixturesPath = join(__dirname, "..", "fixtures", "subject-ids.json");

interface FixtureCase {
  input: string;
  expected: string;
}

const fixtures: FixtureCase[] = JSON.parse(readFileSync(fixturesPath, "utf-8"));

describe("normalizeSubjectId (shared fixture)", () => {
  it.each(fixtures)("normalizes $input → $expected", ({ input, expected }) => {
    expect(normalizeSubjectId(input)).toBe(expected);
  });
});
