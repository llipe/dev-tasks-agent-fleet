/**
 * Import boundary checker.
 *
 * Rules:
 * - apps/ must not import from agents/
 * - agents/ must not import from apps/
 * - packages/shared must not import from apps/ or agents/
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const ROOT = resolve(import.meta.dirname, "..");

interface Violation {
  file: string;
  line: number;
  importPath: string;
  rule: string;
}

const RULES: Array<{
  sourcePrefix: string;
  forbiddenPatterns: string[];
  description: string;
}> = [
  {
    sourcePrefix: "apps/",
    forbiddenPatterns: ["agents/", "@fleet/dep-updater"],
    description: "apps/ must not import from agents/",
  },
  {
    sourcePrefix: "agents/",
    forbiddenPatterns: ["apps/", "@fleet/control-plane"],
    description: "agents/ must not import from apps/",
  },
  {
    sourcePrefix: "packages/shared",
    forbiddenPatterns: [
      "apps/",
      "agents/",
      "@fleet/control-plane",
      "@fleet/dep-updater",
      "@fleet/infra",
    ],
    description: "packages/shared must not import from apps/ or agents/",
  },
];

function collectTsFiles(dir: string): string[] {
  const files: string[] = [];
  const entries = readdirSync(dir, { withFileTypes: true });

  for (const entry of entries) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === "dist" || entry.name === ".next") {
        continue;
      }
      files.push(...collectTsFiles(fullPath));
    } else if (/\.(ts|tsx|js|jsx|mts|mjs)$/.test(entry.name)) {
      files.push(fullPath);
    }
  }

  return files;
}

function checkFile(filePath: string): Violation[] {
  const violations: Violation[] = [];
  const relPath = relative(ROOT, filePath);
  const content = readFileSync(filePath, "utf-8");
  const lines = content.split("\n");

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    // Match import/require statements
    const importMatch = line.match(
      /(?:import|export)\s+.*?from\s+['"](.*?)['"]|require\s*\(\s*['"](.*?)['"]\s*\)/,
    );
    if (!importMatch) continue;

    const importPath = importMatch[1] ?? importMatch[2] ?? "";

    for (const rule of RULES) {
      if (!relPath.startsWith(rule.sourcePrefix)) continue;

      for (const forbidden of rule.forbiddenPatterns) {
        // For bare path prefixes (like "agents/"), match only at the start of the import
        // to avoid false positives with path aliases like "@/app/agents/..."
        if (forbidden.endsWith("/")) {
          if (
            importPath.startsWith(forbidden) ||
            importPath.startsWith(`./${forbidden}`) ||
            importPath.startsWith(`../${forbidden}`)
          ) {
            violations.push({
              file: relPath,
              line: i + 1,
              importPath,
              rule: rule.description,
            });
          }
        } else if (importPath === forbidden || importPath.startsWith(`${forbidden}/`)) {
          violations.push({
            file: relPath,
            line: i + 1,
            importPath,
            rule: rule.description,
          });
        }
      }
    }
  }

  return violations;
}

function main(): void {
  const dirsToCheck = ["apps", "agents", "packages/shared"].map((d) => join(ROOT, d));
  const allFiles: string[] = [];

  for (const dir of dirsToCheck) {
    try {
      statSync(dir);
      allFiles.push(...collectTsFiles(dir));
    } catch {
      // Directory may not exist yet
    }
  }

  const allViolations: Violation[] = [];
  for (const file of allFiles) {
    allViolations.push(...checkFile(file));
  }

  if (allViolations.length > 0) {
    console.error("\n Import boundary violations found:\n");
    for (const v of allViolations) {
      console.error(`  ${v.file}:${v.line}`);
      console.error(`    import: ${v.importPath}`);
      console.error(`    rule:   ${v.rule}\n`);
    }
    console.error(`\n ${allViolations.length} violation(s) found.\n`);
    process.exit(1);
  }

  console.log(" Import boundary check passed.");
}

main();
