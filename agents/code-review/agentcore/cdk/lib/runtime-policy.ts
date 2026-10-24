/**
 * Least-privilege policy for the `code_review` runtime role (S-214, spec §7.2).
 *
 * The `@aws/agentcore-cdk` runtime construct grants every runtime a broad default
 * policy: `bedrock:InvokeModel`/`InvokeModelWithResponseStream`/`CountTokens` on
 * `foundation-model/*` and `inference-profile/*`, plus Configuration Bundle
 * create/update/delete. Spec §7.2 allows this runtime Bedrock access to the Sol
 * model only and no AWS writes, so `restrictRuntimeRole` replaces the role's
 * policy document with the exact list below:
 *
 * - kept from the construct, unchanged: the ECR pull grants (plus `kms:Decrypt` on
 *   the ECR repository's own key, needed to pull an encrypted image), X-Ray trace
 *   upload, and CloudWatch Logs on the runtime log-group namespace;
 * - dropped: the wildcard Bedrock statement and the Configuration Bundle actions;
 * - added: `bedrock:InvokeModel` on the Sol inference profile and its
 *   foundation-model ARNs, and `secretsmanager:GetSecretValue` on the two secrets.
 *
 * Converse needs `bedrock:InvokeModel` only; the adapter never streams
 * (`bedrock_adapter.py` calls `converse`, not `converse_stream`), so
 * `InvokeModelWithResponseStream` is not granted.
 *
 * The CDK assertion test (`test/code-review-runtime.test.ts`) pins the result.
 */
import { ArnFormat, Stack } from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import { AgentEcrRepository, type AgentEnvironment } from '@aws/agentcore-cdk';

/**
 * Sol system-defined (cross-Region) inference-profile ID. Must equal `MODEL_ID`
 * in `agentcore.json`. CANDIDATE, NOT CONFIRMED: the spec (§17 Q1) fixes the real
 * ID at the S-214 "model access" deploy step (`aws bedrock list-inference-profiles`).
 * Never an application-inference-profile ARN (spec §9, S-210 DR-8).
 */
export const SOL_INFERENCE_PROFILE_ID = 'us.openai.gpt-5-6-sol-v1:0';

/** Sol foundation-model ID the profile routes to. CANDIDATE, see above. */
export const SOL_FOUNDATION_MODEL_ID = 'openai.gpt-5-6-sol-v1:0';

/**
 * Regions the `us.` profile can route to. A cross-Region profile needs
 * `InvokeModel` on the foundation model in every destination Region.
 * CANDIDATE: confirm against `aws bedrock get-inference-profile` at deploy.
 */
export const SOL_PROFILE_REGIONS = ['us-east-1', 'us-east-2', 'us-west-2'];

// DeepSeek V4 Pro fallback (D-18). Disabled until needed: switching is a MODEL_ID
// change plus uncommenting these and the statement in `bedrockStatement`.
// export const DEEPSEEK_FOUNDATION_MODEL_ID = 'deepseek.v4-pro-v1:0';
// export const DEEPSEEK_REGIONS = ['us-east-1'];

/**
 * Secrets the runtime reads, by name. The `-??????` suffix matches the six random
 * characters Secrets Manager appends to every secret ARN, so each grant covers
 * exactly one secret. The PEM's full ARN lives in
 * `github_installations.private_key_secret_arn`.
 */
export const SECRET_NAMES = ['agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY', 'agent-fleet/prod/GITHUB_APP_PRIVATE_KEY'];

function bedrockStatement(stack: Stack): iam.PolicyStatement {
  const resources = [
    stack.formatArn({
      service: 'bedrock',
      resource: 'inference-profile',
      resourceName: SOL_INFERENCE_PROFILE_ID,
      arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
    }),
    ...SOL_PROFILE_REGIONS.map(
      region => `arn:${stack.partition}:bedrock:${region}::foundation-model/${SOL_FOUNDATION_MODEL_ID}`
    ),
    // DeepSeek V4 Pro (D-18), disabled:
    // ...DEEPSEEK_REGIONS.map(
    //   region => `arn:${stack.partition}:bedrock:${region}::foundation-model/${DEEPSEEK_FOUNDATION_MODEL_ID}`
    // ),
  ];
  return new iam.PolicyStatement({ sid: 'InvokeSolModel', actions: ['bedrock:InvokeModel'], resources });
}

