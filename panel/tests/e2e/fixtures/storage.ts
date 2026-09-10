import { fileURLToPath } from "node:url";

/**
 * On-disk location of the authenticated operator storage state written by the
 * `auth.setup.ts` project and consumed by the chromium project (S-119). Kept in
 * a fixtures module so both the setup and the config reference one constant.
 *
 * The file lives under the e2e test tree and holds only a LOCAL-stack session
 * cookie — never real credentials. It is regenerated on every run.
 */
export const OPERATOR_STORAGE_STATE = fileURLToPath(
  new URL("../.auth/operator.json", import.meta.url),
);
