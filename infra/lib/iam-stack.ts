import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import type * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import type { Construct } from "constructs";
import {
  CONTROL_PLANE_WRITE_ATTRIBUTES,
  ORCHESTRATOR_WRITE_ATTRIBUTES,
  AGENT_EXEC_WRITE_ATTRIBUTES,
} from "@fleet/shared";

export interface IamStackProps extends cdk.StackProps {
  /** The DynamoDB table to scope permissions against */
  table: dynamodb.ITable;
}

/**
 * IamStack — Three IAM roles enforcing write separation.
 *
 * - control-plane-role: read + write scope config (enabled, params), NO InvokeAgentRuntime
 * - orchestrator-role: read + write run lifecycle (last_session_id, last_run_at, last_status), InvokeAgentRuntime
 * - agent-exec-role: UpdateItem on last_status and last_outcome_url ONLY, NO PutItem
 *
 * Write separation is enforced via `dynamodb:Attributes` condition keys
 * using `ForAllValues:StringEquals` to restrict which attributes each role can write.
 */
export class IamStack extends cdk.Stack {
  public readonly controlPlaneRole: iam.Role;
  public readonly orchestratorRole: iam.Role;
  public readonly agentExecRole: iam.Role;

  constructor(scope: Construct, id: string, props: IamStackProps) {
    super(scope, id, props);

    const { table } = props;
    const tableArn = table.tableArn;
    const gsiArn = `${tableArn}/index/*`;

    // ─── Control-Plane Role ───────────────────────────────────────────────
    // Fly OIDC provider — enables AssumeRoleWithWebIdentity from Fly Machines
    const flyOidcProvider = new iam.OpenIdConnectProvider(this, "FlyOidcProvider", {
      url: "https://oidc.fly.io/personal",
      clientIds: ["sts.amazonaws.com"],
    });

    this.controlPlaneRole = new iam.Role(this, "ControlPlaneRole", {
      roleName: "agent-fleet-control-plane-role",
      assumedBy: new iam.WebIdentityPrincipal(flyOidcProvider.openIdConnectProviderArn, {
        StringEquals: {
          "oidc.fly.io/personal:aud": "sts.amazonaws.com",
        },
        StringLike: {
          "oidc.fly.io/personal:sub": "personal:dt-agent-fleet-control-plane:*",
        },
      }),
      description:
        "Control plane role: read all, write scope config (enabled, params), no InvokeAgentRuntime",
    });

    // Read access to table and GSI
    this.controlPlaneRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "DynamoDBRead",
        effect: iam.Effect.ALLOW,
        actions: ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:BatchGetItem"],
        resources: [tableArn, gsiArn],
      }),
    );

    // Write access with attribute condition
    this.controlPlaneRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "DynamoDBWriteScopeConfig",
        effect: iam.Effect.ALLOW,
        actions: ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"],
        resources: [tableArn],
        conditions: {
          "ForAllValues:StringEquals": {
            "dynamodb:Attributes": [...CONTROL_PLANE_WRITE_ATTRIBUTES],
          },
        },
      }),
    );

    // Explicit deny on InvokeAgentRuntime
    this.controlPlaneRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "DenyInvokeAgentRuntime",
        effect: iam.Effect.DENY,
        actions: ["bedrock-agentcore:InvokeAgentRuntime"],
        resources: ["*"],
      }),
    );

    // CloudWatch Logs — read spans and agent application logs for the runs view
    this.controlPlaneRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "CloudWatchLogsRead",
        effect: iam.Effect.ALLOW,
        actions: [
          "logs:StartQuery",
          "logs:GetQueryResults",
          "logs:StopQuery",
          "logs:FilterLogEvents",
        ],
        resources: [
          `arn:aws:logs:${this.region}:${this.account}:log-group:aws/spans:*`,
          `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/depupdater_dep_updater*:*`,
        ],
      }),
    );

    // Resource Groups Tagging — discover agents by tag
    this.controlPlaneRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "TaggingRead",
        effect: iam.Effect.ALLOW,
        actions: ["tag:GetResources"],
        resources: ["*"],
      }),
    );

    // ─── Orchestrator Role ────────────────────────────────────────────────
    this.orchestratorRole = new iam.Role(this, "OrchestratorRole", {
      roleName: "agent-fleet-orchestrator-role",
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      description: "Orchestrator role: read all, write run lifecycle, InvokeAgentRuntime",
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole"),
      ],
    });

    // Read access to table and GSI
    this.orchestratorRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "DynamoDBRead",
        effect: iam.Effect.ALLOW,
        actions: ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:BatchGetItem"],
        resources: [tableArn, gsiArn],
      }),
    );

    // Write access constrained to orchestrator attributes
    this.orchestratorRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "DynamoDBWriteRunLifecycle",
        effect: iam.Effect.ALLOW,
        actions: ["dynamodb:UpdateItem"],
        resources: [tableArn],
        conditions: {
          "ForAllValues:StringEquals": {
            "dynamodb:Attributes": [...ORCHESTRATOR_WRITE_ATTRIBUTES],
          },
        },
      }),
    );

    // InvokeAgentRuntime permission
    this.orchestratorRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "InvokeAgentRuntime",
        effect: iam.Effect.ALLOW,
        actions: ["bedrock-agentcore:InvokeAgentRuntime"],
        resources: ["*"],
      }),
    );

    // ─── Agent Execution Role ─────────────────────────────────────────────
    this.agentExecRole = new iam.Role(this, "AgentExecRole", {
      roleName: "agent-fleet-agent-exec-role",
      assumedBy: new iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
      description:
        "Agent execution role: UpdateItem on last_status and last_outcome_url only, no PutItem",
    });

    // Read access to table (agent needs to verify item exists)
    this.agentExecRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "DynamoDBRead",
        effect: iam.Effect.ALLOW,
        actions: ["dynamodb:GetItem", "dynamodb:Query"],
        resources: [tableArn, gsiArn],
      }),
    );

    // UpdateItem constrained to agent-allowed attributes only
    this.agentExecRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "DynamoDBUpdateOutcome",
        effect: iam.Effect.ALLOW,
        actions: ["dynamodb:UpdateItem"],
        resources: [tableArn],
        conditions: {
          "ForAllValues:StringEquals": {
            "dynamodb:Attributes": [...AGENT_EXEC_WRITE_ATTRIBUTES],
          },
        },
      }),
    );

    // Secrets Manager read for GitHub App key
    this.agentExecRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "SecretsManagerRead",
        effect: iam.Effect.ALLOW,
        actions: ["secretsmanager:GetSecretValue"],
        resources: [`arn:aws:secretsmanager:${this.region}:${this.account}:secret:agent-fleet/*`],
      }),
    );

    // Explicit deny on PutItem — agent must never replace entire items
    this.agentExecRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "DenyPutItem",
        effect: iam.Effect.DENY,
        actions: ["dynamodb:PutItem"],
        resources: [tableArn],
      }),
    );

    // Explicit deny on writing forbidden attributes via UpdateItem
    // This is a defense-in-depth deny: even if the allow condition is bypassed,
    // writing enabled/params is still denied.
    this.agentExecRole.addToPolicy(
      new iam.PolicyStatement({
        sid: "DenyWriteForbiddenAttributes",
        effect: iam.Effect.DENY,
        actions: ["dynamodb:UpdateItem"],
        resources: [tableArn],
        conditions: {
          "ForAnyValue:StringEquals": {
            "dynamodb:Attributes": ["enabled", "params"],
          },
        },
      }),
    );

    // ─── Outputs ──────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, "ControlPlaneRoleArn", {
      value: this.controlPlaneRole.roleArn,
      description: "Control plane IAM role ARN",
    });

    new cdk.CfnOutput(this, "OrchestratorRoleArn", {
      value: this.orchestratorRole.roleArn,
      description: "Orchestrator IAM role ARN",
    });

    new cdk.CfnOutput(this, "AgentExecRoleArn", {
      value: this.agentExecRole.roleArn,
      description: "Agent execution IAM role ARN",
    });
  }
}
