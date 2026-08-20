import { cn } from "@/lib/utils/cn";

export type Status = "success" | "running" | "failed" | "incomplete";

const statusConfig: Record<Status, { label: string; bg: string; fg: string }> = {
  success: {
    label: "Success",
    bg: "bg-status-success-bg",
    fg: "text-status-success-fg",
  },
  running: {
    label: "Running",
    bg: "bg-status-running-bg",
    fg: "text-status-running-fg",
  },
  failed: {
    label: "Failed",
    bg: "bg-status-failed-bg",
    fg: "text-status-failed-fg",
  },
  incomplete: {
    label: "Incomplete",
    bg: "bg-status-incomplete-bg",
    fg: "text-status-incomplete-fg",
  },
};

export interface StatusBadgeProps {
  status: Status;
  className?: string;
}

/**
 * Status badge with colour token + text label.
 * No animated elements — respects prefers-reduced-motion by default.
 */
export function StatusBadge({ status, className }: StatusBadgeProps) {
  const config = statusConfig[status];

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium",
        config.bg,
        config.fg,
        className,
      )}
    >
      {config.label}
    </span>
  );
}
