/**
 * Test operator credentials + provisioning for the E2E auth scenarios (S-119).
 *
 * The auth gate (S-117) is active in E2E, so the suite needs a real operator
 * account to sign in with. This account is created once in `global-setup.ts`
 * via the Supabase admin API against the LOCAL stack (operator accounts are
 * created in the dashboard in production — never seeded by a migration — so the
 * E2E suite provisions its own, mirroring the story's migration opt-out note).
 *
 * The credentials are fixed, clearly test-only, and used only against the local
 * stack. They are NOT application config and never reach a real environment.
 */

import { createClient } from "@supabase/supabase-js";

export const TEST_OPERATOR_EMAIL = "e2e-operator@panel.test";
export const TEST_OPERATOR_PASSWORD = "e2e-Operator-Pw-4f7a2c19";

/**
 * Create (or reset) the test operator user via the admin API. Idempotent: if
 * the user already exists (a prior run left it), delete and recreate so the
 * password is known. Requires the local stack's service-role key + API URL.
 */
export async function provisionTestOperator(apiUrl: string, serviceRoleKey: string): Promise<void> {
  const admin = createClient(apiUrl, serviceRoleKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });

  // Remove any pre-existing account with this email so the password is known.
  const existing = await admin.auth.admin.listUsers();
  if (!existing.error) {
    const dup = existing.data.users.find((u) => u.email === TEST_OPERATOR_EMAIL);
    if (dup) await admin.auth.admin.deleteUser(dup.id).catch(() => {});
  }

  const { error } = await admin.auth.admin.createUser({
    email: TEST_OPERATOR_EMAIL,
    password: TEST_OPERATOR_PASSWORD,
    email_confirm: true,
  });
  if (error && !/already been registered/i.test(error.message)) {
    throw new Error(`E2E setup: failed to provision the test operator user: ${error.message}`);
  }
}
