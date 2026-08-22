import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { AgentCoreStack } from '../lib/cdk-stack';
import {
  AGENT_EXEC_WRITE_ATTRIBUTES,
  AGENT_EXEC_FORBIDDEN_ATTRIBUTES,
  FLEET_GITHUB_SECRET_NAME_PREFIX,
  FLEET_TABLE_NAME,
} from '../lib/fleet-iam-attributes';

const EMPTY_SPEC = {
  name: 'testproject',
  version: 1,
  managedBy: 'CDK' as const,
  runtimes: [],
  memories: [],
  credentials: [],
  evaluators: [],
  onlineEvalConfigs: [],
  configBundles: [],
  policyEngines: [],
  payments: [],
  agentCoreGateways: [],
  mcpRuntimeTools: [],
  unassignedTargets: [],
  datasets: [],
  knowledgeBases: [],
};

/**
 * A Container runtime whose build context is the two-file fixture directory, so
 * synth-time asset staging stays instant. Paths resolve against the repository
 * root (the parent of `agentcore/`), matching the CLI's resolveCodeLocation.
 */
const RUNTIME_SPEC = {
  ...EMPTY_SPEC,
  runtimes: [
    {
      name: 'dep_updater',
      build: 'Container' as const,
      entrypoint: 'main.py',
      codeLocation: 'agentcore/cdk/test/fixtures/container-context',
      buildContextPath: 'agentcore/cdk/test/fixtures/container-context',
      dockerfile: 'Dockerfile',
      runtimeVersion: 'PYTHON_3_13' as const,
      networkMode: 'PUBLIC' as const,
      protocol: 'HTTP' as const,
    },
  ],
};

/**
 * Synthesize with the same IAM feature flag the real `cdk.json` sets, so the
 * assertions below see the policy document that actually gets deployed rather
 * than an un-minimized approximation of it.
 */
function templateWithRuntime(): Template {
  const app = new cdk.App({ context: { '@aws-cdk/aws-iam:minimizePolicies': true } });
  const stack = new AgentCoreStack(app, 'TestStack', {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    spec: RUNTIME_SPEC as any,
    env: { account: '123456789012', region: 'us-east-1' },
  });
  return Template.fromStack(stack);
}

type Statement = Record<string, unknown>;

/** Every inline policy statement in the stack, flattened. */
function allPolicyStatements(template: Template): Statement[] {
  const statements: Statement[] = [];
  for (const resource of Object.values(template.findResources('AWS::IAM::Policy'))) {
    const props = resource.Properties as Record<string, unknown>;
    const doc = props.PolicyDocument as Record<string, unknown>;
    statements.push(...(doc.Statement as Statement[]));
  }
  return statements;
}

function statementBySid(template: Template, sid: string): Statement {
  const found = allPolicyStatements(template).filter(s => s.Sid === sid);
  expect(found).toHaveLength(1);
  return found[0]!;
}

function actionsOf(statement: Statement): string[] {
  const action = statement.Action;
  return Array.isArray(action) ? (action as string[]) : [action as string];
}

function conditionAttributes(statement: Statement, operator: string): string[] | undefined {
  const condition = statement.Condition as Record<string, Record<string, string[]>> | undefined;
  return condition?.[operator]?.['dynamodb:Attributes'];
}

/** JSON.stringify of a CFN value, for substring assertions on Fn::Join structures. */
function flatten(value: unknown): string {
  return JSON.stringify(value);
}

test('AgentCoreStack synthesizes with empty spec', () => {
  const app = new cdk.App();
  const stack = new AgentCoreStack(app, 'TestStack', {
    spec: EMPTY_SPEC,
  });
  const template = Template.fromStack(stack);
  template.hasOutput('StackNameOutput', {
    Description: 'Name of the CloudFormation Stack',
  });
});

/**
 * The AgentCore runtime execution role is created by the L3 construct and only
 * carries the AgentCore defaults. Everything the fleet data plane needs is
 * granted here, which is why these assertions mirror infra/test/iam-stack.test.ts:
 * this stack — not AgentFleetIamStack — governs the deployed agent's real
 * permissions.
 */
