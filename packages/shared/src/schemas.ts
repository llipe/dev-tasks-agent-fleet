/**
 * Zod schemas for DynamoDB item types.
 * These define the shape of items in the agent-fleet-config table.
 */

import { z } from "zod";

/**
 * Subject metadata item (pk=SUBJECT#<repo>, sk=META)
 * One per repository in the system.
 */
export const SubjectMetaItem = z.object({
  pk: z.string(),
  sk: z.literal("META"),
  subject_id: z.string(),
  created_at: z.string(),
});
export type SubjectMetaItem = z.infer<typeof SubjectMetaItem>;

/**
 * Subject-agent association item (pk=SUBJECT#<repo>, sk=AGENT#<name>)
 * One per (repo, agent) pair. Tracks scope and run status.
 */
export const SubjectAgentItem = z.object({
  pk: z.string(),
  sk: z.string(),
  enabled: z.boolean(),
  params: z.record(z.string(), z.unknown()).default({}),
  last_session_id: z.string().optional(),
  last_run_at: z.string().optional(),
  last_status: z.string().optional(),
  last_outcome_url: z.string().optional(),
});
export type SubjectAgentItem = z.infer<typeof SubjectAgentItem>;

/**
 * Agent global config item (pk=AGENT#<name>, sk=CONFIG)
 * One per agent. Holds global defaults.
 */
export const AgentConfigItem = z.object({
  pk: z.string(),
  sk: z.literal("CONFIG"),
  agent_name: z.string(),
  domain: z.string().optional(),
  default_params: z.record(z.string(), z.unknown()).default({}),
});
export type AgentConfigItem = z.infer<typeof AgentConfigItem>;
