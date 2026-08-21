"use client";

/**
 * EnabledToggle — S-022, sub-task 22.3.
 *
 * Optimistic UI toggle for the enabled state of a subject-agent pair.
 * Flips immediately on click; rolls back on failure with error naming the repo.
 */

import { useState, useCallback, useTransition } from "react";
import { setSubjectEnabled } from "@/server/actions/scope.js";
import { cn } from "@/lib/utils/cn.js";

interface EnabledToggleProps {
  subjectId: string;
  agentName: string;
  initialEnabled: boolean;
}

export function EnabledToggle({ subjectId, agentName, initialEnabled }: EnabledToggleProps) {
  const [enabled, setEnabled] = useState(initialEnabled);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const handleToggle = useCallback(() => {
    const newEnabled = !enabled;

    // Optimistic flip
    setEnabled(newEnabled);
    setError(null);

    startTransition(async () => {
      const result = await setSubjectEnabled({
        subjectId,
        agentName,
        enabled: newEnabled,
      });

      if (!result.ok) {
        // Rollback
        setEnabled(!newEnabled);
        setError(`Failed to update "${subjectId}": ${result.error.message}`);
      }
    });
  }, [enabled, subjectId, agentName]);

  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label={`Toggle ${subjectId} ${enabled ? "off" : "on"}`}
        disabled={isPending}
        onClick={handleToggle}
        className={cn(
          "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-secondary",
          enabled ? "bg-brand-secondary" : "bg-surface-border",
          isPending && "opacity-50",
        )}
      >
        <span
          className={cn(
            "pointer-events-none inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform",
            enabled ? "translate-x-[18px]" : "translate-x-[3px]",
          )}
        />
      </button>
      {error && (
        <span role="alert" className="text-xs text-status-failed-fg">
          {error}
        </span>
      )}
    </div>
  );
}
