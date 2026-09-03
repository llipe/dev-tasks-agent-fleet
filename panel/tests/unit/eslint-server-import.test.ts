import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

// Security-boundary test (S-104 / issue #117, CT-13 / EC-13, AC-104.1).
// The SD2 ESLint rule (panel/eslint.config.mjs, no-restricted-imports on
// **/lib/supabase/server, scoped to components/**) was added in S-101 and had
// never been observed firing. This proves it triggers: a fixture client
// component under components/ that imports @/lib/supabase/server must produce
// the SD2 lint error. It is the fast lint-time half of the guard; the hard
// guard is the `import "server-only"` pragma in lib/supabase/server.ts, which
// fails `next build` if the module ever reaches a client bundle.
//
// The fixtures are written under panel/components/ (so the scoped rule applies)
// and removed afterwards. They are linted with --no-ignore so a defensive
// .gitignore/eslint-ignore of the fixture dir does not neutralize the check.

const panelDir = join(__dirname, "..", "..");
const fixtureDir = join(panelDir, "components", "__sd2_fixture__");
const clientFixture = join(fixtureDir, "client-import.tsx");
const serverLibFixture = join(panelDir, "lib", "__sd2_fixture_server__.ts");

beforeAll(() => {
  mkdirSync(fixtureDir, { recursive: true });

  // A client component under components/ importing the server-only module —
  // the exact SD2 violation the rule must catch.
  writeFileSync(
    clientFixture,
    [
      '"use client";',
      'import { createServerClient } from "@/lib/supabase/server";',
      "export function Bad() {",
      "  createServerClient();",
      "  return null;",
      "}",
      "",
    ].join("\n"),
  );

  // A server-context module (under lib/, NOT components/) importing the same
  // thing — legitimate SD2 usage. The scoped lint rule must NOT flag it; the
  // `server-only` pragma is what guards this path at build time.
  writeFileSync(
    serverLibFixture,
    [
      'import { createServerClient } from "@/lib/supabase/server";',
      "export function ok() {",
      "  return createServerClient();",
      "}",
      "",
    ].join("\n"),
  );
});

afterAll(() => {
  rmSync(fixtureDir, { recursive: true, force: true });
  rmSync(serverLibFixture, { force: true });
});

interface EslintMessage {
  ruleId: string | null;
  message: string;
}
interface EslintFileResult {
  filePath: string;
  messages: EslintMessage[];
}

function lintJson(file: string): EslintFileResult[] {
  try {
    const out = execFileSync(
      "pnpm",
      ["exec", "eslint", "--no-ignore", "--format", "json", file],
      { cwd: panelDir, stdio: ["ignore", "pipe", "pipe"], encoding: "utf8" },
    );
    return JSON.parse(out) as EslintFileResult[];
  } catch (err) {
    // ESLint exits non-zero when it reports errors; the JSON is still on stdout.
    const e = err as { stdout?: string };
    if (e.stdout) return JSON.parse(e.stdout) as EslintFileResult[];
    throw err;
  }
}

describe("SD2 ESLint restricted-import rule", () => {
  it("fires no-restricted-imports when a client component imports lib/supabase/server", () => {
    const messages = lintJson(clientFixture).flatMap((r) => r.messages);
    const restricted = messages.filter((m) => m.ruleId === "no-restricted-imports");
    expect(
      restricted.length,
      `expected an SD2 restricted-import error, got: ${JSON.stringify(messages)}`,
    ).toBeGreaterThan(0);
    // The rule's custom message names SD2 so the failure is self-explanatory.
    expect(restricted.some((m) => m.message.includes("SD2"))).toBe(true);
  });

  it("does NOT flag a legitimate server-context module (guarded by server-only, not this rule)", () => {
    const restricted = lintJson(serverLibFixture)
      .flatMap((r) => r.messages)
      .filter((m) => m.ruleId === "no-restricted-imports");
    expect(
      restricted.length,
      "server-context import of lib/supabase/server must not trip the SD2 client-scoped rule",
    ).toBe(0);
  });
});
