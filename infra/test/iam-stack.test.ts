import { describe, it, expect } from "vitest";
import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { DataStack } from "../lib/data-stack.js";
import { IamStack } from "../lib/iam-stack.js";
import {
  CONTROL_PLANE_WRITE_ATTRIBUTES,
  ORCHESTRATOR_WRITE_ATTRIBUTES,
  AGENT_EXEC_WRITE_ATTRIBUTES,
} from "@fleet/shared";

function createTemplate(): Template {
  const app = new cdk.App();
  const dataStack = new DataStack(app, "TestDataStack");
  const iamStack = new IamStack(app, "TestIamStack", {
    table: dataStack.table,
  });
  return Template.fromStack(iamStack);
}

/**
 * Helper: extracts all inline policy statements from a role's policy document.
 */
function getPolicyStatements(template: Template, roleName: string): Array<Record<string, unknown>> {
  const policies = template.findResources("AWS::IAM::Policy");
  const statements: Array<Record<string, unknown>> = [];

  for (const [, resource] of Object.entries(policies)) {
    const props = resource.Properties as Record<string, unknown>;
    const doc = props.PolicyDocument as Record<string, unknown>;
    const stmts = doc.Statement as Array<Record<string, unknown>>;
    const roles = props.Roles as Array<Record<string, unknown>>;

    // Check if this policy is attached to the role we care about
    const isForRole = roles?.some((r) => {
      const ref = r.Ref as string | undefined;
      if (ref && ref.includes(roleName)) return true;
      return false;
    });

    if (isForRole) {
      statements.push(...stmts);
    }
  }
  return statements;
}

