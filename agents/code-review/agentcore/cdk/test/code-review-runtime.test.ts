/**
 * S-214 (#416) — CDK assertion tests for the `code_review` runtime.
 *
 * Test plan rows (workstream/test-plan-prd-code-review-agent.md §4.11):
 * - TC-214-01: runtime shape (Container, ARM64 build, PUBLIC, HTTP, idle 900, maxLifetime 1800, env).
 * - TC-214-02: no secret material in agentcore.json, the CDK sources, or the Dockerfile.
 * - TC-214-03: the runtime role's policy is exactly the expected statements.
 * - TC-214-04: no `*` Bedrock resource, no `bedrock:*`, no extra AWS write actions,
 *   no Anthropic or DeepSeek model ARN.
 *
 * The spec is read from the real `agentcore.json` through the same ConfigIO the
 * CLI uses, so a schema-invalid file fails here too. Expected ARNs are literals
 * on purpose: changing MODEL_ID or a secret must change this file (IAM review).
 */
import * as fs from 'fs';
import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Template } from 'aws-cdk-lib/assertions';
import { ConfigIO, type AgentCoreProjectSpec } from '@aws/agentcore-cdk';
import { AgentCoreStack } from '../lib/cdk-stack';

const ACCOUNT = '123456789012';
const REGION = 'us-east-1';
const CONFIG_ROOT = path.resolve(__dirname, '..', '..');
const PROJECT_ROOT = path.resolve(CONFIG_ROOT, '..');
const AGENTCORE_JSON = path.join(CONFIG_ROOT, 'agentcore.json');

// Candidate Sol IDs (unconfirmed; fixed at the S-214 "model access" deploy step).
const MODEL_ID = 'us.openai.gpt-5-6-sol-v1:0';
const SOL_FOUNDATION_MODEL = 'openai.gpt-5-6-sol-v1:0';
const EXPECTED_BEDROCK_RESOURCES = [
  `arn:aws:bedrock:us-east-1:${ACCOUNT}:inference-profile/${MODEL_ID}`,
  `arn:aws:bedrock:us-east-1::foundation-model/${SOL_FOUNDATION_MODEL}`,
  `arn:aws:bedrock:us-east-2::foundation-model/${SOL_FOUNDATION_MODEL}`,
  `arn:aws:bedrock:us-west-2::foundation-model/${SOL_FOUNDATION_MODEL}`,
].sort();
const EXPECTED_SECRET_RESOURCES = [
  `arn:aws:secretsmanager:us-east-1:${ACCOUNT}:secret:agent-fleet/prod/GITHUB_APP_PRIVATE_KEY-??????`,
  `arn:aws:secretsmanager:us-east-1:${ACCOUNT}:secret:agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY-??????`,
].sort();

interface NormalizedStatement {
  actions: string[];
  resources: string[];
}

// The exact runtime-role policy. ECR, KMS (ECR image key), X-Ray and Logs are
// what the AgentCore construct itself needs to pull the image and emit
// telemetry; Bedrock and Secrets Manager are the agent's own grants (spec §7.2).
const EXPECTED_STATEMENTS: NormalizedStatement[] = [
  { actions: ['ecr:GetAuthorizationToken'], resources: ['*'] },
  {
    actions: ['ecr:BatchCheckLayerAvailability', 'ecr:BatchGetImage', 'ecr:GetDownloadUrlForLayer'],
    resources: ['<ECR_REPOSITORY>'],
  },
  { actions: ['kms:Decrypt'], resources: ['<ECR_KMS_KEY>'] },
  { actions: ['xray:PutTelemetryRecords', 'xray:PutTraceSegments'], resources: ['*'] },
  { actions: ['logs:DescribeLogGroups'], resources: ['*'] },
  {
    actions: [
      'logs:CreateLogGroup',
      'logs:CreateLogStream',
      'logs:DescribeLogStreams',
      'logs:FilterLogEvents',
      'logs:GetLogEvents',
      'logs:PutLogEvents',
      'logs:PutResourcePolicy',
    ],
    resources: [`arn:aws:logs:us-east-1:${ACCOUNT}:log-group:/aws/bedrock-agentcore/runtimes/*`],
  },
  { actions: ['bedrock:InvokeModel'], resources: EXPECTED_BEDROCK_RESOURCES },
  { actions: ['secretsmanager:GetSecretValue'], resources: EXPECTED_SECRET_RESOURCES },
];

