#!/usr/bin/env node
/**
 * Fly OIDC token probe for the panel release gate (Issue #280, D-05).
 *
 * WHY THIS EXISTS. Since release v12 the deployed panel's Next.js server (uid
 * 1001, `nextjs`) could not connect to the Fly Machine OIDC socket `/.fly/api`:
 * Fly creates it root-owned `0755`, and connecting to a unix socket needs write
 * permission, so a non-root process gets `EACCES`. The fix (a root entrypoint
 * that group-grants the socket to `nodejs` and then drops to uid 1001 via
 * `setpriv`) must be guarded against silent recurrence. This probe is that
 * guard: `scripts/deploy-panel.sh` runs it on every started Machine, AS uid
 * 1001 (via `setpriv`), after the auth gate. If uid 1001 cannot obtain an OIDC
 * token, the release FAILS (deploy-panel.sh exit 3) instead of shipping a panel
 * that silently cannot invoke.
 *
 * WHAT IT DOES. It POSTs `{"aud":"sts.amazonaws.com"}` to `/v1/tokens/oidc` over
 * the socket — exactly the request `panel/lib/aws/credentials.ts`
 * (`fetchFlyOidcToken`) makes — and classifies the result. It does NOT exchange
 * the token with STS (no AWS call); obtaining a token as uid 1001 is the single
 * thing that was broken, so that is all it checks.
 *
 * SECRET DISCIPLINE (D-05, same posture as credentials.ts). The token value is
 * NEVER printed, logged, or persisted. The only line this program writes to
 * stdout is `status=<code> token=<present|absent>`. Token *presence* is
 * reported; the token itself never leaves this process.
 *
 * TOKEN-PRESENCE RULE. Identical to `extractOidcToken` in credentials.ts: the
 * socket returns a raw JWT body (three base64url segments separated by dots —
 * the real Fly shape confirmed 2026-10-14, D-07), OR a JSON object with a
 * string `value`/`token` key, OR a JSON-encoded JWT string. Anything else
 * (non-200, HTML error page, two-segment string, wrong shape) means absent.
 *
 * EXIT CODES. 0 only when HTTP status is 2xx AND a token is present; 1
 * otherwise. deploy-panel.sh maps any non-zero probe to its own exit 3.
 *
 * The pure classification functions are exported so they are unit-testable from
 * fixtures with NO socket and NO network (see
 * panel/tests/unit/fly-oidc-probe.test.ts). The socket I/O + CLI only run when
 * the file is executed directly.
 */

const DEFAULT_SOCKET = "/.fly/api";
const OIDC_PATH = "/v1/tokens/oidc";
const STS_AUDIENCE = "sts.amazonaws.com";

/**
 * JWT shape: three base64url segments separated by dots (the signature segment
 * MAY be empty). This is the literal shape of a raw JWT body, not a validation
 * of its contents.
 *
 * DUPLICATED from `extractOidcToken`'s `JWT_SHAPE` in
 * `panel/lib/aws/credentials.ts`. This probe ships as a single standalone file
 * into the runtime image (`/app/fly-oidc-probe.mjs`, see `Dockerfile.panel`)
 * with no `lib/` beside it, so it cannot import from lib/. Both copies MUST
 * stay identical; the parity corpus in
 * `panel/tests/unit/fly-oidc-probe.test.ts` fails if they drift.
 *
 * @param {string} s
 * @returns {boolean}
 */
function isJwtShaped(s) {
  return /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*$/.test(s);
}

/**
 * Is the token present in the socket's response body?
 *
 * Mirrors `extractOidcToken` (credentials.ts) EXACTLY: a trimmed raw JWT body,
 * a JSON object with a string `value` or `token` key, or a JSON-encoded
 * JWT-shaped string → present. Any other shape — HTML page, two-segment string,
 * array, non-object, missing/non-string key, unparseable body → absent. This
 * never returns or logs the token value, only the boolean presence.
 *
 * @param {string} rawBody
 * @returns {boolean}
 */