describe('runtime execution role — fleet data-plane grants', () => {
  it('allows GetSecretValue scoped to the dep-agent/github-* secrets', () => {
    const stmt = statementBySid(templateWithRuntime(), 'FleetSecretsManagerRead');
    expect(stmt.Effect).toBe('Allow');
    expect(actionsOf(stmt)).toContain('secretsmanager:GetSecretValue');
    expect(flatten(stmt.Resource)).toContain('secret:dep-agent/github-*');
  });

  it('does not grant secret access beyond the dep-agent/github- prefix', () => {
    const stmt = statementBySid(templateWithRuntime(), 'FleetSecretsManagerRead');
    const resource = flatten(stmt.Resource);
    expect(resource).not.toContain('secret:*');
    expect(resource).not.toBe('"*"');
  });

  it('allows read access to the config table and its indexes', () => {
    const stmt = statementBySid(templateWithRuntime(), 'FleetDynamoDBRead');
    expect(stmt.Effect).toBe('Allow');
    expect(actionsOf(stmt)).toEqual(
      expect.arrayContaining(['dynamodb:GetItem', 'dynamodb:Query'])
    );
    const resource = flatten(stmt.Resource);
    expect(resource).toContain(`table/${FLEET_TABLE_NAME}`);
    expect(resource).toContain(`table/${FLEET_TABLE_NAME}/index/*`);
  });

  it('allows UpdateItem only for the agent-exec attribute allowlist', () => {
    const stmt = statementBySid(templateWithRuntime(), 'FleetDynamoDBUpdateOutcome');
    expect(stmt.Effect).toBe('Allow');
    expect(actionsOf(stmt)).toEqual(['dynamodb:UpdateItem']);
    expect(conditionAttributes(stmt, 'ForAllValues:StringEquals')).toEqual([
      ...AGENT_EXEC_WRITE_ATTRIBUTES,
    ]);
  });

  it('scopes the UpdateItem allow to the table itself, not its indexes', () => {
    const stmt = statementBySid(templateWithRuntime(), 'FleetDynamoDBUpdateOutcome');
    expect(flatten(stmt.Resource)).not.toContain('/index/');
  });

  it('explicitly denies PutItem on the config table', () => {
    const stmt = statementBySid(templateWithRuntime(), 'FleetDenyPutItem');
    expect(stmt.Effect).toBe('Deny');
    expect(actionsOf(stmt)).toContain('dynamodb:PutItem');
    expect(flatten(stmt.Resource)).toContain(`table/${FLEET_TABLE_NAME}`);
  });

  it('explicitly denies UpdateItem touching enabled or params', () => {
    const stmt = statementBySid(templateWithRuntime(), 'FleetDenyWriteForbiddenAttributes');
    expect(stmt.Effect).toBe('Deny');
    expect(actionsOf(stmt)).toContain('dynamodb:UpdateItem');
    expect(conditionAttributes(stmt, 'ForAnyValue:StringEquals')).toEqual([
      ...AGENT_EXEC_FORBIDDEN_ATTRIBUTES,
    ]);
  });

  it('never grants PutItem or DeleteItem in any Allow statement', () => {
    for (const stmt of allPolicyStatements(templateWithRuntime())) {
      if (stmt.Effect !== 'Allow') continue;
      expect(actionsOf(stmt)).not.toContain('dynamodb:PutItem');
      expect(actionsOf(stmt)).not.toContain('dynamodb:DeleteItem');
    }
  });

  it('never grants an unconditional UpdateItem', () => {
    for (const stmt of allPolicyStatements(templateWithRuntime())) {
      if (stmt.Effect !== 'Allow') continue;
      if (!actionsOf(stmt).includes('dynamodb:UpdateItem')) continue;
      expect(conditionAttributes(stmt, 'ForAllValues:StringEquals')).toEqual([
        ...AGENT_EXEC_WRITE_ATTRIBUTES,
      ]);
    }
  });

  it('grants nothing to a project with no runtimes', () => {
    const app = new cdk.App({ context: { '@aws-cdk/aws-iam:minimizePolicies': true } });
    const stack = new AgentCoreStack(app, 'EmptyStack', { spec: EMPTY_SPEC });
    const sids = allPolicyStatements(Template.fromStack(stack)).map(s => s.Sid);
    expect(sids).not.toContain('FleetDynamoDBUpdateOutcome');
  });
});

/**
 * Drift guard. The vended CDK app cannot import @fleet/shared (see the comment
 * in lib/fleet-iam-attributes.ts), so the allowlist is mirrored. This test reads
 * the real source of truth off disk and fails the moment the two diverge.
 * infra/test/vended-cdk-iam-drift.test.ts asserts the same invariant from the
 * workspace side, which is the copy CI runs.
 */
