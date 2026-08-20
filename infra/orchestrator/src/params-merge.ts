/**
 * Params merge: global CONFIG defaults + subject-level params.
 * Subject-level params win on conflict.
 */

/**
 * Merge global default params with subject-level overrides.
 * Subject params take precedence over global defaults.
 */
export function mergeParams(
  globalDefaults: Record<string, unknown>,
  subjectParams: Record<string, unknown>,
): Record<string, unknown> {
  return { ...globalDefaults, ...subjectParams };
}
