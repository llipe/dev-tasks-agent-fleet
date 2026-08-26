// lib/aws/credentials.ts
//
// Un solo provider de credenciales AWS para el panel, con dos ramas:
//
//   En Fly.io  → token OIDC del socket local → AssumeRoleWithWebIdentity
//   En local   → cadena estándar del SDK (perfil SSO, ~/.aws/credentials, env vars)
//
// El código de invocación no sabe en cuál está corriendo.
//
// Requiere: @aws-sdk/client-sts, @aws-sdk/credential-providers
// Env vars: AWS_ROLE_ARN (solo en Fly), AWS_REGION
//           AWS_PROFILE (solo en local, opcional)

import * as http from "node:http";
import * as fs from "node:fs";
import type { AwsCredentialIdentity, AwsCredentialIdentityProvider } from "@aws-sdk/types";
import { STSClient, AssumeRoleWithWebIdentityCommand } from "@aws-sdk/client-sts";
import { fromNodeProviderChain } from "@aws-sdk/credential-providers";

const FLY_OIDC_SOCKET = "/.fly/api";
const FLY_OIDC_PATH = "/v1/tokens/oidc";
const STS_AUDIENCE = "sts.amazonaws.com";
const REFRESH_MARGIN_MS = 60_000;

/** Corriendo en Fly si existe el socket de la Machine. */
function isFly(): boolean {
  return Boolean(process.env.FLY_APP_NAME) && fs.existsSync(FLY_OIDC_SOCKET);
}

// --------------------------------------------------------------- Fly OIDC

function fetchFlyOidcToken(audience: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ aud: audience });
    const req = http.request(
      {
        socketPath: FLY_OIDC_SOCKET,
        path: FLY_OIDC_PATH,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(body),
        },
      },
      (res) => {
        let data = "";
        res.on("data", (chunk) => (data += chunk));
        res.on("end", () => {
          const ok = res.statusCode !== undefined && res.statusCode >= 200 && res.statusCode < 300;
          if (!ok) {
            reject(new Error(`Fly OIDC respondió ${res.statusCode}: ${data.slice(0, 300)}`));
            return;
          }
          // Verificar el shape real con:
          //   curl --unix-socket /.fly/api -X POST http://localhost/v1/tokens/oidc \
          //        --data '{"aud":"sts.amazonaws.com"}'
          try {
            const parsed = JSON.parse(data) as Record<string, unknown>;
            const token = parsed.value ?? parsed.token ?? parsed.aud;
            resolve(typeof token === "string" ? token : data.trim());
          } catch {
            resolve(data.trim());
          }
        });
      }
    );
    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

async function assumeRoleFromFly(): Promise<AwsCredentialIdentity> {
  const roleArn = process.env.AWS_ROLE_ARN;
  if (!roleArn) throw new Error("Falta AWS_ROLE_ARN.");

  const token = await fetchFlyOidcToken(STS_AUDIENCE);
  const sts = new STSClient({ region: process.env.AWS_REGION ?? "us-east-1" });

  const out = await sts.send(
    new AssumeRoleWithWebIdentityCommand({
      RoleArn: roleArn,
      RoleSessionName: `panel-agentes-${process.env.FLY_MACHINE_ID ?? "local"}`,
      WebIdentityToken: token,
      DurationSeconds: 900,
    })
  );

  const c = out.Credentials;
  if (!c?.AccessKeyId || !c.SecretAccessKey || !c.SessionToken || !c.Expiration) {
    throw new Error("AssumeRoleWithWebIdentity no devolvió credenciales completas.");
  }
  return {
    accessKeyId: c.AccessKeyId,
    secretAccessKey: c.SecretAccessKey,
    sessionToken: c.SessionToken,
    expiration: c.Expiration,
  };
}

// --------------------------------------------------------------- provider

let cached: AwsCredentialIdentity | null = null;
let inFlight: Promise<AwsCredentialIdentity> | null = null;

const localChain = fromNodeProviderChain();

/**
 * Provider único. Se pasa tal cual a cualquier cliente del SDK:
 *   new BedrockAgentCoreClient({ region, credentials: awsCredentials })
 */
export const awsCredentials: AwsCredentialIdentityProvider = async () => {
  if (!isFly()) {
    // En local el SDK maneja su propio cache y refresh (SSO incluido).
    return localChain();
  }

  const now = Date.now();
  if (cached?.expiration && cached.expiration.getTime() - REFRESH_MARGIN_MS > now) {
    return cached;
  }

  inFlight ??= assumeRoleFromFly()
    .then((creds) => {
      cached = creds;
      return creds;
    })
    .finally(() => {
      inFlight = null;
    });

  return inFlight;
};

/** Para diagnóstico: qué rama se está usando. */
export function credentialSource(): "fly-oidc" | "local-chain" {
  return isFly() ? "fly-oidc" : "local-chain";
}
