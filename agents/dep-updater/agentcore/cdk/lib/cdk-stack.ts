import {
  AgentCoreApplication,
  AgentCoreMcp,
  AgentCorePaymentManager,
  AgentCorePaymentConnector,
  type AgentCoreProjectSpec,
  type AgentCoreMcpSpec,
  type CustomJWTAuthorizerConfig,
  type HarnessDeploymentConfig,
} from '@aws/agentcore-cdk';
import { CfnOutput, Stack, type StackProps } from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import {
  AGENT_EXEC_FORBIDDEN_ATTRIBUTES,
  AGENT_EXEC_WRITE_ATTRIBUTES,
  FLEET_GITHUB_SECRET_NAME_PREFIX,
  FLEET_TABLE_NAME,
} from './fleet-iam-attributes';

/**
 * Harness deployment config: role-scoped fields (for IAM role + container build)
 * plus the full validated spec + its config directory so the L3 construct can
 * synthesize the AWS::BedrockAgentCore::Harness resource.
 */
export type HarnessConfig = HarnessDeploymentConfig;

export interface PaymentConnectorSpec {
  name: string;
  provider: 'CoinbaseCDP' | 'StripePrivy';
  credentialProviderArn: string;
}

export interface PaymentSpec {
  name: string;
  description?: string;
  authorizerType: 'AWS_IAM' | 'CUSTOM_JWT';
  authorizerConfiguration?: { customJWTAuthorizer: CustomJWTAuthorizerConfig };
  autoPayment?: boolean;
  paymentToolAllowlist?: string[];
  networkPreferences?: string[];
  connectors: PaymentConnectorSpec[];
}

export interface AgentCoreStackProps extends StackProps {
  /**
   * The AgentCore project specification containing agents, memories, and credentials.
   */
  spec: AgentCoreProjectSpec;
  /**
   * The MCP specification containing gateways and servers.
   */
  mcpSpec?: AgentCoreMcpSpec;
  /**
   * Credential provider ARNs from deployed state, keyed by credential name.
   */
  credentials?: Record<string, { credentialProviderArn: string; clientSecretArn?: string }>;
  /**
   * Harness role configurations.
   */
  harnesses?: HarnessConfig[];
  /**
   * Parsed connectorParameters for non-S3 KB data sources, keyed by
   * connectorConfigFile path. Forwarded to AgentCoreApplication.
   */
  connectorParametersByFile?: Record<string, Record<string, unknown>>;
  /**
   * Payment specifications with resolved credential provider ARNs.
   */
  paymentSpec?: PaymentSpec[];
}

function toCdkId(name: string): string {
  return name.replace(/_/g, '');
}

/**
 * Decide whether a deployed runtime should receive payment env vars + IAM grants.
 * Payments today only ships a runtime shim for Python HTTP runtimes; injecting
 * AGENTCORE_PAYMENT_* env vars into TypeScript / MCP / A2A / AGUI runtimes
 * would surface env vars they cannot consume and would dilute least-privilege
 * IAM grants for runtimes that never call ProcessPayment.
 */
function isPaymentEligibleAgent(agent: { entrypoint?: string; protocol?: string }): boolean {
  if (agent.protocol && agent.protocol !== 'HTTP') {
    return false;
  }
  const entrypoint = typeof agent.entrypoint === 'string' ? agent.entrypoint : '';
  const entrypointFile = entrypoint.split(':')[0] ?? '';
  return entrypointFile.endsWith('.py');
}

/**
 * CDK Stack that deploys AgentCore infrastructure.
 *
 * This is a thin wrapper that instantiates L3 constructs.
 * All resource logic and outputs are contained within the L3 constructs.
 */
export class AgentCoreStack extends Stack {
  /** The AgentCore application containing all agent environments */
  public readonly application: AgentCoreApplication;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    const { spec, mcpSpec, credentials, harnesses, connectorParametersByFile, paymentSpec } = props;

    // Create AgentCoreApplication with all agents and harness roles
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const appProps: Record<string, unknown> = { spec };
    if (harnesses?.length) {
      appProps.harnesses = harnesses;
    }
    if (connectorParametersByFile && Object.keys(connectorParametersByFile).length > 0) {
      appProps.connectorParametersByFile = connectorParametersByFile;
    }
    if (credentials) {
      appProps.credentials = credentials;
    }
    this.application = new AgentCoreApplication(this, 'Application', appProps as any);

    // Fleet data-plane grants on each runtime's AgentCore-provisioned execution
    // role. Applied before payments so the grants exist regardless of whether a
    // payment manager is configured.
    this.grantFleetDataPlaneAccess();

    // Create AgentCoreMcp if there are gateways configured
    if (mcpSpec?.agentCoreGateways && mcpSpec.agentCoreGateways.length > 0) {
      new AgentCoreMcp(this, 'Mcp', {
        projectName: spec.name,
        mcpSpec,
        agentCoreApplication: this.application,
        credentials,
        projectTags: spec.tags,
      });
    }

