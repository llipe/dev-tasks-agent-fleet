import { StatusDot } from "@/components/StatusDot";
import { formatEventCount } from "@/lib/format";
import type { StepPanelRow } from "@/lib/domain/run-detail";

import styles from "./StepsPanel.module.css";

/**
 * StepsPanel — /DESIGN.md §5.3 (Story S-145, FR9/FR10).
 *
 * A vertical list of `run_steps` rows: colored status dot, mono step name,
 * duration, event count. Clicking a row calls `onSelectStep(id)`, filtering
 * the log viewer to that step's events (FR10); the "All steps" control
 * calls `onSelectStep(null)`, restoring the full tail. Both branches are
 * pure presentation — the actual filtering happens in `applyLogFilter`
 * (`lib/domain/log-filter.ts`), called by the log-viewer wrapper.
 *
 * The color comes straight from `run_steps.status` (never `effective_status`
 * — steps carry no reaper-computed "effective" state, business rule §8.2),
 * reusing the existing `StatusDot`/`statusMeta` mapping — no new color logic.
 * A zero-step run renders an empty (but present) panel, not an error
 * (edge-case matrix).
 */
export interface StepsPanelProps {
  steps: StepPanelRow[];
  /** The currently-selected step id, or null when "All steps" is active. */
  selectedStepId: string | null;
  onSelectStep: (stepId: string | null) => void;
}

export function StepsPanel({ steps, selectedStepId, onSelectStep }: StepsPanelProps) {
  return (
    <div className={styles.panel} data-steps-panel aria-label="Steps">
      {/* A zero-step run renders no controls at all — there is nothing to
       * filter, so "All steps" would be a no-op affordance (edge case:
       * empty panel, not an error). */}
      {steps.length > 0 && (
        <button
          type="button"
          className={styles.row}
          aria-pressed={selectedStepId === null}
          onClick={() => onSelectStep(null)}
        >
          <span className={styles.allSteps}>All steps</span>
        </button>
      )}
      {steps.map((step) => (
        <button
          key={step.id}
          type="button"
          className={styles.row}
          aria-pressed={selectedStepId === step.id}
          onClick={() => onSelectStep(step.id)}
        >
          <StatusDot status={step.status} size={6} />
          <span className={styles.name}>{step.title}</span>
          <span className={styles.duration}>{step.duration}</span>
          <span className={styles.eventCount}>{formatEventCount(step.eventCount)}</span>
        </button>
      ))}
    </div>
  );
}
