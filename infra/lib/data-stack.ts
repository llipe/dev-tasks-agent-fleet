import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import type { Construct } from "constructs";
import { TABLE_NAME, GSI1_NAME } from "@fleet/shared";

// Re-export for use in tests and other infra modules
export { TABLE_NAME, GSI1_NAME };

/**
 * DataStack — DynamoDB table for agent fleet configuration.
 *
 * Table: agent-fleet-config
 *   pk (String) — partition key (e.g., SUBJECT#owner/repo)
 *   sk (String) — sort key (e.g., META, AGENT#dep-updater, CONFIG)
 *
 * GSI1 — inverted index
 *   GSI1pk = sk (from base table)
 *   GSI1sk = pk (from base table)
 *   Projection: ALL
 *
 * This enables bi-directional queries:
 *   - Base table: all agents/meta for a subject (pk=SUBJECT#repo)
 *   - GSI1: all subjects for an agent (pk=AGENT#name), all subjects (pk=META)
 */
export class DataStack extends cdk.Stack {
  public readonly table: dynamodb.Table;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    this.table = new dynamodb.Table(this, "AgentFleetConfigTable", {
      tableName: TABLE_NAME,
      partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "sk", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      deletionProtection: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    this.table.addGlobalSecondaryIndex({
      indexName: GSI1_NAME,
      partitionKey: { name: "sk", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "pk", type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // Outputs for cross-stack references
    new cdk.CfnOutput(this, "TableName", {
      value: this.table.tableName,
      description: "DynamoDB table name for agent fleet configuration",
    });

    new cdk.CfnOutput(this, "TableArn", {
      value: this.table.tableArn,
      description: "DynamoDB table ARN",
    });
  }
}
