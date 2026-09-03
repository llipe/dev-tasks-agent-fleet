import styles from "./LogLine.module.css";

/**
 * LogLine — /DESIGN.md §3.6 + §7.5. A single log row rendered as a 4-column
 * grid (timestamp | level | step | message), monospace, with the message
 * `pre-wrap` and word-broken so it WRAPS and is NEVER truncated (§7.5 —
 * log content is never truncated). Presentational, server-safe.
 *
 * The level drives a color class so error/warn stand out; the mapping falls
 * back to the default (info) tint for any unknown level.
 */
export type LogLevel = "debug" | "info" | "warn" | "error" | (string & {});

export interface LogLineProps {
  /** already-formatted HH:MM:SS timestamp (see lib/format.formatClock) */
  timestamp: string;
  level: LogLevel;
  step?: string;
  message: string;
  className?: string;
}

const LEVEL_CLASS: Record<string, string> = {
  debug: "levelDebug",
  info: "levelInfo",
  warn: "levelWarn",
  error: "levelError",
};

export function LogLine({ timestamp, level, step, message, className }: LogLineProps) {
  const levelClass = styles[LEVEL_CLASS[level] ?? "levelInfo"];
  return (
    <div className={[styles.logline, className].filter(Boolean).join(" ")}>
      <span className={styles.time}>{timestamp}</span>
      <span className={[styles.level, levelClass].filter(Boolean).join(" ")}>{level}</span>
      <span className={styles.step}>{step}</span>
      <span className={styles.message}>{message}</span>
    </div>
  );
}
