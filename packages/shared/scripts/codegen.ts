/**
 * Code generation script: Zod schemas → JSON Schema → Python dataclass module.
 *
 * Reads the TypeScript Zod schemas and generates:
 * 1. JSON Schema files under generated/schemas/
 * 2. A Python dataclass module under generated/shared_contract.py
 *
 * This is the single source of truth for the agent Python contract.
 * Run via: pnpm --filter shared run codegen
 */

import { z } from "zod";
import { writeFileSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { SubjectMetaItem, SubjectAgentItem, AgentConfigItem } from "../src/schemas.js";
import { PARAMS_SCHEMAS } from "../src/params-schemas.js";
import { LLIPE } from "../src/llipe.js";
import { SPAN_FIELDS } from "../src/span-fields.js";
import { DEFAULT_MAX_LIFETIME_MS, TERMINATION_GRACE_MS } from "../src/status.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const GENERATED_DIR = join(ROOT, "generated");
const SCHEMAS_DIR = join(GENERATED_DIR, "schemas");

// ──────────────────────────────────────────────────────
// Step 1: Generate JSON Schemas
// ──────────────────────────────────────────────────────

interface SchemaEntry {
  name: string;
  schema: z.ZodType;
}

const SCHEMAS: SchemaEntry[] = [
  { name: "SubjectMetaItem", schema: SubjectMetaItem },
  { name: "SubjectAgentItem", schema: SubjectAgentItem },
  { name: "AgentConfigItem", schema: AgentConfigItem },
];

const PARAM_ENTRIES = Object.entries(PARAMS_SCHEMAS);

function generateJsonSchemas(): Record<string, unknown> {
  mkdirSync(SCHEMAS_DIR, { recursive: true });

  const allSchemas: Record<string, unknown> = {};

  for (const { name, schema } of SCHEMAS) {
    const jsonSchema = z.toJSONSchema(schema);
    allSchemas[name] = jsonSchema;
    writeFileSync(join(SCHEMAS_DIR, `${name}.json`), JSON.stringify(jsonSchema, null, 2) + "\n");
  }

  for (const [agentName, schema] of PARAM_ENTRIES) {
    const jsonSchema = z.toJSONSchema(schema);
    const fileName = `Params_${agentName.replace(/-/g, "_")}`;
    allSchemas[fileName] = jsonSchema;
    writeFileSync(
      join(SCHEMAS_DIR, `${fileName}.json`),
      JSON.stringify(jsonSchema, null, 2) + "\n",
    );
  }

  return allSchemas;
}

// ──────────────────────────────────────────────────────
// Step 2: Generate Python module from JSON Schemas
// ──────────────────────────────────────────────────────

interface JsonSchemaProperty {
  type?: string;
  const?: string;
  default?: unknown;
  minimum?: number;
  maximum?: number;
}

interface JsonSchema {
  type: string;
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
  additionalProperties?: unknown;
}

function jsonTypeToPython(prop: JsonSchemaProperty): string {
  if (prop.const !== undefined) {
    return "str";
  }
  switch (prop.type) {
    case "string":
      return "str";
    case "boolean":
      return "bool";
    case "integer":
      return "int";
    case "number":
      return "float";
    case "object":
      return "dict[str, Any]";
    case "array":
      return "list[Any]";
    default:
      return "Any";
  }
}

function generatePythonClass(name: string, schema: JsonSchema): string {
  const lines: string[] = [];
  lines.push(`@dataclass(frozen=True)`);
  lines.push(`class ${name}:`);
  lines.push(`    """Generated from Zod schema. Do not edit manually."""`);
  lines.push("");

  const required = new Set(schema.required ?? []);
  const properties = schema.properties ?? {};

  // Required fields first
  const requiredFields: string[] = [];
  const optionalFields: string[] = [];

  for (const [fieldName, prop] of Object.entries(properties)) {
    const pyType = jsonTypeToPython(prop);
    if (required.has(fieldName) && prop.default === undefined) {
      requiredFields.push(`    ${fieldName}: ${pyType}`);
    } else if (prop.default !== undefined) {
      const defaultVal = JSON.stringify(prop.default);
      const pyDefault = defaultVal === "{}" ? "field(default_factory=dict)" : `${defaultVal}`;
      optionalFields.push(`    ${fieldName}: ${pyType} = ${pyDefault}`);
    } else {
      optionalFields.push(`    ${fieldName}: ${pyType} | None = None`);
    }
  }

  lines.push(...requiredFields);
  lines.push(...optionalFields);

  if (requiredFields.length === 0 && optionalFields.length === 0) {
    lines.push("    pass");
  }

  return lines.join("\n");
}

function generatePythonModule(schemas: Record<string, unknown>): string {
  const lines: string[] = [];

  lines.push(`"""
Generated shared contract module.
DO NOT EDIT — regenerate with: pnpm --filter shared run codegen

Source: packages/shared/src/ (TypeScript Zod schemas)
"""`);
  lines.push("");
  lines.push("from __future__ import annotations");
  lines.push("");
  lines.push("from dataclasses import dataclass, field");
  lines.push("from typing import Any");
  lines.push("");
  lines.push("");

  // Generate constants
  lines.push("# ─── LLIPE Span Attribute Constants ───────────────────────────────────────────");
  lines.push("");
  lines.push("class LLIPE:");
  lines.push('    """Span attribute name constants."""');
  lines.push("");
  for (const [key, value] of Object.entries(LLIPE)) {
    lines.push(`    ${key}: str = "${value}"`);
  }
  lines.push("");
  lines.push("");

  // Span fields
  lines.push("# ─── Span Field Paths ─────────────────────────────────────────────────────────");
  lines.push("");
  lines.push("class SPAN_FIELDS:");
  lines.push('    """Span field path mapping for Logs Insights queries."""');
  lines.push("");
  for (const [key, value] of Object.entries(SPAN_FIELDS)) {
    lines.push(`    ${key}: str = "${value}"`);
  }
  lines.push("");
  lines.push("");

  // Status constants
  lines.push("# ─── Status Derivation Constants ───────────────────────────────────────────────");
  lines.push("");
  lines.push(`DEFAULT_MAX_LIFETIME_MS: int = ${DEFAULT_MAX_LIFETIME_MS}`);
  lines.push(`TERMINATION_GRACE_MS: int = ${TERMINATION_GRACE_MS}`);
  lines.push("");
  lines.push("");

  // Generate dataclasses
  lines.push("# ─── DynamoDB Item Schemas ─────────────────────────────────────────────────────");
  lines.push("");

  for (const [name, schema] of Object.entries(schemas)) {
    if (name.startsWith("Params_")) continue; // Handle separately
    lines.push(generatePythonClass(name, schema as JsonSchema));
    lines.push("");
    lines.push("");
  }

  // Params schemas
  lines.push("# ─── Agent Params Schemas ──────────────────────────────────────────────────────");
  lines.push("");

  for (const [name, schema] of Object.entries(schemas)) {
    if (!name.startsWith("Params_")) continue;
    lines.push(generatePythonClass(name, schema as JsonSchema));
    lines.push("");
    lines.push("");
  }

  // Params registry
  lines.push("# ─── Params Schema Registry ───────────────────────────────────────────────────");
  lines.push("");
  lines.push("PARAMS_SCHEMAS: dict[str, type] = {");
  for (const [agentName] of PARAM_ENTRIES) {
    const className = `Params_${agentName.replace(/-/g, "_")}`;
    lines.push(`    "${agentName}": ${className},`);
  }
  lines.push("}");
  lines.push("");

  return lines.join("\n");
}

// ──────────────────────────────────────────────────────
// Main
// ──────────────────────────────────────────────────────

function main(): void {
  console.log("Generating JSON schemas...");
  const schemas = generateJsonSchemas();

  console.log("Generating Python module...");
  const pythonModule = generatePythonModule(schemas);
  writeFileSync(join(GENERATED_DIR, "shared_contract.py"), pythonModule);

  console.log(`Generated files in ${GENERATED_DIR}/`);
  console.log("  - schemas/*.json");
  console.log("  - shared_contract.py");
}

main();
