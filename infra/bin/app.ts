#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { DataStack } from "../lib/data-stack.js";

const app = new cdk.App();

new DataStack(app, "AgentFleetDataStack", {
  env: {
    account: process.env["CDK_DEFAULT_ACCOUNT"],
    region: process.env["CDK_DEFAULT_REGION"],
  },
});
