/**
 * Per-agent params validation schemas.
 * Each agent defines the params it accepts; unknown keys are rejected via .strict().
 */

import { z } from "zod";

/** dep-updater agent params: controls fix behavior */
const depUpdaterParams = z
  .object({
    allow_fixes: z.boolean(),
    max_fix_attempts: z.number().int().min(1).max(5),
  })
  .strict();

/** Registry of known agent param schemas */
export const PARAMS_SCHEMAS: Record<string, z.ZodObject<z.ZodRawShape>> = {
  "dep-updater": depUpdaterParams,
};

/** Empty strict schema for unknown agents — accepts {} and nothing else */
const EMPTY_STRICT = z.object({}).strict();

/**
 * Get the params schema for an agent.
 * Returns an empty strict object schema for unknown agents,
 * ensuring no unvalidated params reach DynamoDB.
 */
export function paramsSchemaFor(agentName: string): z.ZodObject<z.ZodRawShape> {
  return PARAMS_SCHEMAS[agentName] ?? EMPTY_STRICT;
}
