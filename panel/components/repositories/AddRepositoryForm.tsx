"use client";

import { useActionState, useEffect, useRef, useState, type FormEvent } from "react";
import { useFormStatus } from "react-dom";

import { Button } from "../Button";
import { Input } from "../Input";
import { KLabel } from "../KLabel";
import { addRepository, type AddRepositoryResult } from "@/app/(panel)/repositories/actions";
import { parseFullName } from "@/lib/domain/repository-input";
import styles from "./AddRepositoryForm.module.css";

/**
 * The Add-repository form (Story S-147, spec §10, DESIGN.md §5.6 — first-pass
 * layout, see the stub note there). Mirrors `LoginForm`'s shape:
 *
 *   - Submits to the `addRepository` server action via `useActionState`.
 *   - `useFormStatus` drives the pending/disabled double-submit guard.
 *   - Client-side validation via the SAME `parseFullName` the action
 *     re-validates server-side (fail-fast before the round-trip, AC4) — this
 *     never replaces the server check, only short-circuits the obviously bad
 *     case earlier.
 *   - On success, the (uncontrolled) fields are cleared by remounting under a
 *     fresh key, and a success line names the added repository (no client-side
 *     row-append here — the server component `page.tsx` re-fetches the list
 *     on next navigation; a full-page flow, matching the codebase's existing
 *     "reload picks it up" posture rather than adding new client-side list
 *     state for this first version).
 */
const INVALID_FORMAT_MESSAGE =
  'Must be "owner/repo" (letters, numbers, dots, dashes, underscores only).';

function Fields({
  serverError,
  clientError,
  onFullNameChange,
}: {
  serverError: string | null;
  clientError: string | null;
  onFullNameChange: (value: string) => void;
}) {
  const { pending } = useFormStatus();
  const displayedError = clientError ?? serverError;

  return (
    <>
      {displayedError && (
        <div className={styles.alert} role="alert">
          {displayedError}
        </div>
      )}

      <div className={styles.field}>
        <KLabel>
          <label htmlFor="repo-full-name">Repository</label>
        </KLabel>
        <Input
          id="repo-full-name"
          name="fullName"
          placeholder="owner/repo"
          autoComplete="off"
          required
          disabled={pending}
          onChange={(e) => onFullNameChange(e.target.value)}
          aria-invalid={displayedError != null}
        />
      </div>

      <div className={styles.field}>
        <KLabel>
          <label htmlFor="repo-default-branch">Default branch</label>
        </KLabel>
        <Input
          id="repo-default-branch"
          name="defaultBranch"
          placeholder="main"
          autoComplete="off"
          disabled={pending}
        />
      </div>

      <Button
        type="submit"
        variant="primary"
        className={styles.submit}
        disabled={pending}
        aria-disabled={pending}
      >
        {pending ? "Adding…" : "Add repository"}
      </Button>
    </>
  );
}

export function AddRepositoryForm() {
  const [state, formAction] = useActionState<AddRepositoryResult | null, FormData>(
    addRepository,
    null,
  );
  const [clientError, setClientError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const seen = useRef<AddRepositoryResult | null>(null);

  // Clear the (uncontrolled) fields after a SUCCESSFUL add, by remounting the
  // field group under a fresh key — mirrors LoginForm's post-failure password
  // reset, applied on the opposite (success) branch here.
  useEffect(() => {
    if (state && state !== seen.current) {
      seen.current = state;
      if (state.ok) {
        setAttempt((n) => n + 1);
        setClientError(null);
      }
    }
  }, [state]);

  const serverError = state && !state.ok ? state.message : null;

  function handleFullNameChange(value: string) {
    if (value.trim() === "") {
      setClientError(null);
      return;
    }
    setClientError(parseFullName(value).ok ? null : INVALID_FORMAT_MESSAGE);
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    const raw = new FormData(e.currentTarget).get("fullName");
    const parsed = parseFullName(typeof raw === "string" ? raw : "");
    if (!parsed.ok) {
      // Fail fast, before the Server Action round-trip (AC4). The action
      // re-validates the same shape server-side regardless.
      e.preventDefault();
      setClientError(INVALID_FORMAT_MESSAGE);
    }
  }

  return (
    <form className={styles.form} action={formAction} onSubmit={handleSubmit} noValidate>
      <div key={attempt} className={styles.fieldGroup}>
        <Fields
          serverError={serverError}
          clientError={clientError}
          onFullNameChange={handleFullNameChange}
        />
      </div>

      {state?.ok && (
        <p className={styles.success} role="status">
          Added &quot;{state.repository.full_name}&quot;.
        </p>
      )}
    </form>
  );
}
