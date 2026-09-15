/**
 * S-147 (#207) — the Repositories add-form input validator (spec §8.4, PRD
 * FR16). Pure module, no I/O, no ambient clock — fully unit-testable.
 *
 * `parseFullName` is a SHAPE check only. It never calls the GitHub API and
 * never verifies the repository actually exists — a deliberate, accepted
 * risk (PRD §8 Business Rule, spec §12): a repository that does not exist on
 * GitHub can still be added, and the resulting invocation against it fails
 * normally at the GitHub-App-auth or clone step, same as any other
 * misconfiguration.
 *
 * The shape matches GitHub's own owner/repo charset closely enough for a
 * manual reference: `/^[\w.-]+\/[\w.-]+$/` after trimming — exactly two
 * non-empty halves (word characters, dots, hyphens) separated by a single
 * "/". Case is preserved exactly; this validator never normalizes case (the
 * uniqueness constraint against an existing row is a DB/query concern, not
 * this module's).
 */

export const INVALID_REPOSITORY_FORMAT = "INVALID_REPOSITORY_FORMAT" as const;

export type ParseFullNameResult =
  | { ok: true; value: string }
  | { ok: false; code: typeof INVALID_REPOSITORY_FORMAT };

const FULL_NAME_RE = /^[\w.-]+\/[\w.-]+$/;

/**
 * Validates a raw `full_name` candidate. Trims before validating; on success
 * returns the trimmed value (never the raw, possibly-padded input). Never
 * throws for any input, including empty strings, multi-line strings, or
 * arbitrarily long strings.
 */
export function parseFullName(raw: string): ParseFullNameResult {
  const trimmed = raw.trim();
  if (!FULL_NAME_RE.test(trimmed)) {
    return { ok: false, code: INVALID_REPOSITORY_FORMAT };
  }
  return { ok: true, value: trimmed };
}
