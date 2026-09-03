/**
 * Data-formatting conventions from /DESIGN.md §7.
 *
 * Every function here is pure and, where time is involved, clock-injected
 * (`nowMs` is passed in, never read from `Date.now()` internally) so callers
 * control the instant and tests can assert exact boundaries. Timestamps accept
 * either epoch milliseconds or an ISO-8601 string; the caller parses
 * `timestamptz` strings once at the read boundary and may pass either form.
 *
 * §7.4 typography rule: these values render in the monospace stack (`--mono`)
 * at the call site — the formatter returns the string only.
 */

type TimeInput = number | string;

function toMs(input: TimeInput): number {
  return typeof input === "number" ? input : Date.parse(input);
}

function pad2(n: number): string {
  return n.toString().padStart(2, "0");
}

// ---------------------------------------------------------------------------
// §7.1 Timestamps
// ---------------------------------------------------------------------------

/**
 * 24-hour `HH:MM:SS` clock (log viewer + run metadata). Timezone-explicit so
 * server-rendered output is deterministic; defaults to UTC. Pass a valid IANA
 * zone (e.g. "America/Santiago") to render local wall-clock time.
 */
export function formatClock(input: TimeInput, timeZone = "UTC"): string {
  const d = new Date(toMs(input));
  const parts = new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone,
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "00";
  // Intl renders 24:xx:xx for midnight in some engines; normalize to 00.
  const hh = get("hour") === "24" ? "00" : get("hour");
  return `${hh}:${get("minute")}:${get("second")}`;
}

const SEC = 1000;
const MIN = 60 * SEC;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

/**
 * Relative time (run history + dashboard last-run): `just now`, `N min ago`,
 * `Nh ago`, `yesterday`, `Nd ago`. Future instants (clock skew) clamp to
 * `just now`.
 */
export function formatRelative(input: TimeInput, nowMs: number): string {
  const delta = nowMs - toMs(input);
  if (delta < MIN) return "just now";
  if (delta < HOUR) {
    const m = Math.floor(delta / MIN);
    return `${m} min ago`;
  }
  if (delta < DAY) {
    const h = Math.floor(delta / HOUR);
    return `${h}h ago`;
  }
  const d = Math.floor(delta / DAY);
  if (d === 1) return "yesterday";
  return `${d}d ago`;
}

// ---------------------------------------------------------------------------
// §7.2 Durations
// ---------------------------------------------------------------------------

function clampSeconds(ms: number): number {
  return Math.max(0, Math.floor(ms / SEC));
}

/** `Xm XXs` — run detail + run history (`3m 04s`). */
export function formatDuration(ms: number): string {
  const total = clampSeconds(ms);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}m ${pad2(s)}s`;
}

/** Short form — step list + history (`4s`, `1m 12s`). */
export function formatDurationShort(ms: number): string {
  const total = clampSeconds(ms);
  if (total < 60) return `${total}s`;
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}m ${pad2(s)}s`;
}

/** In-progress form — `running · Xm` (whole minutes, floored). */
export function formatRunningDuration(ms: number): string {
  const minutes = Math.max(0, Math.floor(ms / MIN));
  return `running · ${minutes}m`;
}

// ---------------------------------------------------------------------------
// §7.3 Counts and IDs
// ---------------------------------------------------------------------------

/**
 * Short ULID-style run ID — uppercase, dashes stripped, first 8 chars
 * (`01J8XQ2F`). Rendered in the monospace stack at the call site.
 */
export function formatRunId(id: string): string {
  return id.replace(/-/g, "").slice(0, 8).toUpperCase();
}

/** `N run` / `N runs` (singular/plural aware). */
export function formatRunCount(n: number): string {
  return `${n} ${n === 1 ? "run" : "runs"}`;
}

/** Step progress `n/m`. */
export function formatStepProgress(done: number, total: number): string {
  return `${done}/${total}`;
}

/** Event count `N ev`. */
export function formatEventCount(n: number): string {
  return `${n} ev`;
}

export interface StatusLegendCounts {
  ok: number;
  fail: number;
  timeout: number;
}

/** Status legend `65 ok · 11 fail · 6 timeout`; zero buckets are omitted. */
export function formatStatusLegend(counts: StatusLegendCounts): string {
  const parts: string[] = [];
  if (counts.ok > 0) parts.push(`${counts.ok} ok`);
  if (counts.fail > 0) parts.push(`${counts.fail} fail`);
  if (counts.timeout > 0) parts.push(`${counts.timeout} timeout`);
  return parts.join(" · ");
}

/** Compact glyph legend for cards `65 ✓ · 11 ✕ · 6 ⧗`; zero buckets omitted. */
export function formatStatusLegendCompact(counts: StatusLegendCounts): string {
  const parts: string[] = [];
  if (counts.ok > 0) parts.push(`${counts.ok} ✓`);
  if (counts.fail > 0) parts.push(`${counts.fail} ✕`);
  if (counts.timeout > 0) parts.push(`${counts.timeout} ⧗`);
  return parts.join(" · ");
}

/** Pagination `X of Y`. */
export function formatPagination(shown: number, total: number): string {
  return `${shown} of ${total}`;
}