function secretsStatement(stack: Stack): iam.PolicyStatement {
  return new iam.PolicyStatement({
    sid: 'ReadRuntimeSecrets',
    actions: ['secretsmanager:GetSecretValue'],
    resources: SECRET_NAMES.map(name =>
      stack.formatArn({
        service: 'secretsmanager',
        resource: 'secret',
        resourceName: `${name}-??????`,
        arnFormat: ArnFormat.COLON_RESOURCE_NAME,
      })
    ),
  });
}

/** The construct's own grants that the runtime needs to start and emit telemetry. */
function platformStatements(stack: Stack, ecr: AgentEcrRepository): iam.PolicyStatement[] {
  const logGroupArn = `arn:${stack.partition}:logs:${stack.region}:${stack.account}:log-group:/aws/bedrock-agentcore/runtimes/*`;
  return [
    // GetAuthorizationToken has no resource-level permissions (AWS API).
    new iam.PolicyStatement({ sid: 'EcrAuth', actions: ['ecr:GetAuthorizationToken'], resources: ['*'] }),
    new iam.PolicyStatement({
      sid: 'EcrPull',
      actions: ['ecr:BatchGetImage', 'ecr:GetDownloadUrlForLayer', 'ecr:BatchCheckLayerAvailability'],
      resources: [ecr.repository.repositoryArn],
    }),
    new iam.PolicyStatement({ sid: 'EcrImageKey', actions: ['kms:Decrypt'], resources: [ecr.encryptionKey.keyArn] }),
    new iam.PolicyStatement({
      sid: 'XRay',
      actions: ['xray:PutTraceSegments', 'xray:PutTelemetryRecords'],
      resources: ['*'],
    }),
    // DescribeLogGroups requires `*` (AWS limitation).
    new iam.PolicyStatement({ sid: 'LogsDescribe', actions: ['logs:DescribeLogGroups'], resources: ['*'] }),
    new iam.PolicyStatement({
      sid: 'RuntimeLogs',
      actions: [
        'logs:CreateLogGroup',
        'logs:CreateLogStream',
        'logs:DescribeLogStreams',
        'logs:PutLogEvents',
        'logs:GetLogEvents',
        'logs:FilterLogEvents',
        'logs:PutResourcePolicy',
      ],
      resources: [logGroupArn],
    }),
  ];
}

/**
 * Replace the runtime role's construct-generated policy document with the exact
 * least-privilege statement list. Throws at synth if the construct tree no
 * longer has the shape this relies on (an `@aws/agentcore-cdk` upgrade), so the
 * override can never silently stop applying.
 */
export function restrictRuntimeRole(environment: AgentEnvironment): void {
  const stack = Stack.of(environment);
  const role = environment.runtime.role;
  if (!(role instanceof iam.Role)) {
    throw new Error('code_review: expected a CDK-managed runtime role, found an imported one');
  }
  const ecr = environment.node.children.find((c): c is AgentEcrRepository => c instanceof AgentEcrRepository);
  if (!ecr) {
    throw new Error('code_review: no AgentEcrRepository under the agent environment (Container build expected)');
  }
  const policy = role.node.tryFindChild('DefaultPolicy');
  const cfnPolicy = policy?.node.defaultChild;
  if (!(cfnPolicy instanceof iam.CfnPolicy)) {
    throw new Error('code_review: runtime role has no DefaultPolicy to restrict');
  }
  const statements = [...platformStatements(stack, ecr), bedrockStatement(stack), secretsStatement(stack)];
  cfnPolicy.addPropertyOverride(
    'PolicyDocument.Statement',
    statements.map(s => s.toStatementJson())
  );
}
