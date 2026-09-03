import type { RunStatus } from "@/lib/domain/status";

/**
 * Shared status → presentation metadata for StatusDot and StatusPill, so the
 * two primitives never disagree on label, color token, dot style, or whether
 * the status pulses. /DESIGN.md §8.1 (status → visual mapping) and §2.4/SD10
 * (the four app-level status colors) are the source of truth.
 *
 * `label` is the accessible text that MUST accompany every status indicator —
 * meaning is conveyed by text, never by color alone (AC5 / §12 Do).
 * `colorVar` is a CSS custom property reference (never a literal), consumed via
 * an inline `--st-color` custom property the CSS then reads, so the twelve
 * status colors stay tokenized.
 */
export interface StatusMeta {
  label: string;
  /** token reference used to drive the dot/pill color */
  colorVar: string;
  /** true → animate the dot with the pulse keyframe (running/queued) */
  pulse: boolean;
  /** true → hollow dot (border only), used for failed_to_start */
  hollow: boolean;
}

const META: Record<string, StatusMeta> = {
  running: { label: "running", colorVar: "var(--color-accent)", pulse: true, hollow: false },
  queued: { label: "queued", colorVar: "var(--color-accent)", pulse: true, hollow: false },
  succeeded: { label: "succeeded", colorVar: "var(--st-ok)", pulse: false, hollow: false },
  failed: { label: "failed", colorVar: "var(--st-fail)", pulse: false, hollow: false },
  timed_out: { label: "timed out", colorVar: "var(--st-timeout)", pulse: false, hollow: false },
  failed_to_start: {
    label: "failed to start",
    colorVar: "var(--faint)",
    pulse: false,
    hollow: true,
  },
  canceled: { label: "canceled", colorVar: "var(--muted)", pulse: false, hollow: false },
};

/**
 * Neutral fallback for any unknown status value (EC: a schema that runs ahead
 * of a panel deploy adds an eighth enum value). Renders without crashing and
 * shows the raw value as its own label so it is never silently swallowed.
 */
export function statusMeta(status: RunStatus | (string & {})): StatusMeta {
  return (
    META[status] ?? {
      label: String(status),
      colorVar: "var(--muted)",
      pulse: false,
      hollow: false,
    }
  );
}
