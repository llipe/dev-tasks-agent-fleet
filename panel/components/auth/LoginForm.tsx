"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { Button } from "../Button";
import { Input } from "../Input";
import { KLabel } from "../KLabel";
import { signIn, type SignInResult } from "@/app/login/actions";
import { PasswordField } from "./PasswordField";
import styles from "./LoginForm.module.css";

/**
 * The `/login` form (Story S-119, spec §10.1). Client component: it owns the
 * action state and the pending/disabled UX. Presentation reuses the Nocturne
 * primitives (`Input`, `Button`, `KLabel`) and token-only CSS Modules.
 *
 * Behavior contract:
 *   - Submits to the `signIn` server action via `useActionState`. On success
 *     the action redirects server-side (this component never sees a success
 *     result); on failure it returns a generic message rendered in the
 *     `role="alert"` region above the fields (AC5/AC10).
 *   - `useFormStatus` drives the pending state: while submitting, the fields
 *     and the button are disabled and the button shows a pending label — this
 *     is what prevents a double submit / double post (edge case).
 *   - The `redirect` target is carried as a hidden field so the action can
 *     sanitize and honor it; it is authoritative-sanitized server-side.
 *   - "Forgot password?" is a DEAD control: a `<span aria-disabled>`, NOT an
 *     `<a href="#">` — non-focusable-as-a-link and non-activatable (AC16).
 *
 * Region tag value is a non-secret display string passed from the server
 * component (read from `AWS_REGION`), not hardcoded here.
 */
export interface LoginFormProps {
  /** The raw, still-untrusted redirect target from `?redirect` (sanitized server-side). */
  redirectTarget: string;
  /** Non-secret region label for the footer tag (e.g. "us-east-1"). */
  region: string;
}

/** The interactive body — must be a descendant of <form> to read useFormStatus. */
function Fields({ error }: { error: string | null }) {
  const { pending } = useFormStatus();

  return (
    <>
      {error && (
        <div className={styles.alert} role="alert">
          {error}
        </div>
      )}

      <div className={styles.field}>
        <KLabel>
          <label htmlFor="login-email">EMAIL</label>
        </KLabel>
        <Input
          id="login-email"
          name="email"
          type="email"
          autoComplete="email"
          placeholder="you@company.com"
          required
          disabled={pending}
        />
      </div>

      <PasswordField name="password" label="PASSWORD" disabled={pending} />

      <Button
        type="submit"
        variant="primary"
        className={styles.submit}
        disabled={pending}
        aria-disabled={pending}
      >
        {pending ? "Signing in…" : "Sign in"}
      </Button>
    </>
  );
}

export function LoginForm({ redirectTarget, region }: LoginFormProps) {
  const [state, formAction] = useActionState<SignInResult | null, FormData>(signIn, null);
  const error = state && !state.ok ? state.message : null;

  return (
    <form className={styles.form} action={formAction} noValidate>
      {/* The redirect target is sanitized server-side; carried through so the
          action can honor a legitimate one. */}
      <input type="hidden" name="redirect" value={redirectTarget} />

      <Fields error={error} />

      <div className={styles.footer}>
        {/* Dead link: a styled non-link span, aria-disabled, not activatable (AC16). */}
        <span className={styles.deadLink} aria-disabled="true">
          Forgot password?
        </span>
        <span className={styles.region}>· {region}</span>
      </div>

      <p className={styles.finePrint}>Sessions expire after 12 hours of inactivity.</p>
    </form>
  );
}