describe('fleet-iam-attributes mirror', () => {
  const SHARED_SRC = resolve(__dirname, '../../../../../packages/shared/src/iam-attributes.ts');
  const SHARED_KEYS = resolve(__dirname, '../../../../../packages/shared/src/keys.ts');

  /**
   * Read a string-literal array export, expanding `...OTHER_CONST` spreads so
   * the result is the same list TypeScript would produce. Reformatting
   * @fleet/shared — inlining a spread, say — must not change what this reads,
   * otherwise the guard could start demanding a policy that locks the agent out.
   */
  function parseArray(source: string, constName: string, seen: string[] = []): string[] {
    if (seen.includes(constName)) throw new Error(`circular spread through ${constName}`);
    const match = new RegExp(`export const ${constName}\\s*=\\s*\\[([^\\]]*)\\]`, 's').exec(source);
    if (!match?.[1]) throw new Error(`${constName} not found in @fleet/shared`);
    const values: string[] = [];
    for (const member of match[1].split(',')) {
      const literal = /['"]([^'"]+)['"]/.exec(member);
      if (literal?.[1]) {
        values.push(literal[1]);
        continue;
      }
      const spread = /\.\.\.\s*([A-Z0-9_]+)/.exec(member);
      if (spread?.[1]) values.push(...parseArray(source, spread[1], [...seen, constName]));
    }
    expect(values.length).toBeGreaterThan(0);
    return values;
  }

  it('AGENT_EXEC_WRITE_ATTRIBUTES equals the @fleet/shared allowlist', () => {
    const source = readFileSync(SHARED_SRC, 'utf-8');
    expect([...AGENT_EXEC_WRITE_ATTRIBUTES]).toEqual(
      parseArray(source, 'AGENT_EXEC_WRITE_ATTRIBUTES')
    );
  });

  /**
   * The deny list is CONTROL_PLANE_WRITE_ATTRIBUTES minus the key attributes.
   * The keys are excluded deliberately: DynamoDB counts pk/sk among
   * `dynamodb:Attributes` on every request, so a ForAnyValue deny naming them
   * would match every UpdateItem the agent makes.
   */
  it('AGENT_EXEC_FORBIDDEN_ATTRIBUTES equals the control-plane-only attributes', () => {
    const source = readFileSync(SHARED_SRC, 'utf-8');
    const keyAttributes = parseArray(source, 'KEY_ATTRIBUTES');
    const controlPlaneOnly = parseArray(source, 'CONTROL_PLANE_WRITE_ATTRIBUTES').filter(
      a => !keyAttributes.includes(a)
    );
    expect([...AGENT_EXEC_FORBIDDEN_ATTRIBUTES]).toEqual(controlPlaneOnly);
  });

  it('never denies a key attribute, which would block every agent write', () => {
    const keyAttributes = parseArray(readFileSync(SHARED_SRC, 'utf-8'), 'KEY_ATTRIBUTES');
    for (const key of keyAttributes) {
      expect(AGENT_EXEC_FORBIDDEN_ATTRIBUTES).not.toContain(key);
      expect(AGENT_EXEC_WRITE_ATTRIBUTES).toContain(key);
    }
  });

  it('FLEET_TABLE_NAME equals the @fleet/shared TABLE_NAME', () => {
    const source = readFileSync(SHARED_KEYS, 'utf-8');
    const match = /export const TABLE_NAME = "([^"]+)"/.exec(source);
    expect(FLEET_TABLE_NAME).toBe(match?.[1]);
  });

  it('never allows the agent to write enabled or params', () => {
    for (const forbidden of AGENT_EXEC_FORBIDDEN_ATTRIBUTES) {
      expect(AGENT_EXEC_WRITE_ATTRIBUTES).not.toContain(forbidden);
    }
  });

  it('FLEET_GITHUB_SECRET_NAME_PREFIX covers both the PAT and the App secret', () => {
    expect('dep-agent/github-pat'.startsWith(FLEET_GITHUB_SECRET_NAME_PREFIX)).toBe(true);
    expect('dep-agent/github-app'.startsWith(FLEET_GITHUB_SECRET_NAME_PREFIX)).toBe(true);
    // Must stay a real prefix, not a catch-all.
    expect(FLEET_GITHUB_SECRET_NAME_PREFIX).not.toBe('');
    expect('other-agent/github-pat'.startsWith(FLEET_GITHUB_SECRET_NAME_PREFIX)).toBe(false);
  });
});
