// =====================================================================
// MOVED — this file is no longer the canonical credential provider.
//
// As of Story S-111 (issue #124) the AWS credential provider lives in the
// panel package with the SD9 / F5 corrections applied. The canonical source
// of truth is now:
//
//     panel/lib/aws/credentials.ts
//
// (with panel/lib/aws/errors.ts for the FlyOidcShapeError +
//  CREDENTIALS_UNAVAILABLE / INVOCATION_FAILED taxonomy, and
//  panel/lib/aws/invoke.ts for the InvokeAgentRuntime wrapper.)
//
// This stub is kept only so existing Markdown links to
// `docs/reference/credentials.ts` still resolve. Do NOT restore the old
// implementation here — it carried the F5 defect (an `aud` / raw-body token
// fallback) that the panel copy removes, and a second copy would drift.
// Edit the panel module instead.
// =====================================================================

export {};
