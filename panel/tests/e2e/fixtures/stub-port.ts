/**
 * The fixed local port the AgentCore HTTP-boundary stub binds to (S-114).
 *
 * A FIXED port (not ephemeral) is used deliberately: Playwright's `globalSetup`
 * runs before the `webServer` is launched, but the webServer's env
 * (`AWS_ENDPOINT_URL_BEDROCK_AGENTCORE`) is declared in `playwright.config.ts`
 * at config-evaluation time — before globalSetup runs. A fixed, agreed port
 * lets the config point the SDK at the stub without a runtime handshake.
 */
export const AGENTCORE_STUB_PORT = 54390;
export const AGENTCORE_STUB_ENDPOINT = `http://127.0.0.1:${AGENTCORE_STUB_PORT}`;
