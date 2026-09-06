/**
 * S-113 (#126) — `params_schema` → field-descriptor mapping (FR13, D2, SD8).
 *
 * SD8 rejects generic JSON-Schema form libraries: they fight `/DESIGN.md`'s
 * token system and pull in a large surface for a small need. The actual need is
 * four control kinds:
 *
 *     enum            -> select
 *     boolean         -> toggle
 *     integer/number  -> number   (carrying minimum/maximum when present)
 *     string          -> text
 *
 * Anything else — `oneOf`/`anyOf`/`allOf`, nested objects, arrays, or a property
 * with no recognizable type — maps to a `unsupported` descriptor rendered as a
 * DISABLED field with a visible note. A parameter never vanishes silently
 * (AC4): the operator always sees that the agent declared it, even when the
 * form cannot render an editor for it.
 *
 * Pure module — no React, no Ajv, no I/O. The form component (client) renders
 * these descriptors; the same shared Ajv (`lib/schema/ajv.ts`) validates the
 * collected values, so the client cannot be more lenient than the server.
 */

export type FieldControl = "select" | "toggle" | "number" | "text" | "unsupported";

export interface FieldDescriptor {
  /** The property key in `params_schema.properties`. */
  name: string;
  /** `title` if present, else the key name (AC — missing title falls back). */
  label: string;
  /** `description` help text, if any. */
  help?: string;
  control: FieldControl;
  required: boolean;
  /** The schema `default`, if any (propagated to the initial form value). */
  default?: unknown;
  /** For `select`: the enum options. */
  options?: unknown[];
  /** For `number`: inclusive bounds when the schema declares them. */
  min?: number;
  max?: number;
  /** For `unsupported`: disabled and carrying an explanatory note. */
  disabled?: boolean;
  note?: string;
}

interface JsonSchemaProperty {
  type?: string | string[];
  title?: string;
  description?: string;
  enum?: unknown[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
  // Composition / structural keywords we do NOT render (unsupported):
  oneOf?: unknown;
  anyOf?: unknown;
  allOf?: unknown;
  properties?: unknown;
  items?: unknown;
}

interface JsonSchemaObject {
  type?: string;
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
}

/** True when the property declares a composition/structural keyword we can't render. */
function isStructural(prop: JsonSchemaProperty): boolean {
  return (
    prop.oneOf !== undefined ||
    prop.anyOf !== undefined ||
    prop.allOf !== undefined ||
    prop.properties !== undefined ||
    prop.items !== undefined
  );
}

/** Normalizes `type` (which may be an array like `["string","null"]`) to a set. */
function typeSet(type: string | string[] | undefined): Set<string> {
  if (type === undefined) return new Set();
  return new Set(Array.isArray(type) ? type : [type]);
}

const UNSUPPORTED_NOTE =
  "Unsupported schema type — this parameter cannot be edited in the form. Edit it via the API.";

function mapProperty(name: string, prop: JsonSchemaProperty, required: boolean): FieldDescriptor {
  const label = prop.title && prop.title.trim() !== "" ? prop.title : name;
  const base: FieldDescriptor = {
    name,
    label,
    help: prop.description,
    control: "text",
    required,
    default: prop.default,
  };

  // Structural keywords are unsupported regardless of any declared `type`.
  if (isStructural(prop)) {
    return { ...base, control: "unsupported", disabled: true, note: UNSUPPORTED_NOTE };
  }

  // An enum is a select regardless of its base type (string/number enums).
  if (Array.isArray(prop.enum) && prop.enum.length > 0) {
    return { ...base, control: "select", options: prop.enum };
  }

  const types = typeSet(prop.type);

  if (types.has("boolean")) {
    return { ...base, control: "toggle" };
  }
  if (types.has("integer") || types.has("number")) {
    return {
      ...base,
      control: "number",
      min: typeof prop.minimum === "number" ? prop.minimum : undefined,
      max: typeof prop.maximum === "number" ? prop.maximum : undefined,
    };
  }
  if (types.has("string")) {
    return { ...base, control: "text" };
  }

  // No recognizable type (empty, null-only, or unknown) — never drop it.
  return { ...base, control: "unsupported", disabled: true, note: UNSUPPORTED_NOTE };
}

/**
 * Builds the ordered field-descriptor array from an agent's `params_schema`.
 * Property order is preserved (object key order). A schema without a
 * `properties` object yields `[]` (the empty-schema edge — the form renders no
 * fields and submission is still valid).
 */
export function buildFieldDescriptors(schema: unknown): FieldDescriptor[] {
  if (typeof schema !== "object" || schema === null) return [];
  const s = schema as JsonSchemaObject;
  if (typeof s.properties !== "object" || s.properties === null) return [];

  const requiredSet = new Set(Array.isArray(s.required) ? s.required : []);
  return Object.entries(s.properties).map(([name, prop]) =>
    mapProperty(name, prop, requiredSet.has(name)),
  );
}
