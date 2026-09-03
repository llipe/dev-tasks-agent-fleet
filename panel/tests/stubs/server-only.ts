// Test-only stub for the `server-only` package.
//
// `server-only` uses conditional exports that resolve to a module which throws
// unless it is in a React Server Component graph. Under Vitest's `node`
// environment that guard fires and blocks importing any module that (correctly)
// imports `server-only` — e.g. lib/supabase/server.ts. Aliasing `server-only`
// to this no-op in vitest.config.ts lets those modules be unit-tested in
// isolation. This does NOT weaken the real guard: `next build` still resolves
// the true `server-only`, so a client bundle importing a server-only module
// still fails the production build.
export {};
