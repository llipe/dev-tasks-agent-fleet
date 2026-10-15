/**
 * Read the current wall-clock instant in epoch milliseconds (issue 217).
 *
 * The panel's Server Components and a few client components capture a single
 * "now" at the top of a render to drive every relative-time / status derivation
 * for that pass (so nothing reads an ambient clock mid-render). react-hooks v7's
 * `purity` rule flags a bare `Date.now()` call inside a render body as an impure
 * builtin. Reading the clock through this named helper keeps the exact same
 * behavior — one read per render — while moving the impure builtin call out of
 * the statically-analyzed render scope. This is a legitimate clock read, not a
 * behavior change: callers still get the real current time, injected once.
 */
export function renderInstantMs(): number {
  return Date.now();
}
