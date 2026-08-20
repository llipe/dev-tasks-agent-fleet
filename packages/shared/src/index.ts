// Key builders and prefixes
export { subjectPk, agentSk, META, CONFIG, PREFIXES, TABLE_NAME, GSI1_NAME } from "./keys.js";

// DynamoDB item schemas
export { SubjectMetaItem, SubjectAgentItem, AgentConfigItem } from "./schemas.js";
export type {
  SubjectMetaItem as SubjectMetaItemType,
  SubjectAgentItem as SubjectAgentItemType,
  AgentConfigItem as AgentConfigItemType,
} from "./schemas.js";

// Per-agent params validation
export { PARAMS_SCHEMAS, paramsSchemaFor } from "./params-schemas.js";

// LLIPE span attribute constants
export { LLIPE } from "./llipe.js";
export type { LlipeAttributeKey, LlipeAttributeValue } from "./llipe.js";

// Span field path mapping
export { SPAN_FIELDS } from "./span-fields.js";
export type { SpanFieldKey, SpanFieldPath } from "./span-fields.js";

// Status derivation
export { deriveStatus, DEFAULT_MAX_LIFETIME_MS, TERMINATION_GRACE_MS } from "./status.js";

// Session ID builder
export { buildSessionId } from "./session-id.js";

// Subject ID normalizer
export { normalizeSubjectId } from "./normalize-subject-id.js";

// Agent discovery tags
export { DEP_UPDATER_TAGS, agentNameToSortKey, sortKeyToAgentName } from "./agent-tags.js";
export type { AgentTagSet } from "./agent-tags.js";

// Observability configuration
export { SPANS_LOG_GROUP, SPANS_RETENTION_DAYS } from "./observability-config.js";

// IAM attribute allowlists for write separation
export {
  KEY_ATTRIBUTES,
  CONTROL_PLANE_WRITE_ATTRIBUTES,
  ORCHESTRATOR_WRITE_ATTRIBUTES,
  AGENT_EXEC_WRITE_ATTRIBUTES,
  ALL_ITEM_ATTRIBUTES,
} from "./iam-attributes.js";
export type {
  ControlPlaneWriteAttribute,
  OrchestratorWriteAttribute,
  AgentExecWriteAttribute,
} from "./iam-attributes.js";
