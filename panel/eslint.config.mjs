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
    ],
  },
  {
    // SD2 guard: the server-only Supabase client must never be imported into a
    // client component (it carries the service role key). The module does not
    // exist yet — the rule lands before it, so the first import that violates
    // SD2 fails lint. Client components are those carrying the "use client"
    // pragma; this restricted-import rule is the coarse, always-on backstop.
    files: ["**/*.ts", "**/*.tsx"],
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
