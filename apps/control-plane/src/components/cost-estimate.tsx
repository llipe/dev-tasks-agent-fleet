import { cn } from "@/lib/utils/cn";

export interface CostEstimateProps {
  /** Cost in USD. null/undefined means unpriced (unknown). */
  usd: number | null | undefined;
  /** Whether the cost is complete or partial (still accumulating). */
  complete: boolean;
  className?: string;
}

/**
 * Displays cost estimate in one of three modes:
 * - complete: exact "$X.XX"
 * - partial (incomplete): "≥ $X.XX" with visual marker
 * - unknown (null/undefined usd): "unknown" — never "$0.00" for unpriced
 */
export function CostEstimate({ usd, complete, className }: CostEstimateProps) {
  // Unknown: usd is null or undefined
  if (usd == null) {
    return (
      <span className={cn("text-text-muted tabular-nums text-sm", className)} title="Cost unknown">
        unknown
      </span>
    );
  }

  const formatted = `$${usd.toFixed(2)}`;

  // Complete cost
  if (complete) {
    return (
      <span
        className={cn("text-text-primary tabular-nums text-sm", className)}
        title={`Cost: ${formatted}`}
      >
        {formatted}
      </span>
    );
  }

  // Partial cost (still accumulating)
  return (
    <span
      className={cn("text-text-secondary tabular-nums text-sm", className)}
      title={`≥ ${formatted} (partial — run in progress)`}
    >
      ≥ {formatted}
    </span>
  );
}