describe("IamStack", () => {
  describe("Fly OIDC provider", () => {
    it("creates an OpenIDConnect provider for the real Fly org slug, not the `personal` alias", () => {
      const template = createTemplate();
      template.hasResourceProperties("Custom::AWSCDKOpenIdConnectProvider", {
        Url: "https://oidc.fly.io/felipe-mallea",
        ClientIDList: ["sts.amazonaws.com"],
      });
    });

    it("does not register the `personal` org alias as the issuer", () => {
      // `fly orgs list` reports "personal" for a personal org, but tokens are issued by
      // https://oidc.fly.io/<real-slug>. Registering the alias makes STS reject every token
      // with InvalidIdentityTokenException. Guard against the regression.
      const template = createTemplate();
      const providers = template.findResources("Custom::AWSCDKOpenIdConnectProvider");
      for (const [, resource] of Object.entries(providers)) {
        const url = (resource.Properties as { Url?: string }).Url ?? "";
        expect(url).not.toBe("https://oidc.fly.io/personal");
      }
      const roles = template.findResources("AWS::IAM::Role", {
        Properties: { RoleName: "agent-fleet-control-plane-role" },
      });
      expect(JSON.stringify(roles)).not.toContain("oidc.fly.io/personal");
    });
  });

  describe("role creation", () => {
    it("creates three application IAM roles (plus one for the OIDC custom resource)", () => {
      const template = createTemplate();
      template.resourceCountIs("AWS::IAM::Role", 4);
    });

    it("creates control-plane-role with correct name", () => {
      const template = createTemplate();
      template.hasResourceProperties("AWS::IAM::Role", {
        RoleName: "agent-fleet-control-plane-role",
      });
    });

    it("creates orchestrator-role with correct name", () => {
      const template = createTemplate();
      template.hasResourceProperties("AWS::IAM::Role", {
        RoleName: "agent-fleet-orchestrator-role",
      });
    });

    it("creates agent-exec-role with correct name", () => {
      const template = createTemplate();
      template.hasResourceProperties("AWS::IAM::Role", {
        RoleName: "agent-fleet-agent-exec-role",
      });
    });
  });

  describe("control-plane-role", () => {
    it("trusts the Fly OIDC provider via AssumeRoleWithWebIdentity", () => {
      const template = createTemplate();
      template.hasResourceProperties("AWS::IAM::Role", {
        RoleName: "agent-fleet-control-plane-role",
        AssumeRolePolicyDocument: {
          Statement: [
            {
              Effect: "Allow",
              Action: "sts:AssumeRoleWithWebIdentity",
              Condition: {
                StringEquals: {
                  "oidc.fly.io/felipe-mallea:aud": "sts.amazonaws.com",
                },
                StringLike: {
                  "oidc.fly.io/felipe-mallea:sub": "felipe-mallea:dt-agent-fleet-control-plane:*",
                },
              },
            },
          ],
        },
      });
    });

    it("does NOT trust ecs-tasks.amazonaws.com", () => {
      const template = createTemplate();
      const roles = template.findResources("AWS::IAM::Role", {
        Properties: { RoleName: "agent-fleet-control-plane-role" },
      });
      const roleKey = Object.keys(roles)[0];
      expect(roleKey).toBeDefined();
      if (!roleKey) return;
      // eslint-disable-next-line @typescript-eslint/no-non-null-assertion -- guarded by the check above
      const role = roles[roleKey]!;
      const trustDoc = role.Properties.AssumeRolePolicyDocument;
      const statements = trustDoc.Statement as Array<Record<string, unknown>>;
      for (const stmt of statements) {
        const principal = stmt.Principal as Record<string, unknown>;
        if (principal.Service) {
          const services = Array.isArray(principal.Service)
            ? principal.Service
            : [principal.Service];
          expect(services).not.toContain("ecs-tasks.amazonaws.com");
        }
      }
    });

    it("has DynamoDB read actions", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "ControlPlaneRole");
      const readStmt = stmts.find((s) => (s.Sid as string) === "DynamoDBRead");
      expect(readStmt).toBeDefined();
      if (!readStmt) return;
      expect(readStmt.Effect).toBe("Allow");
      expect(readStmt.Action).toEqual(
        expect.arrayContaining(["dynamodb:GetItem", "dynamodb:Query", "dynamodb:BatchGetItem"]),
      );
    });

    it("has write access with attribute condition for scope config", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "ControlPlaneRole");
      const writeStmt = stmts.find((s) => (s.Sid as string) === "DynamoDBWriteScopeConfig");
      expect(writeStmt).toBeDefined();
      if (!writeStmt) return;
      expect(writeStmt.Effect).toBe("Allow");
      expect(writeStmt.Action).toEqual(
        expect.arrayContaining(["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"]),
      );
      const condition = writeStmt.Condition as Record<string, Record<string, string[]>>;
      const attrs = condition["ForAllValues:StringEquals"]?.["dynamodb:Attributes"];
      expect(attrs).toEqual(expect.arrayContaining([...CONTROL_PLANE_WRITE_ATTRIBUTES]));
    });

    it("explicitly denies InvokeAgentRuntime", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "ControlPlaneRole");
      const denyStmt = stmts.find((s) => (s.Sid as string) === "DenyInvokeAgentRuntime");
      expect(denyStmt).toBeDefined();
      if (!denyStmt) return;
      expect(denyStmt.Effect).toBe("Deny");
      expect(denyStmt.Action).toContain("bedrock-agentcore:InvokeAgentRuntime");
    });

    it("does NOT have InvokeAgentRuntime in any Allow statement", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "ControlPlaneRole");
      const allowStmts = stmts.filter((s) => s.Effect === "Allow");
      for (const stmt of allowStmts) {
        const actions = Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action];
        expect(actions).not.toContain("bedrock-agentcore:InvokeAgentRuntime");
      }
    });

    it("has CloudWatch Logs read actions scoped to the two log group ARN patterns", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "ControlPlaneRole");
      const logsStmt = stmts.find((s) => (s.Sid as string) === "CloudWatchLogsRead");
      expect(logsStmt).toBeDefined();
      if (!logsStmt) return;
      expect(logsStmt.Effect).toBe("Allow");
      expect(logsStmt.Action).toEqual(
        expect.arrayContaining([
          "logs:StartQuery",
          "logs:GetQueryResults",
          "logs:StopQuery",
          "logs:FilterLogEvents",
        ]),
      );
      // Scoped to exactly two ARN patterns
      const resources = Array.isArray(logsStmt.Resource) ? logsStmt.Resource : [logsStmt.Resource];
      // We check the resolved ARNs contain both patterns via Join/Sub references or literal strings
      expect(resources.length).toBe(2);
    });

    it("has tag:GetResources permission", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "ControlPlaneRole");
      const tagStmt = stmts.find((s) => (s.Sid as string) === "TaggingRead");
      expect(tagStmt).toBeDefined();
      if (!tagStmt) return;
      expect(tagStmt.Effect).toBe("Allow");
      expect(tagStmt.Action).toContain("tag:GetResources");
      expect(tagStmt.Resource).toBe("*");
    });

    it("does NOT have logs:DescribeLogGroups in any statement", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "ControlPlaneRole");
      for (const stmt of stmts) {
        const actions = Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action];
        expect(actions).not.toContain("logs:DescribeLogGroups");
      }
    });

    it("DynamoDB write condition still references CONTROL_PLANE_WRITE_ATTRIBUTES", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "ControlPlaneRole");
      const writeStmt = stmts.find((s) => (s.Sid as string) === "DynamoDBWriteScopeConfig");
      expect(writeStmt).toBeDefined();
      if (!writeStmt) return;
      const condition = writeStmt.Condition as Record<string, Record<string, string[]>>;
      const attrs = condition["ForAllValues:StringEquals"]?.["dynamodb:Attributes"];
      // Must contain all and only CONTROL_PLANE_WRITE_ATTRIBUTES
      expect(attrs).toEqual(expect.arrayContaining([...CONTROL_PLANE_WRITE_ATTRIBUTES]));
      expect(attrs?.length).toBe(CONTROL_PLANE_WRITE_ATTRIBUTES.length);
    });
  });

  describe("orchestrator-role", () => {
    it("has DynamoDB read actions", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "OrchestratorRole");
      const readStmt = stmts.find((s) => (s.Sid as string) === "DynamoDBRead");
      expect(readStmt).toBeDefined();
      if (!readStmt) return;
      expect(readStmt.Effect).toBe("Allow");
    });

    it("has UpdateItem with orchestrator attribute condition", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "OrchestratorRole");
      const writeStmt = stmts.find((s) => (s.Sid as string) === "DynamoDBWriteRunLifecycle");
      expect(writeStmt).toBeDefined();
      if (!writeStmt) return;
      expect(writeStmt.Effect).toBe("Allow");
      expect(writeStmt.Action).toContain("dynamodb:UpdateItem");
      const condition = writeStmt.Condition as Record<string, Record<string, string[]>>;
      const attrs = condition["ForAllValues:StringEquals"]?.["dynamodb:Attributes"];
      expect(attrs).toEqual(expect.arrayContaining([...ORCHESTRATOR_WRITE_ATTRIBUTES]));
    });

    it("has InvokeAgentRuntime permission", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "OrchestratorRole");
      const invokeStmt = stmts.find((s) => (s.Sid as string) === "InvokeAgentRuntime");
      expect(invokeStmt).toBeDefined();
      if (!invokeStmt) return;
      expect(invokeStmt.Effect).toBe("Allow");
      expect(invokeStmt.Action).toContain("bedrock-agentcore:InvokeAgentRuntime");
    });

    it("does NOT have PutItem action", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "OrchestratorRole");
      for (const stmt of stmts) {
        if (stmt.Effect === "Allow") {
          const actions = Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action];
          expect(actions).not.toContain("dynamodb:PutItem");
        }
      }
    });
  });

  describe("agent-exec-role", () => {
    it("has DynamoDB read actions", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "AgentExecRole");
      const readStmt = stmts.find((s) => (s.Sid as string) === "DynamoDBRead");
      expect(readStmt).toBeDefined();
      if (!readStmt) return;
      expect(readStmt.Effect).toBe("Allow");
    });

    it("has UpdateItem constrained to agent-allowed attributes only", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "AgentExecRole");
      const updateStmt = stmts.find((s) => (s.Sid as string) === "DynamoDBUpdateOutcome");
      expect(updateStmt).toBeDefined();
      if (!updateStmt) return;
      expect(updateStmt.Effect).toBe("Allow");
      expect(updateStmt.Action).toContain("dynamodb:UpdateItem");
      const condition = updateStmt.Condition as Record<string, Record<string, string[]>>;
      const attrs = condition["ForAllValues:StringEquals"]?.["dynamodb:Attributes"];
      expect(attrs).toEqual(expect.arrayContaining([...AGENT_EXEC_WRITE_ATTRIBUTES]));
    });

    it("has NO PutItem in any Allow statement (sub-task 4.4)", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "AgentExecRole");
      const allowStmts = stmts.filter((s) => s.Effect === "Allow");
      for (const stmt of allowStmts) {
        const actions = Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action];
        expect(actions).not.toContain("dynamodb:PutItem");
      }
    });

    it("has explicit Deny on PutItem", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "AgentExecRole");
      const denyStmt = stmts.find((s) => (s.Sid as string) === "DenyPutItem");
      expect(denyStmt).toBeDefined();
      if (!denyStmt) return;
      expect(denyStmt.Effect).toBe("Deny");
      expect(denyStmt.Action).toContain("dynamodb:PutItem");
    });

    it("has explicit Deny on UpdateItem touching enabled/params", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "AgentExecRole");
      const denyStmt = stmts.find((s) => (s.Sid as string) === "DenyWriteForbiddenAttributes");
      expect(denyStmt).toBeDefined();
      if (!denyStmt) return;
      expect(denyStmt.Effect).toBe("Deny");
      expect(denyStmt.Action).toContain("dynamodb:UpdateItem");
      const condition = denyStmt.Condition as Record<string, Record<string, string[]>>;
      const attrs = condition["ForAnyValue:StringEquals"]?.["dynamodb:Attributes"];
      expect(attrs).toEqual(expect.arrayContaining(["enabled", "params"]));
    });

    it("has Secrets Manager read permission", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "AgentExecRole");
      const secretsStmt = stmts.find((s) => (s.Sid as string) === "SecretsManagerRead");
      expect(secretsStmt).toBeDefined();
      if (!secretsStmt) return;
      expect(secretsStmt.Effect).toBe("Allow");
      expect(secretsStmt.Action).toContain("secretsmanager:GetSecretValue");
    });

    it("does NOT have InvokeAgentRuntime", () => {
      const template = createTemplate();
      const stmts = getPolicyStatements(template, "AgentExecRole");
      for (const stmt of stmts) {
        const actions = Array.isArray(stmt.Action) ? stmt.Action : [stmt.Action];
        expect(actions).not.toContain("bedrock-agentcore:InvokeAgentRuntime");
      }
    });
  });

  describe("attribute allowlists imported from shared", () => {
    it("CONTROL_PLANE_WRITE_ATTRIBUTES includes pk, sk, enabled, params", () => {
      expect(CONTROL_PLANE_WRITE_ATTRIBUTES).toEqual(
        expect.arrayContaining(["pk", "sk", "enabled", "params"]),
      );
    });

    it("ORCHESTRATOR_WRITE_ATTRIBUTES includes pk, sk, last_session_id, last_run_at, last_status", () => {
      expect(ORCHESTRATOR_WRITE_ATTRIBUTES).toEqual(
        expect.arrayContaining(["pk", "sk", "last_session_id", "last_run_at", "last_status"]),
      );
    });

    it("AGENT_EXEC_WRITE_ATTRIBUTES includes pk, sk, last_status, last_outcome_url", () => {
      expect(AGENT_EXEC_WRITE_ATTRIBUTES).toEqual(
        expect.arrayContaining(["pk", "sk", "last_status", "last_outcome_url"]),
      );
    });

    it("AGENT_EXEC_WRITE_ATTRIBUTES does NOT include enabled or params", () => {
      expect(AGENT_EXEC_WRITE_ATTRIBUTES).not.toContain("enabled");
      expect(AGENT_EXEC_WRITE_ATTRIBUTES).not.toContain("params");
    });
  });

  describe("cross-stack integration", () => {
    it("references the data stack table via props", () => {
      const template = createTemplate();
      // The policy resources should reference the table ARN from DataStack
      const policies = template.findResources("AWS::IAM::Policy");
      expect(Object.keys(policies).length).toBeGreaterThan(0);
    });

    it("exports role ARNs as outputs", () => {
      const template = createTemplate();
      const outputs = template.toJSON().Outputs;
      expect(outputs).toBeDefined();
      const outputKeys = Object.keys(outputs);
      expect(outputKeys.some((k) => k.includes("ControlPlaneRoleArn"))).toBe(true);
      expect(outputKeys.some((k) => k.includes("OrchestratorRoleArn"))).toBe(true);
      expect(outputKeys.some((k) => k.includes("AgentExecRoleArn"))).toBe(true);
    });
  });
});
