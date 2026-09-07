/**
 * Artifact URL scheme validation — mandatory security guard #5 (spec §12, A10).
 *
 * `run_artifacts.url` is written by the agent, so it is untrusted input. Before
 * the panel renders it as an `<a href>`, the scheme MUST be validated: only a
 * well-formed `https:` URL is safe to link. A `javascript:` or `data:` URL in
 * an `href` is a stored-XSS vector; an `http:` URL is a downgrade / mixed
 * content; a relative or empty value is not a resource the panel should link.
 * Everything that is not a well-formed `https:` URL renders as inert text.
 *
 * The function is pure and TOTAL: it returns a boolean for ANY input and never
 * throws (test-plan RT-1). The WHATWG `URL` parser does the heavy lifting —
 * it normalizes the scheme, so `HTTPS:` and `javascript:` with embedded tabs
 * are both classified correctly rather than by fragile string matching.
 */

export function isSafeArtifactUrl(url: string | null | undefined): boolean {
  if (typeof url !== "string") return false;
  const trimmed = url.trim();
  if (trimmed.length === 0) return false;

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    // Not an absolute URL (relative path, garbage, malformed host). Unsafe,
    // but never an error — the caller shows inert text.
    return false;
  }

  // `URL.protocol` is normalized to lowercase and includes the trailing colon
  // (e.g. "https:"). This is the only scheme we link.
  return parsed.protocol === "https:";
}
