import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

const eslintConfig = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
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
    // entrypoints (page/layout/route/template/default/error/loading/not-found),
    // which read Supabase on purpose (SD2). Those filenames are excluded below.
    // `server-only` remains the hard build-time guard for every server module.
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
