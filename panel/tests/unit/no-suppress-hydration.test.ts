import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Mechanical guard (test-plan G3).
 *
 * `suppressHydrationWarning` makes a hydration mismatch vanish permanently for
 * a whole subtree — the exact failure the G3 instrument exists to catch. It is
 * banned under `app/**` and `components/**` UNLESS the same line carries a
 * `// hydration-divergence:` comment naming the specific, legitimate cause
 * (e.g. a rendered timestamp). This is a grep, not a judgment, so it scales
 * across every Wave 3+ screen.
 */

const ROOTS = ["app", "components"];
const EXTS = new Set([".ts", ".tsx"]);
const ALLOW_MARKER = "hydration-divergence:";

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

describe("suppressHydrationWarning is banned without a naming comment (G3)", () => {
  const files = ROOTS.flatMap((r) => walk(join(process.cwd(), r)));

  it("scans a non-trivial number of source files (vacuity guard)", () => {
    expect(files.length).toBeGreaterThanOrEqual(10);
  });

  it("finds no unjustified suppressHydrationWarning", () => {
    const offenders: string[] = [];
    for (const file of files) {
      const lines = readFileSync(file, "utf8").split("\n");
      lines.forEach((line, i) => {
        if (line.includes("suppressHydrationWarning") && !line.includes(ALLOW_MARKER)) {
          offenders.push(`${file}:${i + 1}: ${line.trim()}`);
        }
      });
    }
    expect(offenders, offenders.join("\n")).toEqual([]);
  });
});
