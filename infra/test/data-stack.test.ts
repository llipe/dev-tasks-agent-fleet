import { describe, it, expect } from "vitest";
import * as cdk from "aws-cdk-lib";
import { Template, Match } from "aws-cdk-lib/assertions";
import { DataStack, TABLE_NAME, GSI1_NAME } from "../lib/data-stack.js";

describe("DataStack", () => {
  function createTemplate(): Template {
    const app = new cdk.App();
    const stack = new DataStack(app, "TestDataStack");
    return Template.fromStack(stack);
  }

  describe("table configuration", () => {
    it("creates a DynamoDB table with correct name", () => {
      const template = createTemplate();
      template.hasResourceProperties("AWS::DynamoDB::Table", {
        TableName: TABLE_NAME,
      });
    });

    it("has pk/sk string key schema", () => {
      const template = createTemplate();
      template.hasResourceProperties("AWS::DynamoDB::Table", {
        KeySchema: [
          { AttributeName: "pk", KeyType: "HASH" },
          { AttributeName: "sk", KeyType: "RANGE" },
        ],
        AttributeDefinitions: Match.arrayWith([
          { AttributeName: "pk", AttributeType: "S" },
          { AttributeName: "sk", AttributeType: "S" },
        ]),
      });
    });

    it("uses on-demand billing", () => {
      const template = createTemplate();
      template.hasResourceProperties("AWS::DynamoDB::Table", {
        BillingMode: "PAY_PER_REQUEST",
      });
    });

    it("has PITR enabled", () => {
      const template = createTemplate();
      template.hasResourceProperties("AWS::DynamoDB::Table", {
        PointInTimeRecoverySpecification: {
          PointInTimeRecoveryEnabled: true,
        },
      });
    });

    it("has deletion protection enabled", () => {
      const template = createTemplate();
      template.hasResourceProperties("AWS::DynamoDB::Table", {
        DeletionProtectionEnabled: true,
      });
    });
  });

  describe("GSI1 (inverted index)", () => {
    it("creates GSI1 with pk=sk, sk=pk", () => {
      const template = createTemplate();
      template.hasResourceProperties("AWS::DynamoDB::Table", {
        GlobalSecondaryIndexes: Match.arrayWith([
          Match.objectLike({
            IndexName: GSI1_NAME,
            KeySchema: [
              { AttributeName: "sk", KeyType: "HASH" },
              { AttributeName: "pk", KeyType: "RANGE" },
            ],
          }),
        ]),
      });
    });

    it("GSI1 has ALL projection", () => {
      const template = createTemplate();
      template.hasResourceProperties("AWS::DynamoDB::Table", {
        GlobalSecondaryIndexes: Match.arrayWith([
          Match.objectLike({
            IndexName: GSI1_NAME,
            Projection: { ProjectionType: "ALL" },
          }),
        ]),
      });
    });
  });

  describe("exports", () => {
    it("exports TABLE_NAME constant matching the table", () => {
      expect(TABLE_NAME).toBe("agent-fleet-config");
    });

    it("exports GSI1_NAME constant", () => {
      expect(GSI1_NAME).toBe("GSI1");
    });
  });

  describe("removal policy", () => {
    it("retains table on stack deletion", () => {
      const template = createTemplate();
      const tables = template.findResources("AWS::DynamoDB::Table");
      const tableKeys = Object.keys(tables);
      expect(tableKeys.length).toBe(1);
      const tableKey = tableKeys[0];
      const table = tableKey ? tables[tableKey] : undefined;
      expect(table?.DeletionPolicy).toBe("Retain");
      expect(table?.UpdateReplacePolicy).toBe("Retain");
    });
  });
});
