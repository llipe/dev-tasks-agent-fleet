# Fixture repositories (S-189)

Plain directory trees. A test copies one into a temporary directory, commits
it with real `git`, and clones it from a local bare remote
(`tests/component/repo_fixtures.py`). They are never imported or collected.

| Fixture | Shape |
| ------- | ----- |
| `js-pnpm-ok` | pnpm by `pnpm-lock.yaml`; `test`, `lint`, `format:check`, `typecheck`, `audit` scripts; `developer.md` |
| `js-npm-ok` | npm by `package-lock.json`; the same scripts |
| `js-npm-out-of-sync` | `package.json` declares a dependency `package-lock.json` lacks (D-63) |
| `js-missing-typecheck` | no `typecheck` script |
| `js-format-dash` | `format-check` instead of `format:check` |
| `js-no-scripts` | `package.json` with no `scripts` |
| `js-monorepo` | root scripts and lockfile, plus a workspace package |
| `js-autofix-lint` | `lint` rewrites a tracked file, adds an untracked one and fills `node_modules/` (TC-189-15) |
| `js-node-24` | `js-pnpm-ok` with `engines.node: ">=24.21.0 <25"`, which only the image's Node 24 satisfies |
| `js-node-unsupported` | `js-pnpm-ok` with `engines.node: ">=30"`, which no Node in the image satisfies |
| `py-make-ok` | `Makefile` targets `install`, `test`, `lint`, `format-check`, `typecheck`, `audit` |
| `py-no-developer-md` | every target, no `.claude/agents/developer.md` |
| `py-format-underscore` | `format_check` instead of `format-check` |
| `py-no-install` | no `install` target (D-112) |
| `none` | neither `package.json` nor `Makefile` |
