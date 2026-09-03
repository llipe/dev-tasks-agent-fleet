import { readdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Mechanical token-discipline check (AC2 / /DESIGN.md §11.1, task 2.10 / G4).
 *
 * DESIGN.md §11.1 mandates that tokens are the source of truth: no component
 * or global stylesheet may hardcode a color hex or a font-family literal —
 * every such value MUST reference a custom property from tokens.css. This test
 * makes that rule a gate rather than a review judgment, so it holds as Wave 3's
 * screens (far more than twelve files) land.
 *
 * SCOPE — what is mechanized here, and the honest limits (G4: "land a rule, not
 * a judgment, and record anything genuinely not mechanizable"):
 *
 *   ENFORCED (fully mechanical, zero tolerance):
 *     1. No color hex literal (`#rgb`/`#rrggbb`/`#rrggbbaa`) anywhere under
 *        components/** or styles/globals.css.
 *     2. No `font-family:` literal — font stacks come only from --font-*.
 *
 *   NOT MECHANIZED (recorded, not silently dropped):
 *     - "Bare px in spacing properties" is intentionally NOT rejected. The
 *       Nocturne prototype specifies exact pixel DIMENSIONS that are not part
 *       of the 6-step §2.7 spacing scale — grid track sizes (LogLine's
 *       `82px 46px 108px`), dot/knob diameters, control min-heights, 1–3px
 *       radii. A blanket "no px" rule would reject faithful reproduction of the
 *       visual contract and produce false positives that erode the gate. The
 *       spacing SCALE itself is tokenized (--space-1..8) and used for padding/
 *       gap where a scale step applies; dimensional px that the design fixes
 *       exactly are allowed. This boundary is a review point, documented in
 *       panel/README.md, not a mechanical assertion.
 *
 * tokens.css is the single exempt file — it is the one intentional home of the
 * literal values every other file references.
 */

const panelRoot = fileURLToPath(new URL("../..", import.meta.url));

const EXEMPT = new Set([join(panelRoot, "styles", "tokens.css")]);

function collectStyleSources(): string[] {
  const files: string[] = [];

  // All CSS (incl. CSS modules) under components/**
  const componentsDir = join(panelRoot, "components");
  walk(componentsDir, (p) => {
    if (p.endsWith(".css") || p.endsWith(".tsx") || p.endsWith(".ts")) files.push(p);
  });

  // Global stylesheet (tokens.css is exempt and handled below)
  files.push(join(panelRoot, "styles", "globals.css"));

  return files.filter((f) => !EXEMPT.has(f));
}

function walk(dir: string, onFile: (path: string) => void): void {
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return;
  }
  for (const entry of entries) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, onFile);
    else onFile(full);
  }
}

// A color hex literal: # followed by 3, 4, 6, or 8 hex digits, not part of a
// longer word. Matches #fff, #161826, #e9e9ed80.
const HEX = /#[0-9a-fA-F]{3,8}\b/;
const FONT_FAMILY_LITERAL = /font-family:\s*(?!var\()\S/;

describe("token discipline (AC2 / DESIGN §11.1)", () => {
  const files = collectStyleSources();

  it("scans at least the twelve component modules plus globals", () => {
    // Guard against a broken glob silently making this test vacuous.
    const cssModules = files.filter((f) => f.endsWith(".module.css"));
    expect(cssModules.length).toBeGreaterThanOrEqual(12);
  });

  it.each(collectStyleSources().map((f) => [f.replace(panelRoot, ""), f] as const))(
    "%s contains no hardcoded color hex",
    (_label, file) => {
      const content = readFileSync(file, "utf8");
      const offending = content
        .split("\n")
        .map((line, i) => [i + 1, line] as const)
        .filter(([, line]) => HEX.test(line));
      expect(offending, `hex literal(s) in ${file}: ${JSON.stringify(offending)}`).toHaveLength(0);
    },
  );

  it.each(collectStyleSources().map((f) => [f.replace(panelRoot, ""), f] as const))(
    "%s uses no font-family literal (only var(--font-*))",
    (_label, file) => {
      const content = readFileSync(file, "utf8");
      const offending = content
        .split("\n")
        .map((line, i) => [i + 1, line] as const)
        .filter(([, line]) => FONT_FAMILY_LITERAL.test(line));
      expect(
        offending,
        `font-family literal(s) in ${file}: ${JSON.stringify(offending)}`,
      ).toHaveLength(0);
    },
  );
});
