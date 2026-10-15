// Native flat config for eslint-config-next 16 (issue 217 D-04). The former
// `FlatCompat` / `@eslint/eslintrc` bridge is gone: v16 ships flat-config arrays
// directly. `eslint-config-next/core-web-vitals` already composes the base Next
// config (typescript-eslint, react, react-hooks v7, import, jsx-a11y, the Next
// parser) plus the Core Web Vitals rules; `eslint-config-next/typescript` layers
// the TS-specific recommended rules. Spreading both reproduces the previous
// `compat.extends("next/core-web-vitals", "next/typescript")` exactly, with no
// rule disabled or downgraded (D-08).
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const eslintConfig = [
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    ignores: [
      ".next/**",
      "coverage/**",
      "node_modules/**",
      "next-env.d.ts",
      "playwright-report/**",
      "test-results/**",
      // Transient SD2-rule test fixtures (created/removed by
      // tests/unit/eslint-server-import.test.ts). The test lints them
      // explicitly with --no-ignore; this keeps a routine `eslint .` clean if a
      // run is interrupted and leaves one behind.
      "components/__sd2_fixture__/**",
      "lib/__sd2_fixture_server__.ts",
    ],
  },
  {
    // SD2 guard (lint-time hint). The server-only Supabase client carries the
    // service role key and must never enter the client bundle. The HARD guard
    // is the `import "server-only"` pragma at the top of lib/supabase/server.ts:
    // if that module is ever pulled into a client bundle, `next build` fails
    // with a precise React Server Components error that no `eslint-disable` can
    // suppress. This lint rule is the fast, pre-build hint on top of it.
    //
    // The restriction is scoped to the client-component trees: components/**
    // and the app/** subtree — but it MUST NOT fire on App Router server
    // entrypoints (page/layout/route/template/default/error/loading/not-found)
    // or on a "use server" Server Actions file (`actions.ts`, S-147 — the
    // panel's first Server Action to read Supabase directly via
    // `createServerClient()`, the same legitimate server-only usage as a route
    // handler), which read Supabase on purpose (SD2). Those filenames are
    // excluded below. `server-only` remains the hard build-time guard for
    // every server module.
    files: ["components/**/*.ts", "components/**/*.tsx", "app/**/*.ts", "app/**/*.tsx"],
    ignores: [
      "app/**/page.tsx",
      "app/**/layout.tsx",
      "app/**/route.ts",
      "app/**/template.tsx",
      "app/**/default.tsx",
      "app/**/error.tsx",
      "app/**/loading.tsx",
      "app/**/not-found.tsx",
      "app/**/actions.ts",
    ],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/lib/supabase/server", "@/lib/supabase/server"],
              message:
                "SD2: lib/supabase/server.ts is server-only (holds the service role key). Do not import it from a client component. Read Supabase in Server Components or route handlers only.",
            },
          ],
        },
      ],
    },
  },
];

export default eslintConfig;
