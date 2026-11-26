// S-214 AC-1/AC-2 and S-217 (v1.8, AC-17 IAM half): the code-review runtime
// config and its least-privilege role.
//
// The runtime uses a dedicated, hand-made role (`executionRoleArn`), so the
// AgentCore L3 construct imports it read-only and attaches nothing. That is
// what keeps the construct's default `bedrock:InvokeModel*` grant on every
// foundation model off this agent. The role's inline policy is the desired-
// state document `agentcore/iam/runtime-role-policy.json`, pinned here; the
// infra-engineer applies it with `put-role-policy` (S-218). The v1.0 record in
// `infra/changes/20261024-code-review-runtime/` stays as applied history.
//
// v1.8 (D-74, D-88): the model is Claude Sonnet 5.5 on the Anthropic API, so
// the role has no `bedrock:` action at all and reads one more secret, the
// Anthropic API key, by name.
import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import * as fs from 'fs';
import * as path from 'path';
import { AgentCoreStack } from '../lib/cdk-stack';

const AGENTCORE_DIR = path.resolve(__dirname, '..', '..');
const REPO_ROOT = path.resolve(AGENTCORE_DIR, '..', '..', '..');
const CHANGE_DIR = path.join(REPO_ROOT, 'infra', 'changes', '20261024-code-review-runtime');
const POLICY_PATH = path.join(AGENTCORE_DIR, 'iam', 'runtime-role-policy.json');

const ACCOUNT = '755641879575';
const ROLE_ARN = `arn:aws:iam::${ACCOUNT}:role/agent-fleet-code-review-runtime`;
// D-71, D-80: Claude Sonnet 5.5 on the Anthropic API (an Anthropic model ID).
const MODEL_ID = 'claude-sonnet-5-5';
// D-88: the key's secret, read by name. Created in S-218 (ChangeId
// 20261125-code-review-anthropic-v18) as a dedicated secret: the planned name
// agent-fleet/prod/ANTHROPIC_API_KEY is the bug-fix agent's key (D-50). The
// grant names its full ARN, suffix included, like the other two secrets.
const ANTHROPIC_KEY_SECRET_ID = 'agent-fleet/prod/CODE_REVIEW_ANTHROPIC_API_KEY';
const ANTHROPIC_KEY_SECRET_ARN = `arn:aws:secretsmanager:us-east-1:${ACCOUNT}:secret:${ANTHROPIC_KEY_SECRET_ID}-K0guwA`;
const BUG_FIX_KEY_SECRET_ID = 'agent-fleet/prod/ANTHROPIC_API_KEY';
const SECRET_ARNS = [
  `arn:aws:secretsmanager:us-east-1:${ACCOUNT}:secret:agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY-wS5xrJ`,
  `arn:aws:secretsmanager:us-east-1:${ACCOUNT}:secret:agent-fleet/prod/GITHUB_APP_PRIVATE_KEY-t4sXT2`,
  ANTHROPIC_KEY_SECRET_ARN,
];

type Statement = {
  Sid?: string;
  Effect: string;
  Action: string | string[];
  Resource: string | string[];
  Condition?: Record<string, Record<string, string>>;
};

const asList = (v: string | string[]): string[] => (Array.isArray(v) ? v : [v]);
const readJson = (p: string) => JSON.parse(fs.readFileSync(p, 'utf8'));

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const spec: any = readJson(path.join(AGENTCORE_DIR, 'agentcore.json'));
const runtime = spec.runtimes[0];

describe('agentcore.json (AC-1)', () => {
  test('defines exactly one runtime, code_review: Container, PUBLIC, HTTP', () => {
    expect(spec.name).toBe('codereview');
    expect(spec.runtimes).toHaveLength(1);
    expect(runtime).toMatchObject({
      name: 'code_review',
      build: 'Container',
      entrypoint: 'main.py',
      codeLocation: 'app/codeReview/',
      networkMode: 'PUBLIC',
      protocol: 'HTTP',
    });
  });

  test('lifecycle is idle 900 / max 1800 (D-32, S-204 D2)', () => {
    expect(runtime.lifecycleConfiguration).toEqual({
      idleRuntimeSessionTimeout: 900,
      maxLifetime: 1800,
    });
  });

  test('uses the dedicated execution role', () => {
    expect(runtime.executionRoleArn).toBe(ROLE_ARN);
  });

  const env: Record<string, string> = Object.fromEntries(
    runtime.envVars.map((e: { name: string; value: string }) => [e.name, e.value])
  );

  test('sets the spec §9 v1.8 env vars (TC-217-23, CT-21)', () => {
    expect(env).toEqual({
      SUPABASE_URL: 'https://hegxeycmbmjfgzqpdiik.supabase.co',
      SUPABASE_KEY_SECRET_ID: 'agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY',
      ANTHROPIC_API_KEY_SECRET_ID: ANTHROPIC_KEY_SECRET_ID,
      MODEL_ID,
      PANEL_BASE_URL: 'https://dt-agent-fleet-panel.fly.dev',
      AWS_REGION: 'us-east-1', // spec §9: Secrets Manager only; AgentCore also injects it
    });
  });

  test('MODEL_ID is an Anthropic model ID: never an ARN or a Bedrock ID (CT-21)', () => {
    expect(env.MODEL_ID).toBe('claude-sonnet-5-5');
    expect(env.MODEL_ID).not.toMatch(/^arn:/);
    expect(env.MODEL_ID).not.toMatch(/^(us\.|eu\.|apac\.|global\.)|^[a-z]+\.[a-z]/);
  });

  test('carries no key and no retired price env (D-87, D-88; TC-217-23)', () => {
    for (const name of ['PRICE_INPUT_PER_MTOK', 'PRICE_OUTPUT_PER_MTOK', 'ANTHROPIC_API_KEY']) {
      expect(env).not.toHaveProperty(name);
    }
    expect(Object.keys(env).filter(k => k.startsWith('PRICE_'))).toEqual([]);
    for (const value of Object.values(env)) expect(value).not.toMatch(/sk-ant-/);
    expect(JSON.stringify(spec)).not.toMatch(/sk-ant-/);
  });
});

