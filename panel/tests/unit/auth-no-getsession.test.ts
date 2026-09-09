import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * AC8 grep guard (spec §12).
 *
 * `getSession()` returns a user object that is NOT re-validated against the
 * Supabase Auth server — it is read straight from the (client-writable) cookie,
 * so it is spoofable. It MUST NOT drive any authorization decision. Only
 * `getClaims()` (which verifies the JWT) may. This is a grep, not a judgment, so
 * it holds the line for every future change: if someone wires `getSession()`
 * into the gate or any authorization path, this test goes red in CI.
 *
 * Scope: the authorization surface — the middleware gate and its cookie-threading
 * client, plus every `lib/auth/**` module. If a later story adds a server-side
 * authorization helper, add its path here.
 */

const AUTHZ_FILES = ["middleware.ts", join("lib", "supabase", "auth-middleware.ts")];

const AUTHZ_DIRS = [join("lib", "auth")];

const EXTS = new Set([".ts", ".tsx"]);
// Match an actual CALL — `.getSession(` — not the word appearing in prose that
// explains why it is banned. A real authorization path would invoke it as
// `supabase.auth.getSession(...)`; the docstrings that name the ban must not
// trip the guard, or the guard would pressure authors to stop documenting it.
const BANNED = /\.\s*getSession\s*\(/;

function walk(dir: string): string[] {
  const out: string[] = [];
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return out;
  }
  for (const entry of entries) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...walk(full));
    } else if (EXTS.has(full.slice(full.lastIndexOf(".")))) {
      out.push(full);
    }
  }
  return out;
}

describe("no authorization path calls getSession() (AC8)", () => {
  const root = process.cwd();
  const files = [
    ...AUTHZ_FILES.map((f) => join(root, f)),
    ...AUTHZ_DIRS.flatMap((d) => walk(join(root, d))),
  ];

  it("scans the middleware gate and the auth modules (vacuity guard)", () => {
    // The gate + client + at least route-policy/redirect/errors must be present.
    expect(files.length).toBeGreaterThanOrEqual(4);
  });

  it("the guard pattern actually detects a getSession() call (falsifiability)", () => {
    // If this ever stopped matching a real call, the guard below would be
    // vacuously green. Prove it bites.
    expect(BANNED.test("const { data } = await supabase.auth.getSession();")).toBe(true);
    expect(BANNED.test("supabase.auth . getSession ( )")).toBe(true);
    // ...and does NOT bite prose that merely names it.
    expect(BANNED.test(" * Verify identity with getClaims(), NEVER getSession().")).toBe(false);
  });

  it("finds no getSession() usage anywhere in the authorization surface", () => {
    const offenders: string[] = [];
    for (const file of files) {
      let contents: string;
      try {
        contents = readFileSync(file, "utf8");
      } catch {
        continue;
      }
      contents.split("\n").forEach((line, i) => {
        if (BANNED.test(line)) {
          offenders.push(`${file}:${i + 1}: ${line.trim()}`);
        }
      });
    }
    expect(offenders, offenders.join("\n")).toEqual([]);
  });
});