type Resources = Record<string, { Type: string; Properties?: Record<string, any> }>;

let template: Template;
let resources: Resources;
let spec: AgentCoreProjectSpec;

beforeAll(async () => {
  spec = await new ConfigIO({ baseDir: CONFIG_ROOT }).readProjectSpec();
  const cdkJson = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', 'cdk.json'), 'utf8'));
  const app = new cdk.App({ context: cdkJson.context });
  const stack = new AgentCoreStack(app, 'AgentCore-codereview-test', {
    spec,
    env: { account: ACCOUNT, region: REGION },
  });
  template = Template.fromStack(stack);
  resources = template.toJSON().Resources as Resources;
});

function ofType(type: string): [string, Record<string, any>][] {
  return Object.entries(resources)
    .filter(([, r]) => r.Type === type)
    .map(([id, r]) => [id, r.Properties ?? {}]);
}

function runtimeRoleId(): string {
  const roles = ofType('AWS::IAM::Role').filter(([, props]) =>
    JSON.stringify(props.AssumeRolePolicyDocument ?? {}).includes('bedrock-agentcore.amazonaws.com')
  );
  expect(roles).toHaveLength(1);
  return roles[0][0];
}

function attachedPolicies(roleId: string): Record<string, any>[] {
  return ofType('AWS::IAM::Policy')
    .filter(([, props]) => JSON.stringify(props.Roles ?? []).includes(`"${roleId}"`))
    .map(([, props]) => props);
}

function normalizeResource(value: unknown): string {
  if (typeof value === 'string') return value;
  const getAtt = (value as { 'Fn::GetAtt'?: [string, string] })['Fn::GetAtt'];
  if (getAtt && getAtt[1] === 'Arn') {
    const type = resources[getAtt[0]]?.Type;
    if (type === 'AWS::ECR::Repository') return '<ECR_REPOSITORY>';
    if (type === 'AWS::KMS::Key') return '<ECR_KMS_KEY>';
  }
  return `<UNRECOGNIZED:${JSON.stringify(value)}>`;
}

function asArray<T>(value: T | T[]): T[] {
  return Array.isArray(value) ? value : [value];
}

function runtimeStatements(): Record<string, any>[] {
  const policies = attachedPolicies(runtimeRoleId());
  return policies.flatMap(p => asArray(p.PolicyDocument.Statement));
}

function normalized(): NormalizedStatement[] {
  return runtimeStatements().map(s => ({
    actions: asArray<string>(s.Action).slice().sort(),
    resources: asArray<unknown>(s.Resource).map(normalizeResource).sort(),
  }));
}

function key(s: NormalizedStatement): string {
  return JSON.stringify([s.actions, s.resources]);
}

function runtimeProps(): Record<string, any> {
  const runtimes = ofType('AWS::BedrockAgentCore::Runtime');
  expect(runtimes).toHaveLength(1);
  return runtimes[0][1];
}

describe('agentcore.json (TC-214-01)', () => {
  test('defines one Container runtime `code_review` from app/codeReview/main.py', () => {
    expect(spec.name).toBe('codereview');
    expect(spec.runtimes).toHaveLength(1);
    const rt = spec.runtimes[0];
    expect(rt.name).toBe('code_review');
    expect(rt.build).toBe('Container');
    expect(rt.entrypoint).toBe('main.py');
    expect(rt.codeLocation).toBe('app/codeReview/');
    expect(rt.runtimeVersion).toBe('PYTHON_3_14');
    expect(rt.networkMode).toBe('PUBLIC');
    expect(rt.protocol).toBe('HTTP');
    expect(fs.existsSync(path.join(PROJECT_ROOT, 'app', 'codeReview', 'Dockerfile'))).toBe(true);
    expect(fs.existsSync(path.join(PROJECT_ROOT, 'app', 'codeReview', 'main.py'))).toBe(true);
  });

  test('MODEL_ID is a model or system-defined inference-profile ID, never an ARN', () => {
    const env = Object.fromEntries((spec.runtimes[0].envVars ?? []).map(e => [e.name, e.value]));
    expect(env.MODEL_ID).toBe(MODEL_ID);
    expect(env.MODEL_ID.startsWith('arn:')).toBe(false);
    expect(env.MODEL_ID).not.toMatch(/application-inference-profile/);
  });
});

