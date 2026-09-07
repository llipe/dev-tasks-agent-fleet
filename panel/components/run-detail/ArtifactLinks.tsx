import { isSafeArtifactUrl } from "@/lib/domain/artifact-url";
import type { ArtifactType } from "@/lib/supabase/types";

import styles from "./ArtifactLinks.module.css";

/**
 * ArtifactLinks — /DESIGN.md §5.3 (pill-shaped artifact links).
 *
 * Renders `run_artifacts` as pill links. Two guarantees this component carries:
 *
 *  - **AC14:** artifacts render REGARDLESS of run status — a `failed` run that
 *    still produced a `pull_request` surfaces the link alongside the red pill.
 *    This component receives artifacts, not status, so there is no code path
 *    that hides them on failure.
 *
 *  - **Security guard #5 (spec §12, A10):** `url` is agent-authored, untrusted.
 *    A link is rendered ONLY when `isSafeArtifactUrl(url)` (well-formed
 *    `https:`); every other value renders as inert text, never an `<a href>`.
 *    Safe links carry `rel="noopener noreferrer"` and open in a new tab.
 *
 * Presentational and server-safe.
 */
export interface ArtifactView {
  id: string;
  type: ArtifactType;
  title: string | null;
  url: string | null;
}

const TYPE_LABEL: Record<string, string> = {
  pull_request: "Pull request",
  audit_report: "Audit report",
  diff: "Diff",
  file: "File",
};

function label(a: ArtifactView): string {
  if (a.title != null && a.title.length > 0) return a.title;
  return TYPE_LABEL[a.type] ?? a.type;
}

export interface ArtifactLinksProps {
  artifacts: ArtifactView[];
}

export function ArtifactLinks({ artifacts }: ArtifactLinksProps) {
  if (artifacts.length === 0) return null;

  return (
    <ul className={styles.list} aria-label="Artifacts">
      {artifacts.map((a) => {
        const safe = isSafeArtifactUrl(a.url);
        return (
          <li key={a.id} className={styles.item}>
            {safe ? (
              <a
                className={styles.link}
                href={a.url as string}
                target="_blank"
                rel="noopener noreferrer"
              >
                {label(a)}
              </a>
            ) : (
              // Unsafe or absent URL — inert text, never a link (guard #5).
              <span className={styles.inert} title="No linkable URL">
                {label(a)}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