describe('synthesized stack (AC-2)', () => {
  const app = new cdk.App();
  const stack = new AgentCoreStack(app, 'CodeReviewTest', {
    spec,
    env: { account: ACCOUNT, region: 'us-east-1' },
  });
  const template = Template.fromStack(stack);

  test('creates no IAM role for the runtime', () => {
    const roles = template.findResources('AWS::IAM::Role');
    const runtimeRoles = Object.values(roles).filter(r =>
      JSON.stringify(r).includes('bedrock-agentcore.amazonaws.com')
    );
    expect(runtimeRoles).toHaveLength(0);
  });

  test('grants no bedrock: action anywhere in the stack', () => {
    const policies = {
      ...template.findResources('AWS::IAM::Policy'),
      ...template.findResources('AWS::IAM::ManagedPolicy'),
    };
    for (const p of Object.values(policies)) {
      expect(JSON.stringify(p)).not.toMatch(/"bedrock:/);
    }
  });

  test('no bedrock: action string anywhere in the synthesized template (TC-217-22, SN-16)', () => {
    // Covers inline Role `Policies` and any other resource shape, not only
    // AWS::IAM::Policy/ManagedPolicy. IAM action names are case-insensitive.
    // `bedrock-agentcore:` baseline actions do not match.
    const synthesized = JSON.stringify(template.toJSON());
    expect(synthesized).not.toMatch(/"bedrock:/i);
    expect(synthesized).not.toMatch(/foundation-model\/|inference-profile\//);
  });

  test('the runtime resource uses the imported role', () => {
    const runtimes = template.findResources('AWS::BedrockAgentCore::Runtime');
    expect(Object.keys(runtimes)).toHaveLength(1);
    const props = Object.values(runtimes)[0].Properties;
    expect(JSON.stringify(props.RoleArn)).toContain('agent-fleet-code-review-runtime');
    expect(props.LifecycleConfiguration).toEqual({
      IdleRuntimeSessionTimeout: 900,
      MaxLifetime: 1800,
    });
  });

  test('the synthesized runtime env equals agentcore.json, with no key or price (TC-217-24)', () => {
    const runtimes = template.findResources('AWS::BedrockAgentCore::Runtime');
    const props = Object.values(runtimes)[0].Properties;
    const synthesized = JSON.stringify(props.EnvironmentVariables ?? {});
    for (const e of runtime.envVars as { name: string; value: string }[]) {
      expect(synthesized).toContain(JSON.stringify(e.name));
      expect(synthesized).toContain(JSON.stringify(e.value));
    }
    expect(synthesized).not.toMatch(/PRICE_|"ANTHROPIC_API_KEY"|sk-ant-/);
  });
});

describe('runtime-role-policy.json (AC-2, spec §7.2 v1.8, AC-17 IAM half)', () => {
  const policy = readJson(POLICY_PATH);
  const statements: Statement[] = policy.Statement;
  const allActions = statements.flatMap(s => asList(s.Action));

  test('every statement is an Allow', () => {
    for (const s of statements) expect(s.Effect).toBe('Allow');
  });

  test('no bedrock: action at all (D-74, TC-217-22, SN-16)', () => {
    expect(allActions.filter(a => a.toLowerCase().startsWith('bedrock:'))).toEqual([]);
    expect(JSON.stringify(policy)).not.toMatch(/"bedrock:/);
    expect(JSON.stringify(policy)).not.toMatch(/foundation-model|inference-profile/);
  });

  test('Secrets Manager: GetSecretValue on exactly the Supabase key, App PEM and Anthropic key (D-88, TC-217-21)', () => {
    const sm = statements.filter(s => asList(s.Action).some(a => a.startsWith('secretsmanager:')));
    expect(sm).toHaveLength(1);
    expect(asList(sm[0].Action)).toEqual(['secretsmanager:GetSecretValue']);
    expect([...asList(sm[0].Resource)].sort()).toEqual([...SECRET_ARNS].sort());
  });

  test('no secret ARN has a wildcard: every grant names its full suffix', () => {
    const sm = statements.find(s => asList(s.Action).includes('secretsmanager:GetSecretValue'))!;
    for (const arn of asList(sm.Resource)) {
      expect(arn).not.toMatch(/[*?]/);
      expect(arn).toMatch(/-[A-Za-z0-9]{6}$/);
    }
  });

  test("the code-review key is not the bug-fix agent's key (D-50, D-88)", () => {
    const sm = statements.find(s => asList(s.Action).includes('secretsmanager:GetSecretValue'))!;
    expect(ANTHROPIC_KEY_SECRET_ID).not.toBe(BUG_FIX_KEY_SECRET_ID);
    for (const arn of asList(sm.Resource)) expect(arn).not.toContain(`:secret:${BUG_FIX_KEY_SECRET_ID}-`);
  });

  test('the Anthropic key secret is the one the runtime reads (env ANTHROPIC_API_KEY_SECRET_ID)', () => {
    const id = runtime.envVars.find((e: { name: string }) => e.name === 'ANTHROPIC_API_KEY_SECRET_ID')?.value;
    expect(id).toBe(ANTHROPIC_KEY_SECRET_ID);
    expect(ANTHROPIC_KEY_SECRET_ARN).toContain(`:secret:${id}-`);
  });

  test('the v1.0 applied record is history: it still holds the DeepSeek grant v1.8 removes', () => {
    const applied = readJson(path.join(CHANGE_DIR, 'role-policy.json'));
    const appliedActions = applied.Statement.flatMap((s: Statement) => asList(s.Action));
    expect(appliedActions).toContain('bedrock:InvokeModel');
    // Every other v1.0 statement carries over unchanged.
    const keep = (st: Statement[]) =>
      st.filter(s => !asList(s.Action).some(a => a.startsWith('bedrock:') || a.startsWith('secretsmanager:')));
    expect(keep(statements)).toEqual(keep(applied.Statement));
  });

  test('KMS: Decrypt only through ECR', () => {
    const kms = statements.filter(s => asList(s.Action).some(a => a.startsWith('kms:')));
    expect(kms).toHaveLength(1);
    expect(asList(kms[0].Action)).toEqual(['kms:Decrypt']);
    expect(kms[0].Condition).toEqual({ StringEquals: { 'kms:ViaService': 'ecr.us-east-1.amazonaws.com' } });
    for (const arn of asList(kms[0].Resource)) {
      expect(arn).toMatch(new RegExp(`^arn:aws:kms:us-east-1:${ACCOUNT}:key/(\\*|[0-9a-f-]{36})$`));
    }
  });

  test('ECR pull is scoped to the codereview repository', () => {
    const pull = statements.filter(s => asList(s.Action).includes('ecr:BatchGetImage'));
    expect(pull).toHaveLength(1);
    expect(asList(pull[0].Resource)).toEqual([`arn:aws:ecr:us-east-1:${ACCOUNT}:repository/codereview/*`]);
  });

  test('no other actions: the runtime baseline plus Secrets Manager, KMS via ECR and ECR pull', () => {
    expect([...new Set(allActions)].sort()).toEqual(
      [
        'bedrock-agentcore:GetConfigurationBundle',
        'bedrock-agentcore:GetConfigurationBundleVersion',
        'bedrock-agentcore:ListConfigurationBundleVersions',
        'bedrock-agentcore:ListConfigurationBundles',
        'ecr:BatchCheckLayerAvailability',
        'ecr:BatchGetImage',
        'ecr:GetAuthorizationToken',
        'ecr:GetDownloadUrlForLayer',
        'kms:Decrypt',
        'logs:CreateLogGroup',
        'logs:CreateLogStream',
        'logs:DescribeLogGroups',
        'logs:DescribeLogStreams',
        'logs:FilterLogEvents',
        'logs:GetLogEvents',
        'logs:PutLogEvents',
        'logs:PutResourcePolicy',
        'secretsmanager:GetSecretValue',
        'xray:PutTelemetryRecords',
        'xray:PutTraceSegments',
      ].sort()
    );
    expect(allActions.some(a => a.includes('*'))).toBe(false);
  });

  test('the trust policy admits only AgentCore in this account', () => {
    const trust = readJson(path.join(CHANGE_DIR, 'role-trust.json'));
    expect(trust.Statement).toHaveLength(1);
    expect(trust.Statement[0]).toMatchObject({
      Effect: 'Allow',
      Principal: { Service: 'bedrock-agentcore.amazonaws.com' },
      Action: 'sts:AssumeRole',
      Condition: {
        StringEquals: { 'aws:SourceAccount': ACCOUNT },
        ArnLike: { 'aws:SourceArn': `arn:aws:bedrock-agentcore:us-east-1:${ACCOUNT}:*` },
      },
    });
  });
});
