/**
 * LLIPE span attribute name constants.
 * These are the custom attributes emitted by agents on their root spans.
 */

export const LLIPE = {
  SUBJECT_ID: "llipe.subject.id",
  RUN_STATUS: "llipe.run.status",
  OUTCOME_TYPE: "llipe.outcome.type",
  OUTCOME_URL: "llipe.outcome.url",
} as const;

export type LlipeAttributeKey = keyof typeof LLIPE;
export type LlipeAttributeValue = (typeof LLIPE)[LlipeAttributeKey];
