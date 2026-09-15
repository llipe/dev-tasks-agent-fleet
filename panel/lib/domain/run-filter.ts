/**
 * Run History filter/pagination model (Story S-143, spec §8.1, FR1–FR6/FR8/FR13).
 *
 * A single pure module owns the URL <-> filter mapping so `/agents/[slug]` and
 * the future `/runs` screen (S-146) share one implementation. Both directions
 * are TOTAL: `parseRunFilter` never throws for any `URLSearchParams` (an
 * unknown/malformed value falls back to its default), and
 * `serializeRunFilter` omits default values so the URL stays clean
 * (`?status=all` is never written).
 *
 * Filter/pagination state lives in the URL query string only — never
 * `localStorage`, never bare component state (spec §8.1 Business Rule).
 */

import type { RunStatus } from "@/lib/domain/status";

/** The seven lifecycle values a run can be filtered to, plus "all" (no filter). */
export type RunFilterStatus = RunStatus | "all";

const KNOWN_STATUSES: readonly RunStatus[] = [
  "queued",
  "running",
  "succeeded",
  "failed",
  "timed_out",
  "failed_to_start",
  "canceled",
];

/** Segmented-control order, per PRD FR1 / DESIGN.md §5.2. */
export const STATUS_FILTER_ORDER: readonly RunFilterStatus[] = [
  "queued",
  "running",
  "succeeded",
  "failed",
  "timed_out",
  "failed_to_start",
  "all",
];

export interface RunFilter {
  /** segmented control, FR1 */
  status: RunFilterStatus;
  /** repo chip, FR2 */
  repositoryId: string | null;
  /** free text, FR3 */
  search: string | null;
  /** ONLY meaningful on /runs — null on /agents/[slug] (FR13) */
  agentSlug: string | null;
  /** 1-based, FR4/FR5 */
  page: number;
}

const DEFAULT_FILTER: RunFilter = {
  status: "all",
  repositoryId: null,
  search: null,
  agentSlug: null,
  page: 1,
};

function isKnownStatus(value: string): value is RunStatus {
  return (KNOWN_STATUSES as readonly string[]).includes(value);
}

/** A non-empty, trimmed-non-empty string param, else `null`. Never throws. */
function readNonEmpty(searchParams: URLSearchParams, key: string): string | null {
  const raw = searchParams.get(key);
  if (raw == null) return null;
  return raw.length > 0 ? raw : null;
}

/**
 * Parse a `RunFilter` from `URLSearchParams`. Total and never throws: any
 * unknown/malformed value degrades to its default rather than raising —
 * `status` falls back to `"all"`, `repositoryId`/`search`/`agentSlug` fall
 * back to `null`, `page` falls back to `1`.
 */
export function parseRunFilter(searchParams: URLSearchParams): RunFilter {
  const statusRaw = searchParams.get("status");
  const status: RunFilterStatus = statusRaw != null && isKnownStatus(statusRaw) ? statusRaw : "all";

  const repositoryId = readNonEmpty(searchParams, "repo");
  const search = readNonEmpty(searchParams, "q");
  const agentSlug = readNonEmpty(searchParams, "agent");

  let page = 1;
  const pageRaw = searchParams.get("page");
  if (pageRaw != null) {
    const parsed = Number.parseInt(pageRaw, 10);
    if (Number.isFinite(parsed) && parsed >= 1) {
      page = parsed;
    }
  }

  return { status, repositoryId, search, agentSlug, page };
}

/**
 * Serialize a `RunFilter` to `URLSearchParams`, omitting every field that is
 * already at its default value so the URL stays clean (`?status=all` is never
 * written, an unfiltered view is a bare path). A `search` that is empty or
 * whitespace-only serializes as absent, matching `parseRunFilter`'s own
 * normalization so a round trip is stable.
 */
export function serializeRunFilter(filter: RunFilter): URLSearchParams {
  const params = new URLSearchParams();
  if (filter.status !== DEFAULT_FILTER.status) {
    params.set("status", filter.status);
  }
  if (filter.repositoryId != null && filter.repositoryId !== "") {
    params.set("repo", filter.repositoryId);
  }
  if (filter.search != null && filter.search.trim() !== "") {
    params.set("q", filter.search);
  }
  if (filter.agentSlug != null && filter.agentSlug !== "") {
    params.set("agent", filter.agentSlug);
  }
  if (filter.page !== DEFAULT_FILTER.page) {
    params.set("page", String(filter.page));
  }
  return params;
}

/**
 * Escapes `%`, `_`, and the escape character (`\`) so a value can be
 * interpolated into a Postgres `ilike` pattern as a literal substring (spec
 * §8.1 v1.1 addendum, closes a `verifier` Design Mode gap). Without this, a
 * search for `my_repo` would match `my-repo`/`myXrepo`/etc. because `_` is a
 * single-character wildcard to `ilike` — this keeps search literal-substring
 * only, mirroring the existing dashboard `AgentFilter`'s EC-25 precedent (a
 * stray metacharacter matches literally, never throws) applied to `ilike`
 * instead of `String.includes`.
 *
 * The backslash MUST be escaped first — escaping `%`/`_` before the backslash
 * would double-escape the backslashes those steps just introduced.
 */
export function escapeIlikeWildcards(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/%/g, "\\%").replace(/_/g, "\\_");
}
