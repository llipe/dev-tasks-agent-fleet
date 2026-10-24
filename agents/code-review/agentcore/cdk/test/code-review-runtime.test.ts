// S-214 AC-1/AC-2: the code-review runtime config and its least-privilege role.
//
// The runtime uses a dedicated, hand-made role (`executionRoleArn`), so the
// AgentCore L3 construct imports it read-only and attaches nothing. That is
// what keeps the construct's default `bedrock:InvokeModel*` grant on every
// foundation model off this agent. The role's permissions live in the
// ChangeId record and are pinned here.
import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import * as fs from 'fs';
import * as path from 'path';
import { AgentCoreStack } from '../lib/cdk-stack';

const AGENTCORE_DIR = path.resolve(__dirname, '..', '..');
const REPO_ROOT = path.resolve(AGENTCORE_DIR, '..', '..', '..');
const CHANGE_DIR = path.join(REPO_ROOT, 'infra', 'changes', '20261024-code-review-runtime');

const ACCOUNT = '755641879575';
const ROLE_ARN = `arn:aws:iam::${ACCOUNT}:role/agent-fleet-code-review-runtime`;
// D-59: DeepSeek V3.2, on-demand in us-east-1 only (no inference profile).
const MODEL_ID = 'deepseek.v3.2';
const MODEL_ARNS = ['arn:aws:bedrock:us-east-1::foundation-model/deepseek.v3.2'];
const SECRET_ARNS = [
  `arn:aws:secretsmanager:us-east-1:${ACCOUNT}:secret:agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY-wS5xrJ`,
  `arn:aws:secretsmanager:us-east-1:${ACCOUNT}:secret:agent-fleet/prod/GITHUB_APP_PRIVATE_KEY-t4sXT2`,
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

  test('sets the required env vars (spec §9), MODEL_ID a model or system profile ID, never an ARN (DR-8, D-59)', () => {
    const env = Object.fromEntries(runtime.envVars.map((e: { name: string; value: string }) => [e.name, e.value]));
    expect(env).toEqual({
      SUPABASE_URL: 'https://hegxeycmbmjfgzqpdiik.supabase.co',
      SUPABASE_KEY_SECRET_ID: 'agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY',
      MODEL_ID,
      PANEL_BASE_URL: 'https://dt-agent-fleet-panel.fly.dev',
    });
    expect(env.MODEL_ID).not.toMatch(/^arn:/);
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
});

describe('role-policy.json (AC-2, spec §7.2)', () => {
  const policy = readJson(path.join(CHANGE_DIR, 'role-policy.json'));
  const statements: Statement[] = policy.Statement;
  const allActions = statements.flatMap(s => asList(s.Action));

  test('every statement is an Allow', () => {
    for (const s of statements) expect(s.Effect).toBe('Allow');
  });

  test('Bedrock: InvokeModel only, on exactly the DeepSeek V3.2 model ARN (D-59)', () => {
    const bedrock = statements.filter(s => asList(s.Action).some(a => a.startsWith('bedrock:')));
    expect(bedrock).toHaveLength(1);
    expect(asList(bedrock[0].Action)).toEqual(['bedrock:InvokeModel']);
    expect([...asList(bedrock[0].Resource)].sort()).toEqual([...MODEL_ARNS].sort());
    for (const arn of asList(bedrock[0].Resource)) expect(arn).not.toContain('*');
  });

  test('Secrets Manager: GetSecretValue on exactly the Supabase key and App PEM', () => {
    const sm = statements.filter(s => asList(s.Action).some(a => a.startsWith('secretsmanager:')));
    expect(sm).toHaveLength(1);
    expect(asList(sm[0].Action)).toEqual(['secretsmanager:GetSecretValue']);
    expect([...asList(sm[0].Resource)].sort()).toEqual([...SECRET_ARNS].sort());
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

  test('no other actions: the full action set is the runtime baseline plus the three grants', () => {
    expect([...new Set(allActions)].sort()).toEqual(
      [
        'bedrock-agentcore:GetConfigurationBundle',
        'bedrock-agentcore:GetConfigurationBundleVersion',
        'bedrock-agentcore:ListConfigurationBundleVersions',
        'bedrock-agentcore:ListConfigurationBundles',
        'bedrock:InvokeModel',
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
