/**
 * Safety assertion: no action ever touches last_* attributes — S-022, sub-task 22.10.
 *
 * This test statically greps the scope actions source to ensure no last_* attribute
 * is referenced in any update/write operation.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { resolve } from "path";

describe("scope actions safety (22.10)", () => {
  const scopeSource = readFileSync(resolve(import.meta.dirname, "./scope.ts"), "utf-8");

  it("does not contain any last_* attribute writes", () => {
    // Check for UpdateExpression or attribute names containing last_
    const lastAttrPatterns = [
      /last_status/,
      /last_run_at/,
      /last_session_id/,
      /last_outcome_url/,
      /lastStatus.*=/,
      /lastRunAt.*=/,
      /lastSessionId.*=/,
      /lastOutcomeUrl.*=/,
    ];

    for (const pattern of lastAttrPatterns) {
      expect(scopeSource).not.toMatch(pattern);
    }
  });

  it("does not call repository setSubjectEnabled with last_* params", () => {
    // The function signature in scope.ts calls repoSetEnabled(subjectId, agentName, enabled)
    // Verify no additional params are passed
    const setEnabledCalls = scopeSource.match(/repoSetEnabled\([^)]+\)/g) ?? [];
    for (const call of setEnabledCalls) {
      expect(call).not.toContain("last");
    }
  });

  it("does not call repository setSubjectParams with last_* params", () => {
    const setParamsCalls = scopeSource.match(/repoSetParams\([^)]+\)/g) ?? [];
    for (const call of setParamsCalls) {
      expect(call).not.toContain("last");
    }
  });

  it("does not call repository addSubject with last_* params", () => {
    const addCalls = scopeSource.match(/repoAddSubject\([^)]+\)/g) ?? [];
    for (const call of addCalls) {
      expect(call).not.toContain("last");
    }
  });

  it("only writes enabled or params attributes (never last_*)", () => {
    // The scope actions source should only reference enabled and params for writes
    // Any line with "UpdateExpression" or "SET" should not contain last_
    const lines = scopeSource.split("\n");
    const writeLines = lines.filter((l) => l.includes("UpdateExpression") || l.includes("SET "));
    for (const line of writeLines) {
      expect(line).not.toContain("last_");
    }
  });
});
