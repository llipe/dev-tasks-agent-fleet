import type { CSSProperties } from "react";

import type { Banner } from "@/lib/domain/run-detail";
import { statusMeta } from "@/components/status-meta";

import styles from "./StateBanner.module.css";

/**
 * StateBanner — /DESIGN.md §8.3. Shown above the log viewer for the two
 * reaper terminal states (`timed_out`, `failed_to_start`). Colored border +
 * background tint driven by the status color token; carries the reaper's
 * explanatory event text so the operator sees *why* the run ended when the
 * agent itself never reported (product-context success metric 3).
 *
 * Presentational and server-safe. The explanatory text is rendered as an inert
 * text node — it originates from `runs.error_message`, which is agent/reaper
 * authored (untrusted, spec §12); React escapes it.
 */
export interface StateBannerProps {
  banner: Banner;
  /** Reaper/agent explanatory text (runs.error_message), or null. */
  message: string | null;
}

export function StateBanner({ banner, message }: StateBannerProps) {
  const meta = statusMeta(banner.status);
  const style = { "--st-color": meta.colorVar } as CSSProperties;
  return (
    <div className={styles.banner} style={style} role="status">
      <span
        className={[styles.dot, meta.hollow && styles.hollow].filter(Boolean).join(" ")}
        aria-hidden="true"
      />
      <div className={styles.body}>
        <span className={styles.title}>{banner.title}</span>
        {message != null && message.length > 0 && (
          <span className={styles.explanation}>{message}</span>
        )}
      </div>
    </div>
  );
}
