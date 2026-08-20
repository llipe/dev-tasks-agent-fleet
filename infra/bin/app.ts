#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { DataStack } from "../lib/data-stack.js";
import { IamStack } from "../lib/iam-stack.js";
import { AgentStack } from "../lib/agent-stack.js";

const app = new cdk.App();

const env = {
  account: process.env["CDK_DEFAULT_ACCOUNT"],
  region: process.env["CDK_DEFAULT_REGION"],
};

const dataStack = new DataStack(app, "AgentFleetDataStack", { env });

new IamStack(app, "AgentFleetIamStack", {
  env,
  table: dataStack.table,
});

new AgentStack(app, "AgentFleetAgentStack", { env });
