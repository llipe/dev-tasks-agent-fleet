#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { DataStack } from "../lib/data-stack.js";
import { IamStack } from "../lib/iam-stack.js";
import { OrchestrationStack } from "../lib/orchestration-stack.js";

// NOTE: the dep-updater agent runtime is NOT deployed from this CDK app.
// It is owned by the AgentCore CLI project at agents/dep-updater/agentcore,
// which vends its own CDK app and deploys stack `AgentCore-depupdater-default`.
// The discovery tags the control plane relies on (agent:managed / agent:name /
// agent:domain) are declared on that runtime in agentcore.json and asserted
// against packages/shared by infra/test/agentcore-config.test.ts.

const app = new cdk.App();

const env = {
  account: process.env["CDK_DEFAULT_ACCOUNT"],
  region: process.env["CDK_DEFAULT_REGION"],
};

const dataStack = new DataStack(app, "AgentFleetDataStack", { env });

const iamStack = new IamStack(app, "AgentFleetIamStack", {
  env,
  table: dataStack.table,
});

new OrchestrationStack(app, "AgentFleetOrchestrationStack", {
  env,
  table: dataStack.table,
  orchestratorRole: iamStack.orchestratorRole,
  agentRuntimeArn: process.env["AGENT_RUNTIME_ARN"] ?? "arn:aws:bedrock-agentcore:*:*:runtime/*",
});
