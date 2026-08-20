/**
 * Run filter parsing and validation — S-020.
 *
 * Pure functions to parse and validate URL search params for the runs tab.
 * Handles: tab, status, from/to date range, run (session_id).
 *
 * Rules:
 * - tab: "runs" (default) | "repos"
 * - status: optional, must be one of: "running" | "success" | "failed" | "incomplete"
 * - from: ISO date string, defaults to 7 days ago
 * - to: ISO date string, defaults to now
 * - Range max 30 days; if from > to: reset to defaults; if range > 30d: clamp from
 * - Invalid dates: fall back to defaults
 * - run: optional session_id string
 */

const VALID_TABS = ["runs", "repos"] as const;
export type TabValue = (typeof VALID_TABS)[number];

const VALID_STATUSES = ["running", "success", "failed", "incomplete"] as const;
export type StatusFilter = (typeof VALID_STATUSES)[number];

/** Maximum range in milliseconds (30 days) */
const MAX_RANGE_MS = 30 * 24 * 60 * 60 * 1000;

/** Default range in milliseconds (7 days) */
const DEFAULT_RANGE_MS = 7 * 24 * 60 * 60 * 1000;

export interface ParsedRunFilters {
  tab: TabValue;
  status: StatusFilter | undefined;
  from: Date;
  to: Date;
  run: string | undefined;
}

export interface RawSearchParams {
  tab?: string;
  status?: string;
  from?: string;
  to?: string;
  run?: string;
}

/**
 * Parse and validate URL search params into a typed filter object.
 *
 * Falls back to safe defaults on any invalid input.
 *
 * @param params - Raw search params from the URL
 * @param now - Current time in ms for testability (defaults to Date.now())
 */
export function parseRunFilters(params: RawSearchParams, now?: number): ParsedRunFilters {
  const currentTime = now ?? Date.now();

  const tab = parseTab(params.tab);
  const status = parseStatus(params.status);
  const run = params.run && params.run.trim().length > 0 ? params.run.trim() : undefined;
  const { from, to } = parseDateRange(params.from, params.to, currentTime);

  return { tab, status, from, to, run };
}

/**
 * Parse tab param. Falls back to "runs" for invalid values.
 */
export function parseTab(value: string | undefined): TabValue {
  if (value && (VALID_TABS as readonly string[]).includes(value)) {
    return value as TabValue;
  }
  return "runs";
}

/**
 * Parse status param. Returns undefined for invalid values (means "all").
 */
export function parseStatus(value: string | undefined): StatusFilter | undefined {
  if (value && (VALID_STATUSES as readonly string[]).includes(value)) {
    return value as StatusFilter;
  }
  return undefined;
}

/**
 * Parse and validate date range with clamping and fallback logic.
 *
 * Rules:
 * 1. Invalid dates → fall back to defaults (7d ago to now)
 * 2. from > to → fall back to defaults
 * 3. range > 30d → clamp from to (to - 30d)
 */
export function parseDateRange(
  fromStr: string | undefined,
  toStr: string | undefined,
  now: number,
): { from: Date; to: Date } {
  const defaultTo = new Date(now);
  const defaultFrom = new Date(now - DEFAULT_RANGE_MS);

  // Parse from
  const fromMs = fromStr ? Date.parse(fromStr) : NaN;
  const toMs = toStr ? Date.parse(toStr) : NaN;

  // If either date is invalid, fall back to defaults
  if (isNaN(fromMs) && isNaN(toMs)) {
    return { from: defaultFrom, to: defaultTo };
  }

  // If only 'to' is invalid, use now as 'to'
  const resolvedTo = isNaN(toMs) ? new Date(now) : new Date(toMs);

  // If only 'from' is invalid, use defaults
  if (isNaN(fromMs)) {
    return { from: new Date(resolvedTo.getTime() - DEFAULT_RANGE_MS), to: resolvedTo };
  }

  const resolvedFrom = new Date(fromMs);

  // from > to → fall back to defaults
  if (resolvedFrom.getTime() > resolvedTo.getTime()) {
    return { from: defaultFrom, to: defaultTo };
  }

  // range > 30d → clamp from to (to - 30d)
  const rangeMs = resolvedTo.getTime() - resolvedFrom.getTime();
  if (rangeMs > MAX_RANGE_MS) {
    return { from: new Date(resolvedTo.getTime() - MAX_RANGE_MS), to: resolvedTo };
  }

  return { from: resolvedFrom, to: resolvedTo };
}

/**
 * Format duration in milliseconds to human-readable string.
 *
 * Rules:
 * - 0 or unknown → "—"
 * - < 60s → "45s"
 * - < 3600s → "2m 30s"
 * - >= 3600s → "1h 5m"
 */
export function formatDuration(ms: number): string {
  if (!ms || ms <= 0) return "—";

  const totalSeconds = Math.floor(ms / 1000);

  if (totalSeconds < 60) {
    return `${totalSeconds}s`;
  }

  if (totalSeconds < 3600) {
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    if (seconds === 0) return `${minutes}m`;
    return `${minutes}m ${seconds}s`;
  }

  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  if (minutes === 0) return `${hours}h`;
  return `${hours}h ${minutes}m`;
}

/**
 * Format token counts as "X,XXX in / Y,YYY out".
 *
 * Rules:
 * - Zero total tokens → "—"
 * - Otherwise → comma-separated numbers with "in / out" labels
 */
export function formatTokens(tokensIn: number, tokensOut: number): string {
  if (tokensIn === 0 && tokensOut === 0) return "—";

  const formattedIn = tokensIn.toLocaleString("en-US");
  const formattedOut = tokensOut.toLocaleString("en-US");

  return `${formattedIn} in / ${formattedOut} out`;
}

/**
 * Serialize filters back to URL search params (only non-default values).
 */
export function filtersToSearchParams(
  filters: Omit<ParsedRunFilters, "run">,
  run?: string,
): Record<string, string> {
  const params: Record<string, string> = {};

  if (filters.tab !== "runs") {
    params["tab"] = filters.tab;
  }

  if (filters.status) {
    params["status"] = filters.status;
  }

  params["from"] = filters.from.toISOString();
  params["to"] = filters.to.toISOString();

  if (run) {
    params["run"] = run;
  }

  return params;
}
