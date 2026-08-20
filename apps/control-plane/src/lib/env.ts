/**
 * Cloudflare Access environment configuration.
 * Validates required environment variables at import time.
 * If variables are missing, the app fails to start.
 */

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `Missing required environment variable: ${name}. The application cannot start without it.`,
    );
  }
  return value;
}

export const CF_ACCESS_TEAM_NAME = requireEnv("CF_ACCESS_TEAM_NAME");
export const CF_ACCESS_AUD = requireEnv("CF_ACCESS_AUD");

export const CF_ACCESS_CERTS_URL = `https://${CF_ACCESS_TEAM_NAME}.cloudflareaccess.com/cdn-cgi/access/certs`;
export const CF_ACCESS_ISSUER = `https://${CF_ACCESS_TEAM_NAME}.cloudflareaccess.com`;
