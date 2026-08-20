import * as cdk from "aws-cdk-lib";
import type { Construct } from "constructs";
import { DEP_UPDATER_TAGS } from "@fleet/shared";

/**
 * Agent runtime lifecycle configuration.
 * Values sourced from agentcore.json and recorded here for CDK synthesis.
 */
export interface AgentLifecycleConfig {
  /** Maximum seconds a runtime session can live before forced termination. */
  readonly maxLifetime: number;
  /** Seconds of idle time before the runtime session is stopped. */
  readonly idleRuntimeSessionTimeout: number;
}

/**
 * Agent runtime specification for AgentCore deployment.
 */
export interface AgentRuntimeSpec {
  readonly name: string;
  readonly build: "Container";
  readonly entrypoint: string;
  readonly codeLocation: string;
  readonly runtimeVersion: string;
  readonly networkMode: "PUBLIC" | "PRIVATE";
  readonly protocol: "HTTP";
  readonly lifecycleConfiguration: AgentLifecycleConfig;
}

/**
 * dep-updater agent runtime specification.
 *
 * Matches the values in agents/dep-updater/agentcore.json (Python 3.13,
 * container build, HTTP protocol on AgentCore Runtime).
 */
export const DEP_UPDATER_RUNTIME: AgentRuntimeSpec = {
  name: "dep-updater",
  build: "Container",
  entrypoint: "main.py",
  codeLocation: "agents/dep-updater/",
  runtimeVersion: "PYTHON_3_13",
  networkMode: "PUBLIC",
  protocol: "HTTP",
  lifecycleConfiguration: {
    maxLifetime: 3600,
    idleRuntimeSessionTimeout: 300,
  },
};

/**
 * AgentStack — CDK stack for the dep-updater agent.
 *
 * Responsibilities:
 * 1. Apply discovery tags (agent:managed, agent:name, agent:domain) to all
 *    resources for control-plane discovery via `tag:GetResources`.
 * 2. Define the agent runtime spec (container config, lifecycle settings)
 *    as CDK outputs and metadata for the AgentCore deployment pipeline.
 *
 * The actual AgentCore runtime resource is deployed via `agentcore deploy`
 * (CLI-driven), not synthesized here. This stack provides:
 * - Tag-based discovery contract
 * - Runtime configuration as infrastructure-as-code documentation
 * - Lifecycle configuration values for the control plane's status derivation
 */
export class AgentStack extends cdk.Stack {
  /** The agent runtime specification. */
  public readonly runtimeSpec: AgentRuntimeSpec = DEP_UPDATER_RUNTIME;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Apply discovery tags to all resources in this stack.
    for (const [key, value] of Object.entries(DEP_UPDATER_TAGS)) {
      cdk.Tags.of(this).add(key, value);
    }

    // Placeholder resource to ensure the stack is deployable and tags are applied.
    // The actual agent runtime is deployed via `agentcore deploy` CLI.
    new cdk.CfnWaitConditionHandle(this, "AgentTagAnchor");

    // ── Outputs: discovery tags ──────────────────────────────────────
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

    // ── Outputs: runtime configuration ───────────────────────────────
    new cdk.CfnOutput(this, "RuntimeName", {
      value: DEP_UPDATER_RUNTIME.name,
      description: "AgentCore runtime name",
    });

    new cdk.CfnOutput(this, "RuntimeVersion", {
      value: DEP_UPDATER_RUNTIME.runtimeVersion,
      description: "Python runtime version (AgentCore enum)",
    });

    new cdk.CfnOutput(this, "MaxLifetime", {
      value: String(DEP_UPDATER_RUNTIME.lifecycleConfiguration.maxLifetime),
      description: "Maximum session lifetime in seconds",
    });

    new cdk.CfnOutput(this, "IdleTimeout", {
      value: String(DEP_UPDATER_RUNTIME.lifecycleConfiguration.idleRuntimeSessionTimeout),
      description: "Idle session timeout in seconds",
    });
  }
}
