"use client";

import Link from "next/link";
import styles from "./SuccessState.module.css";

/**
 * S-113 (issue 126) — the invoke success confirmation (task 2.8, DESIGN §5.4).
 *
 * Shown after a 202 (or a 502 that still produced a run) before/while the app
 * navigates to `/runs/[id]`. `rise` animation (DESIGN §6.1), the run id in
 * monospace, and a link to the run detail. The parent triggers navigation; this
 * is the visible confirmation with an explicit link as a fallback.
 */
export interface SuccessStateProps {
  runId: string;
  /** True when the run was accepted (202); false when it failed to start (502). */
  accepted: boolean;
}

export function SuccessState({ runId, accepted }: SuccessStateProps) {
  return (
    <div className={styles.wrap} role="status" data-testid="invoke-success">
      <p className={styles.title}>{accepted ? "Run queued" : "Run failed to start"}</p>
      <p className={styles.body}>
        Run <code className={styles.runId}>{runId}</code>{" "}
        {accepted
          ? "was queued. Opening the run detail…"
          : "was recorded but did not start. Opening the run detail…"}
      </p>
      <Link className={styles.link} href={`/runs/${runId}`}>
        View run
      </Link>
    </div>
  );
}