export function tokenIsPresent(rawBody) {
  if (typeof rawBody !== "string" || rawBody.length === 0) return false;
  const trimmed = rawBody.trim();
  if (trimmed.length === 0) return false;

  // 1. Raw JWT body — the real Fly shape as of 2026-10-14 (D-07).
  if (isJwtShaped(trimmed)) return true;

  let parsed;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    return false;
  }
  // 3. A JSON-encoded string that is itself JWT-shaped.
  if (typeof parsed === "string") return isJwtShaped(parsed.trim());
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return false;
  }
  // 2. JSON object carrying the token in a string `value`/`token` field.
  return typeof parsed.value === "string" || typeof parsed.token === "string";
}

/**
 * Is the HTTP status a 2xx success?
 * @param {number | undefined} status
 * @returns {boolean}
 */
export function statusIsOk(status) {
  return typeof status === "number" && status >= 200 && status < 300;
}

/**
 * Classify a probe outcome into the single reportable line and an exit code.
 *
 * The ONLY stdout the probe emits is `line`; `tokenPresent` is a boolean, never
 * the token itself. A pass (exit 0) requires BOTH a 2xx status AND a present
 * token — a 200 that returns the wrong shape is still a failure, because the
 * credential provider would then throw `FlyOidcShapeError` at invoke time.
 *
 * @param {{ status?: number, body?: string }} result
 * @returns {{ line: string, tokenPresent: boolean, ok: boolean, exitCode: number }}
 */
export function classifyProbe(result) {
  const src = result && typeof result === "object" ? result : {};
  const status = typeof src.status === "number" ? src.status : 0;
  const present = tokenIsPresent(typeof src.body === "string" ? src.body : "");
  const ok = statusIsOk(status) && present;
  return {
    line: `status=${status} token=${present ? "present" : "absent"}`,
    tokenPresent: present,
    ok,
    exitCode: ok ? 0 : 1,
  };
}

// --- Socket I/O (live, not unit-tested) -----------------------------------

/**
 * POST the OIDC request over the unix socket and resolve the raw HTTP result.
 * Rejects only on a transport error (socket missing/unreachable/refused) — a
 * non-2xx HTTP response resolves normally so `classifyProbe` can report it.
 *
 * @param {string} socketPath
 * @returns {Promise<{ status: number | undefined, body: string }>}
 */
async function requestOidc(socketPath) {
  const http = await import("node:http");
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ aud: STS_AUDIENCE });
    const req = http.request(
      {
        socketPath,
        path: OIDC_PATH,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(body),
        },
      },
      (res) => {
        let data = "";
        res.on("data", (chunk) => (data += chunk));
        res.on("end", () => resolve({ status: res.statusCode, body: data }));
      },
    );
    req.on("error", (err) => reject(err));
    req.write(body);
    req.end();
  });
}

async function mainCli() {
  // Socket path override (used ONLY for the AC5 negative demonstration — point
  // the probe at a non-existent socket and observe status=0 token=absent → the
  // non-zero exit deploy-panel.sh maps to exit 3). Production always uses the
  // default `/.fly/api`.
  const socketPath = process.env.FLY_OIDC_SOCKET || DEFAULT_SOCKET;
  let result;
  try {
    result = await requestOidc(socketPath);
  } catch {
    // Transport failure (EACCES as the old non-root user, ENOENT for a missing
    // socket, ECONNREFUSED): no HTTP status, no token. Report status=0 — never
    // the error detail, which could in theory echo a path but never a token.
    result = { status: 0, body: "" };
  }
  const verdict = classifyProbe(result);
  // The sole line of output. Never the token value.
  console.log(verdict.line);
  process.exit(verdict.exitCode);
}

// Run the live probe only when executed directly, not when imported by a test.
if (process.argv[1]) {
  const { fileURLToPath } = await import("node:url");
  if (fileURLToPath(import.meta.url) === process.argv[1]) {
    await mainCli();
  }
}
