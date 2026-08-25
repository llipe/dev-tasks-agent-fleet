export interface RelativeTimeProps {
  /** ISO 8601 date-time string */
  dateTime: string;
  className?: string;
}

/**
 * Compute a human-readable relative time string.
 */
function formatRelative(dateTime: string): string {
  const now = Date.now();
  const then = new Date(dateTime).getTime();
  const diffMs = now - then;
  const diffSeconds = Math.floor(diffMs / 1000);

  if (diffSeconds < 60) {
    return "just now";
  }

  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) {
    return diffMinutes === 1 ? "1 min ago" : `${diffMinutes} min ago`;
  }

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) {
    return diffHours === 1 ? "1 hour ago" : `${diffHours} hours ago`;
  }

  const diffDays = Math.floor(diffHours / 24);
  return diffDays === 1 ? "1 day ago" : `${diffDays} days ago`;
}

/**
 * Format absolute UTC for the title tooltip.
 */
function formatAbsoluteUTC(dateTime: string): string {
  const date = new Date(dateTime);
  return `${date
    .toISOString()
    .replace("T", " ")
    .replace(/\.\d{3}Z$/, "")} UTC`;
}

/**
 * Renders a <time> element with relative text and absolute UTC in the title attribute.
 */
export function RelativeTime({ dateTime, className }: RelativeTimeProps) {
  return (
    <time dateTime={dateTime} title={formatAbsoluteUTC(dateTime)} className={className}>
      {formatRelative(dateTime)}
    </time>
  );
}
