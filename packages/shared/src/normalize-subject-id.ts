/**
 * Subject ID normalizer.
 *
 * Accepts multiple input forms and normalizes to `owner/repo` (lowercase).
 * Supported forms:
 * - bare: `owner/repo`
 * - HTTPS: `https://github.com/owner/repo[.git][/]`
 * - SSH: `git@github.com:owner/repo[.git]`
 * - with .git suffix or trailing slash
 */

/** SSH remote pattern: git@host:owner/repo[.git] */
const SSH_PATTERN = /^[\w.-]+@[\w.-]+:([\w.-]+\/[\w.-]+?)(?:\.git)?$/;

/** HTTPS URL pattern: https://host/owner/repo[.git][/] */
const HTTPS_PATTERN = /^https?:\/\/[^/]+\/([\w.-]+\/[\w.-]+?)(?:\.git)?\/?\s*$/;

/**
 * Normalize any supported subject ID format to `owner/repo` (lowercase).
 *
 * @param input - Raw subject identifier in any supported format
 * @returns Normalized `owner/repo` string
 */
export function normalizeSubjectId(input: string): string {
  const trimmed = input.trim();

  // Try SSH format first
  const sshMatch = SSH_PATTERN.exec(trimmed);
  if (sshMatch?.[1]) {
    return sshMatch[1].toLowerCase();
  }

  // Try HTTPS format
  const httpsMatch = HTTPS_PATTERN.exec(trimmed);
  if (httpsMatch?.[1]) {
    return httpsMatch[1].toLowerCase();
  }

  // Bare format: strip .git suffix and trailing slash, then lowercase
  let result = trimmed;
  if (result.endsWith("/")) {
    result = result.slice(0, -1);
  }
  if (result.endsWith(".git")) {
    result = result.slice(0, -4);
  }

  return result.toLowerCase();
}