    // Create payment infrastructure via CFN constructs
    if (paymentSpec && paymentSpec.length > 0) {
      for (const payment of paymentSpec) {
        const mgrId = toCdkId(payment.name);
        const manager = new AgentCorePaymentManager(this, `Payment${mgrId}`, {
          projectName: spec.name,
          name: payment.name,
          authorizerType: payment.authorizerType,
          description: payment.description,
          authorizerConfiguration: payment.authorizerConfiguration,
          tags: spec.tags,
        });

        const prefix = `AGENTCORE_PAYMENT_${payment.name.toUpperCase().replace(/-/g, '_')}`;

        // Wire env vars from construct output tokens into eligible agent environments only.
        // See isPaymentEligibleAgent — non-Python or non-HTTP runtimes have no shim that
        // can consume these env vars, and giving them sts:AssumeRole on the
        // ProcessPaymentRole would broaden the privilege surface unnecessarily.
        for (const env of this.application.environments.values()) {
          if (!isPaymentEligibleAgent(env.agent)) {
            continue;
          }
          env.runtime.addEnvironmentVariable(`${prefix}_MANAGER_ARN`, manager.paymentManagerArn);
          env.runtime.addEnvironmentVariable(`${prefix}_PROCESS_PAYMENT_ROLE_ARN`, manager.processPaymentRoleArn);

          // Grant runtime execution role permission to assume the ProcessPaymentRole.
          // The ProcessPaymentRole's trust policy allows AccountRootPrincipal, but the
          // caller still needs sts:AssumeRole on its own role to perform the assumption.
          env.runtime.role.addToPrincipalPolicy(
            new iam.PolicyStatement({
              actions: ['sts:AssumeRole'],
              resources: [manager.processPaymentRoleArn],
            })
          );

          // Grant payment data-plane actions directly to the runtime role.
          //
          // NOTE: This deviates from the canonical role model in the AgentCore Payments
          // beta guide, which assigns Get/List/Create instrument+session actions to a
          // separate ManagementRole and limits the agent's role to ProcessPayment only.
          // The current SDK plugin (AgentCorePaymentsPlugin.generate_payment_header)
          // calls GetPaymentInstrument internally during the 402 auto-pay path, so the
          // runtime role needs read access. CreatePaymentSession is included so
          // `agentcore invoke --auto-session` works without a separate ManagementRole
          // call. Tighten this if the SDK is updated to accept pre-fetched instrument
          // details and split create-session into a backend-only flow.
          env.runtime.role.addToPrincipalPolicy(
            new iam.PolicyStatement({
              actions: [
                'bedrock-agentcore:GetPaymentInstrument',
                'bedrock-agentcore:ListPaymentInstruments',
                'bedrock-agentcore:GetPaymentInstrumentBalance',
                'bedrock-agentcore:GetPaymentSession',
                'bedrock-agentcore:ListPaymentSessions',
                'bedrock-agentcore:CreatePaymentSession',
                'bedrock-agentcore:ProcessPayment',
              ],
              resources: [manager.paymentManagerArn, `${manager.paymentManagerArn}/*`],
            })
          );

          if (payment.autoPayment !== undefined) {
            env.runtime.addEnvironmentVariable(`${prefix}_AUTO_PAYMENT`, String(payment.autoPayment));
          }
          if (payment.paymentToolAllowlist) {
            env.runtime.addEnvironmentVariable(`${prefix}_TOOL_ALLOWLIST`, payment.paymentToolAllowlist.join(','));
          }
          if (payment.networkPreferences) {
            env.runtime.addEnvironmentVariable(`${prefix}_NETWORK_PREFERENCES`, payment.networkPreferences.join(','));
          }
          if (payment.authorizerType === 'CUSTOM_JWT') {
            env.runtime.addEnvironmentVariable(`${prefix}_AUTH_MODE`, 'bearer');
          }
        }

        // Create connectors for this manager
        for (const connector of payment.connectors) {
          const connId = toCdkId(connector.name);
          const conn = new AgentCorePaymentConnector(this, `Payment${mgrId}${connId}`, {
            projectName: spec.name,
            paymentManager: manager,
            connectorName: connector.name,
            connectorType: connector.provider,
            credentialProviderArn: connector.credentialProviderArn,
          });

          // Wire first connector's ID as env var (eligible agents only)
          if (connector === payment.connectors[0]) {
            for (const env of this.application.environments.values()) {
              if (!isPaymentEligibleAgent(env.agent)) continue;
              env.runtime.addEnvironmentVariable(`${prefix}_CONNECTOR_ID`, conn.paymentConnectorId);
            }
          }

          new CfnOutput(this, `Payment${mgrId}${connId}ConnectorId`, {
            value: conn.paymentConnectorId,
          });
        }

        // CFN Outputs for post-deploy state parsing
        new CfnOutput(this, `Payment${mgrId}ManagerArn`, {
          value: manager.paymentManagerArn,
        });
        new CfnOutput(this, `Payment${mgrId}ManagerId`, {
          value: manager.paymentManagerId,
        });
        new CfnOutput(this, `Payment${mgrId}ProcessPaymentRoleArn`, {
          value: manager.processPaymentRoleArn,
        });
        new CfnOutput(this, `Payment${mgrId}ResourceRetrievalRoleArn`, {
          value: manager.resourceRetrievalRoleArn,
        });
      }
    }

