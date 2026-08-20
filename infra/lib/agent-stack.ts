import * as cdk from "aws-cdk-lib";
import type { Construct } from "constructs";
import { DEP_UPDATER_TAGS } from "@fleet/shared";

/**
 * AgentStack — Minimal CDK construct defining agent discovery tags.
 *
 * This stack applies resource tags that enable the control plane to discover
 * managed agents via `tag:GetResources` filtered on `agent:managed=true`.
 *
 * S-006 will extend this stack with the full agent runtime (container, IAM, etc).
 * For now, it defines the tag contract and applies it to all resources in the stack.
 *
 * Tags applied:
 * - `agent:managed=true` — primary discovery filter
 * - `agent:name=dep-updater` — join key matching `AGENT#dep-updater` in DynamoDB
 * - `agent:domain=security` — domain classification for UI grouping
 */
export class AgentStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Apply discovery tags to all resources in this stack.
    // When S-006 adds the agent runtime resource, these tags will be inherited.
    for (const [key, value] of Object.entries(DEP_UPDATER_TAGS)) {
      cdk.Tags.of(this).add(key, value);
    }

    // Placeholder resource to ensure the stack is deployable and tags are applied.
    // This will be replaced by the actual agent runtime in S-006.
    new cdk.CfnWaitConditionHandle(this, "AgentTagAnchor");

    // Outputs for reference
    new cdk.CfnOutput(this, "AgentName", {
      value: DEP_UPDATER_TAGS["agent:name"],
      description: "Agent name (matches AGENT# key in DynamoDB)",
    });

    new cdk.CfnOutput(this, "AgentDomain", {
      value: DEP_UPDATER_TAGS["agent:domain"],
      description: "Agent domain classification",
    });

    new cdk.CfnOutput(this, "AgentManaged", {
      value: DEP_UPDATER_TAGS["agent:managed"],
      description: "Agent managed flag for discovery",
    });
  }
}