describe('runtime resource (TC-214-01)', () => {
  test('lifecycle is idle 900 s and maxLifetime 1800 s', () => {
    expect(runtimeProps().LifecycleConfiguration).toEqual({
      IdleRuntimeSessionTimeout: 900,
      MaxLifetime: 1800,
    });
  });

  test('PUBLIC network, HTTP protocol, container artifact, runtime name', () => {
    const props = runtimeProps();
    expect(props.AgentRuntimeName).toBe('codereview_code_review');
    expect(props.NetworkConfiguration).toEqual({ NetworkMode: 'PUBLIC' });
    // HTTP is the default: the construct omits ProtocolConfiguration for it.
    expect(props.ProtocolConfiguration).toBeUndefined();
    expect(props.AgentRuntimeArtifact.ContainerConfiguration).toBeDefined();
    expect(props.AgentRuntimeArtifact.CodeConfiguration).toBeUndefined();
  });

  test('the image is built on an ARM64 CodeBuild environment', () => {
    const projects = ofType('AWS::CodeBuild::Project');
    expect(projects.length).toBeGreaterThan(0);
    for (const [, props] of projects) {
      expect(props.Environment.Type).toBe('ARM_CONTAINER');
    }
  });

  test('environment variables per spec §9 and config.py', () => {
    const env = runtimeProps().EnvironmentVariables as Record<string, string>;
    expect(env).toEqual({
      SUPABASE_URL: 'https://hegxeycmbmjfgzqpdiik.supabase.co',
      SUPABASE_KEY_SECRET_ID: 'agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY',
      MODEL_ID,
      PANEL_BASE_URL: 'https://dt-agent-fleet-panel.fly.dev',
      AWS_REGION: 'us-east-1',
      HEARTBEAT_INTERVAL: '120',
      IDLE_SESSION_TIMEOUT: '900',
      MAX_LIFETIME: '1800',
    });
  });
});

describe('runtime role policy (TC-214-03)', () => {
  test('the role carries no managed or inline policies of its own', () => {
    const role = resources[runtimeRoleId()].Properties ?? {};
    expect(role.ManagedPolicyArns).toBeUndefined();
    expect(role.Policies).toBeUndefined();
  });

  test('exactly one policy document is attached to the runtime role', () => {
    expect(attachedPolicies(runtimeRoleId())).toHaveLength(1);
  });

  test('statements are exactly the expected actions and resources', () => {
    expect(normalized().map(key).sort()).toEqual(EXPECTED_STATEMENTS.map(key).sort());
  });

  test('every statement is an unconditional Allow', () => {
    for (const s of runtimeStatements()) {
      expect(s.Effect).toBe('Allow');
      expect(s.Condition).toBeUndefined();
      expect(s.NotAction).toBeUndefined();
      expect(s.NotResource).toBeUndefined();
    }
  });
});

