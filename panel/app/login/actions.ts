"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { createAuthServerClient } from "@/lib/supabase/auth-server";
import { classifySignInError, userMessageFor, type AuthErrorCode } from "@/lib/auth/errors";
import { safeRedirectTarget } from "@/lib/auth/redirect";

/**
 * Login server action (Story S-119, spec §8.2 / §8.3).
 *
 * The security-critical properties enforced here:
 *   - **Anti-enumeration (AC5):** unknown-email and wrong-password both flow
 *     through `classifySignInError`, which collapses every 4xx credential
 *     failure to `AUTH_INVALID_CREDENTIALS` — the identical user-facing message
 *     via `userMessageFor`. No branch in this action inspects *which* credential
 *     was wrong, so the two are indistinguishable in the response.
 *   - **Redirect safety (AC4):** the untrusted `redirect` field is passed
 *     through `safeRedirectTarget` (S-116) BEFORE it is used, so an
 *     absolute/off-origin/`/login`-loop value can never send the operator
 *     off-origin or into a loop. Sanitization happens once, up front.
 *   - **No password echo:** on any failure the action returns only a message
 *     and the (already-sanitized) redirect target — never the submitted
 *     password. The password is forwarded to Supabase over HTTPS and is never
 *     stored, logged, or returned.
 *
 * Shape: a pure `resolveSignIn` core takes an injected sign-in function so the
 * decision logic (validation → sanitize → classify) is unit-testable without a
 * live Supabase or Next.js request context. The exported `"use server"`
 * `signIn` wires the real cookie-backed client and performs the redirect on
 * success (a `redirect()` throws control-flow, so it lives outside the testable
 * core).
 */

/** The action's return shape on a NON-redirecting (failure) outcome. */
export interface SignInFailure {
  ok: false;
  /** Generic, safe-to-display message (never reveals whether an email exists). */
  message: string;
  /** Internal code — useful for tests; never rendered raw to the user. */
  code: AuthErrorCode;
  /** The sanitized redirect target, preserved so the form re-renders with it. */
  redirect: string;
}

/** The action's return shape on success (the caller then performs the redirect). */
export interface SignInSuccess {
  ok: true;
  /** The sanitized, safe same-origin target to redirect to. */
  redirect: string;
}

export type SignInResult = SignInFailure | SignInSuccess;

/** The minimal Supabase sign-in surface the core depends on (injectable). */
export interface PasswordSignIn {
  (credentials: { email: string; password: string }): Promise<{
    error: { status?: number; code?: string; message?: string } | null;
  }>;
}

/**
 * Pure decision core: validate field shape, sanitize the redirect BEFORE use,
 * attempt sign-in via the injected function, and map any error to a generic
 * message. Never throws; never redirects; never returns the password.
 *
 * @param raw the untrusted form values (email, password, redirect).
 * @param signInWithPassword injected Supabase password sign-in.
 */
export async function resolveSignIn(
  raw: { email: unknown; password: unknown; redirect: unknown },
  signInWithPassword: PasswordSignIn,
): Promise<SignInResult> {
  // Sanitize the redirect FIRST, so every downstream branch (success or
  // failure) carries only a safe same-origin target (AC4).
  const target = safeRedirectTarget(raw.redirect);

  const email = typeof raw.email === "string" ? raw.email.trim() : "";
  const password = typeof raw.password === "string" ? raw.password : "";

  // Field-shape validation is authoritative here (server-side); the client
  // `required`/`type=email` attributes are hints only (spec §10.4).
  if (email === "" || password === "") {
    return failure("AUTH_MISSING_FIELDS", target);
  }

  let error: { status?: number } | null;
  try {
    ({ error } = await signInWithPassword({ email, password }));
  } catch {
    // A thrown transport/network error is a service failure, not a credential
    // failure — mapped as unavailable so the operator is told to retry.
    return failure("AUTH_SERVICE_UNAVAILABLE", target);
  }

  if (error) {
    // classifySignInError collapses unknown-email and wrong-password to the
    // SAME code (AC5); only 5xx/429/network map to unavailable.
    return failure(classifySignInError(error), target);
  }

  return { ok: true, redirect: target };
}

function failure(code: AuthErrorCode, target: string): SignInFailure {
  return { ok: false, code, message: userMessageFor(code), redirect: target };
}

/**
 * The `"use server"` action bound to the login form. Wires the cookie-backed
 * anon auth client (so a successful sign-in writes the HttpOnly session cookie
 * on this request), runs the pure core, and on success redirects to the
 * sanitized target. On failure it returns the generic message for the form to
 * render in its `role="alert"` region.
 *
 * @param _prev previous action state (unused; required by `useActionState`).
 * @param formData the submitted form data.
 */
export async function signIn(
  _prev: SignInResult | null,
  formData: FormData,
): Promise<SignInResult> {
  const cookieStore = await cookies();
  const supabase = createAuthServerClient(cookieStore);

  const result = await resolveSignIn(
    {
      email: formData.get("email"),
      password: formData.get("password"),
      redirect: formData.get("redirect"),
    },
    (credentials) => supabase.auth.signInWithPassword(credentials),
  );

  if (result.ok) {
    // A successful sign-in has set the session cookie on the response; send the
    // operator to their sanitized target (or `/`). `redirect()` throws to
    // unwind — it must be outside try/catch and is never reached on failure.
    redirect(result.redirect);
  }

  return result;
}
