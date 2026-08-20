import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as events from "aws-cdk-lib/aws-events";
import * as targets from "aws-cdk-lib/aws-events-targets";
import type * as iam from "aws-cdk-lib/aws-iam";
import type * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import type { Construct } from "constructs";
import { TABLE_NAME } from "@fleet/shared";

export interface OrchestrationStackProps extends cdk.StackProps {
  /** The DynamoDB table for scope queries and stamping */
  table: dynamodb.ITable;
  /** The orchestrator IAM role */
  orchestratorRole: iam.IRole;
  /** Agent runtime ARN for InvokeAgentRuntime */
  agentRuntimeArn: string;
}

/**
 * OrchestrationStack — EventBridge Scheduler + Orchestrator Lambda.
 *
 * One EventBridge Scheduler rule per agent triggers the Lambda on a cron.
 * The Lambda reads scope from DynamoDB, stamps lifecycle fields, and invokes agents.
 */
export class OrchestrationStack extends cdk.Stack {
  public readonly orchestratorFn: lambda.Function;

  constructor(scope: Construct, id: string, props: OrchestrationStackProps) {
    super(scope, id, props);

    const { table: _table, orchestratorRole, agentRuntimeArn } = props;

    // Orchestrator Lambda function
    this.orchestratorFn = new lambda.Function(this, "OrchestratorFunction", {
      functionName: "agent-fleet-orchestrator",
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "handler.handler",
      code: lambda.Code.fromAsset("orchestrator/dist"),
      timeout: cdk.Duration.seconds(60),
      memorySize: 256,
      role: orchestratorRole as iam.Role,
      environment: {
        TABLE_NAME,
        AGENT_RUNTIME_ARN: agentRuntimeArn,
        NODE_OPTIONS: "--enable-source-maps",
      },
      description: "Orchestrator: reads DynamoDB scope, stamps lifecycle, invokes agents",
    });

    // EventBridge rule — triggers every 6 hours for dep-updater
    const rule = new events.Rule(this, "DepUpdaterScheduleRule", {
      ruleName: "agent-fleet-dep-updater-schedule",
      description: "Triggers orchestrator Lambda for dep-updater agent every 6 hours",
      schedule: events.Schedule.cron({ minute: "0", hour: "0/6" }),
      enabled: true,
    });

    rule.addTarget(
      new targets.LambdaFunction(this.orchestratorFn, {
        event: events.RuleTargetInput.fromObject({
          agent: "dep-updater",
          scheduledAt: events.EventField.time,
        }),
      }),
    );
  }
}