describe('least privilege (TC-214-04)', () => {
  test('no wildcard Bedrock resource and no bedrock:* or streaming action', () => {
    for (const s of normalized()) {
      const bedrock = s.actions.some(a => a.startsWith('bedrock'));
      if (bedrock) {
        expect(s.actions).toEqual(['bedrock:InvokeModel']);
        for (const r of s.resources) expect(r).not.toContain('*');
      }
      for (const r of s.resources) {
        if (r.includes(':bedrock:')) expect(r).not.toContain('*');
      }
    }
  });

  test('no Anthropic or DeepSeek model ARN (the DeepSeek statement is commented out)', () => {
    const all = JSON.stringify(runtimeStatements());
    expect(all).not.toMatch(/anthropic\./);
    expect(all).not.toMatch(/deepseek/i);
  });

  test('no AgentCore control-plane, IAM, S3 or Secrets Manager write action', () => {
    const actions = normalized().flatMap(s => s.actions);
    for (const a of actions) {
      expect(a).not.toMatch(/^bedrock-agentcore:/);
      expect(a).not.toMatch(/^(iam|s3|sts):/);
      expect(a).not.toMatch(/\*$/);
    }
    expect(actions.filter(a => a.startsWith('secretsmanager:'))).toEqual(['secretsmanager:GetSecretValue']);
  });
});

describe('no secret material (TC-214-02)', () => {
  const SECRET_PATTERNS: [string, RegExp][] = [
    ['GitHub token', /gh[pousr]_[A-Za-z0-9]{20,}/],
    ['PEM block', /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
    ['JWT', /eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/],
    ['AWS access key', /\b(AKIA|ASIA)[A-Z0-9]{16}\b/],
    ['AWS secret key assignment', /aws_secret_access_key\s*[=:]/i],
  ];
  const files = [
    AGENTCORE_JSON,
    path.join(PROJECT_ROOT, 'app', 'codeReview', 'Dockerfile'),
    path.resolve(__dirname, '..', 'bin', 'cdk.ts'),
    ...fs.readdirSync(path.resolve(__dirname, '..', 'lib')).map(f => path.resolve(__dirname, '..', 'lib', f)),
  ];

  test.each(files.map(f => [path.relative(PROJECT_ROOT, f), f]))('%s holds only secret IDs', (_name, file) => {
    const text = fs.readFileSync(file, 'utf8');
    for (const [label, pattern] of SECRET_PATTERNS) {
      expect({ label, match: pattern.test(text) }).toEqual({ label, match: false });
    }
  });
});

describe('override guard (DR-2)', () => {
  // restrictRuntimeRole replaces the whole statement list, so a grant the construct
  // (or later stack wiring: credentials, payments, connections) adds to the runtime
  // role would otherwise vanish silently. Synth must fail instead.
  function stackWithExtraStatement(statement: iam.PolicyStatement): cdk.Stack {
    const cdkJson = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', 'cdk.json'), 'utf8'));
    const app = new cdk.App({ context: cdkJson.context });
    const stack = new AgentCoreStack(app, 'AgentCore-codereview-guard', {
      spec,
      env: { account: ACCOUNT, region: REGION },
    });
    for (const env of stack.application.environments.values()) {
      env.runtime.role.addToPrincipalPolicy(statement);
    }
    return stack;
  }

  test('an unexpected grant on the runtime role fails synth', () => {
    const stack = stackWithExtraStatement(
      new iam.PolicyStatement({ actions: ['sts:AssumeRole'], resources: ['arn:aws:iam::123456789012:role/x'] })
    );
    expect(() => Template.fromStack(stack)).toThrow(/unexpected statement.*sts:AssumeRole/s);
  });

  test('a credential-provider grant added by the construct fails synth', () => {
    const stack = stackWithExtraStatement(
      new iam.PolicyStatement({
        actions: ['bedrock-agentcore:GetResourceApiKey'],
        resources: ['*'],
      })
    );
    expect(() => Template.fromStack(stack)).toThrow(/bedrock-agentcore:GetResourceApiKey/);
  });

  test('the shipped configuration synthesizes without tripping the guard', () => {
    const cdkJson = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', 'cdk.json'), 'utf8'));
    const app = new cdk.App({ context: cdkJson.context });
    const stack = new AgentCoreStack(app, 'AgentCore-codereview-clean', {
      spec,
      env: { account: ACCOUNT, region: REGION },
    });
    expect(() => Template.fromStack(stack)).not.toThrow();
  });
});