    // Stack-level output
    new CfnOutput(this, 'StackNameOutput', {
      description: 'Name of the CloudFormation Stack',
      value: this.stackName,
    });
  }

  /**
   * Grant every runtime execution role the fleet data-plane permissions.
   *
   * AgentCore provisions its own execution role for each runtime and never
   * assumes `agent-fleet-agent-exec-role` from infra/lib/iam-stack.ts, so that
   * role is orphaned and THIS stack governs the deployed agent's real
   * permissions. Without these grants the agent fails at get_github_token()
   * with AccessDenied on secretsmanager:GetSecretValue, then again on
   * dynamodb:UpdateItem when stamping its outcome.
   *
   * The three DynamoDB statements replicate the write-separation control that
   * infra/lib/iam-stack.ts enforces for S-004. A plain `dynamodb:UpdateItem`
   * grant would silently discard it and let the agent flip `enabled` or rewrite
   * `params`, so all three must stay together. Attribute names come from
   * lib/fleet-iam-attributes.ts, which is drift-guarded against @fleet/shared.
   */
  private grantFleetDataPlaneAccess(): void {
    const tableArn = `arn:aws:dynamodb:${this.region}:${this.account}:table/${FLEET_TABLE_NAME}`;
    const tableIndexArn = `${tableArn}/index/*`;
    const githubSecretArn = `arn:aws:secretsmanager:${this.region}:${this.account}:secret:${FLEET_GITHUB_SECRET_NAME_PREFIX}*`;

    for (const env of this.application.environments.values()) {
      // The GitHub credential. The wildcard spans dep-agent/github-pat (current)
      // and dep-agent/github-app (post-migration) so the PAT to GitHub App
      // cutover needs no IAM change between creating the App secret and flipping
      // GITHUB_SECRET_ID.
      //
      // TIGHTEN AFTER CUTOVER: once the App secret is live and the PAT secret is
      // deleted, narrow FLEET_GITHUB_SECRET_NAME_PREFIX to the single full
      // secret name so this resolves to exactly one ARN.
      env.runtime.role.addToPrincipalPolicy(
        new iam.PolicyStatement({
          sid: 'FleetSecretsManagerRead',
          effect: iam.Effect.ALLOW,
          actions: ['secretsmanager:GetSecretValue'],
          resources: [githubSecretArn],
        })
      );

      // Reads are unconstrained: outcome_store.py checks the config row exists
      // before updating it, and discovery queries the GSI.
      env.runtime.role.addToPrincipalPolicy(
        new iam.PolicyStatement({
          sid: 'FleetDynamoDBRead',
          effect: iam.Effect.ALLOW,
          actions: ['dynamodb:GetItem', 'dynamodb:Query'],
          resources: [tableArn, tableIndexArn],
        })
      );

      // Outcome stamping only. ForAllValues means every attribute named by the
      // request must be in the allowlist, so an update that also touches any
      // other attribute is denied outright.
      env.runtime.role.addToPrincipalPolicy(
        new iam.PolicyStatement({
          sid: 'FleetDynamoDBUpdateOutcome',
          effect: iam.Effect.ALLOW,
          actions: ['dynamodb:UpdateItem'],
          resources: [tableArn],
          conditions: {
            'ForAllValues:StringEquals': {
              'dynamodb:Attributes': AGENT_EXEC_WRITE_ATTRIBUTES,
            },
          },
        })
      );

      // PutItem replaces the whole item, which would erase enabled/params
      // regardless of any attribute condition. Never available to an agent.
      env.runtime.role.addToPrincipalPolicy(
        new iam.PolicyStatement({
          sid: 'FleetDenyPutItem',
          effect: iam.Effect.DENY,
          actions: ['dynamodb:PutItem'],
          resources: [tableArn],
        })
      );

      // Defence in depth: even if the allow condition above is ever loosened,
      // writing a control-plane-only attribute stays denied.
      env.runtime.role.addToPrincipalPolicy(
        new iam.PolicyStatement({
          sid: 'FleetDenyWriteForbiddenAttributes',
          effect: iam.Effect.DENY,
          actions: ['dynamodb:UpdateItem'],
          resources: [tableArn],
          conditions: {
            'ForAnyValue:StringEquals': {
              'dynamodb:Attributes': AGENT_EXEC_FORBIDDEN_ATTRIBUTES,
            },
          },
        })
      );
    }
  }
}
