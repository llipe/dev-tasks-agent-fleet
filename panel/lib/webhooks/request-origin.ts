/**
 * S-176 (#321) — the origin for the payload URL shown on `/webhooks`: the
 * host the operator is using, so it reads correctly on Fly and locally. It is
 * display-only; the webhook route never trusts it. Anything that isn't a plain
 * host[:port] yields "" (a relative URL) instead of being rendered.
 */
const HOST = /^[A-Za-z0-9.-]+(:\d{1,5})?$/;

export function requestOrigin(h: { get(name: string): string | null }): string {
  const host = (h.get("x-forwarded-host") ?? h.get("host") ?? "").split(",")[0]!.trim();
  if (!HOST.test(host)) return "";
  const forwarded = (h.get("x-forwarded-proto") ?? "").split(",")[0]!.trim();
  const local = /^(localhost|127\.0\.0\.1)(:\d+)?$/.test(host);
  const proto =
    forwarded === "http" || forwarded === "https" ? forwarded : local ? "http" : "https";
  return `${proto}://${host}`;
}

/** The payload URL for an endpoint token under an origin ("" → relative). */
export function webhookUrl(baseUrl: string, urlToken: string): string {
  return `${baseUrl.replace(/\/+$/, "")}/api/webhooks/${urlToken}`;
}
