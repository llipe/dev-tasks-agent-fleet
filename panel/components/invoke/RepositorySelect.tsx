"use client";

import styles from "./FieldRow.module.css";

/**
 * S-113 (issue 126) — the repository selector (task 2.6, DESIGN §5.4).
 *
 * Rendered SEPARATELY from the params, outside `params_schema`, only when the
 * agent's `requires_repository` is true (§4 — the repo is a first-class field,
 * not a schema property). Lists enabled, non-archived repositories. When the
 * list is empty it shows an empty-state note and the parent blocks submit.
 */
export interface RepositoryOption {
  id: string;
  full_name: string;
}

export interface RepositorySelectProps {
  repositories: RepositoryOption[];
  value: string | null;
  onChange: (repositoryId: string) => void;
}

export function RepositorySelect({ repositories, value, onChange }: RepositorySelectProps) {
  const empty = repositories.length === 0;
  return (
    <div className={styles.row}>
      <div className={styles.labelCol}>
        <label className={styles.label} htmlFor="repository">
          Repository
          <span className={styles.required} aria-hidden="true">
            {" "}
            *
          </span>
        </label>
        <span className={styles.meta}>required</span>
        <span className={styles.help}>
          The repository the agent runs against (enabled, non-archived).
        </span>
      </div>
      <div className={styles.controlCol}>
        {empty ? (
          <span className={styles.note} role="note">
            No enabled repositories — add one via the seed before invoking.
          </span>
        ) : (
          <select
            id="repository"
            className={styles.select}
            value={value ?? ""}
            aria-required
            onChange={(e) => onChange(e.target.value)}
          >
            {value === null && (
              <option value="" disabled>
                Select a repository…
              </option>
            )}
            {repositories.map((r) => (
              <option key={r.id} value={r.id}>
                {r.full_name}
              </option>
            ))}
          </select>
        )}
      </div>
    </div>
  );
}
