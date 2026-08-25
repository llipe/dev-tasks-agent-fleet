import { describe, it, expect } from "vitest";
import { mergeParams } from "../src/params-merge.js";

describe("mergeParams", () => {
  it("returns global defaults when subject has no overrides", () => {
    const global = { allow_fixes: true, max_fix_attempts: 3 };
    const subject = {};
    expect(mergeParams(global, subject)).toEqual({ allow_fixes: true, max_fix_attempts: 3 });
  });

  it("subject params override global defaults on conflict", () => {
    const global = { allow_fixes: true, max_fix_attempts: 3 };
    const subject = { max_fix_attempts: 5 };
    expect(mergeParams(global, subject)).toEqual({ allow_fixes: true, max_fix_attempts: 5 });
  });

  it("subject-only params are included", () => {
    const global = { allow_fixes: true };
    const subject = { custom_key: "value" };
    expect(mergeParams(global, subject)).toEqual({ allow_fixes: true, custom_key: "value" });
  });

  it("returns empty when both are empty", () => {
    expect(mergeParams({}, {})).toEqual({});
  });

  it("subject completely overrides global when all keys conflict", () => {
    const global = { allow_fixes: true, max_fix_attempts: 3 };
    const subject = { allow_fixes: false, max_fix_attempts: 1 };
    expect(mergeParams(global, subject)).toEqual({ allow_fixes: false, max_fix_attempts: 1 });
  });
});
