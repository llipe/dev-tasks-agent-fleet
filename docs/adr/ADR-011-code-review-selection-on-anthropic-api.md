# ADR-011: Code-review context-selection call on the Anthropic API

## Status

Accepted

## Context

ADR-010 (addendum 2026-11-02) placed the optional context-selection call on AWS Bedrock Converse. The 2026-11-25 addendum moved the review call to the Anthropic Messages API (PRD v1.7, S-216 / #480) and deliberately left selection on Bedrock until a follow-up story. Keeping two model providers in the code-review package meant a Bedrock client, a Bedrock test fake, a `bedrock:` IAM grant, and a second credential path to maintain for a single model family. PRD v1.7 decision D-71 specifies one provider for both calls.

## Decision

The context-selection call uses the Anthropic client from `model_adapter.make_client`, with `max_retries=0` (one attempt, bounded by the call's timeouts) and the same API key read once per run by `credentials.py`. `legacy_bedrock.py` and `tests/fixtures/bedrock.py` are deleted. The runtime IAM policy (`agents/code-review/agentcore/iam/runtime-role-policy.json`) carries no `bedrock:` action. Boto3 remains only for AWS Secrets Manager. The selection contract is unchanged: the model returns indexes into a wrapper-built candidate list, any failure falls back to rule-based context, and the review never fails because selection did.

## Alternatives Considered

- **Keep selection on Bedrock until a later story.** Rejected: it keeps a Bedrock client, a `bedrock:` grant and a second credential path alive for one optional call, and blocks the IAM change of S-218 from being a pure removal.
- **Use a different provider for selection than for review.** Rejected: PRD v1.7 D-71 names one provider, and the model-family diversity goal was dropped (D-79).
- **Let the selection call use the review call's retry budget.** Rejected: selection is optional and has its own timeout; `max_retries=0` keeps its worst-case latency bounded and falls back to rule-based context instead of retrying.

## Consequences

- Positive: one provider and one credential path for the code-review agent; the runtime role needs no Bedrock grant for the review or selection calls.
- Positive: the selection tests run on the same Anthropic fake as the review tests.
- Negative: PR content used for selection (PR body, issue text, document index) now leaves AWS for the Anthropic API under its standard retention, as the review content already did (ADR-010 addendum 2026-11-25, D-76).
- Follow-up: the deployed runtime (version 5) still runs the Bedrock build and its IAM policy still grants Bedrock until S-218 (#482) deploys the v1.7 build and applies the new policy and secret. Until then this ADR describes the branch, not production.

## Related

- Requirements: [`docs/requirements/prd-code-review-agent.md`](../requirements/prd-code-review-agent.md) (v1.7, D-71, D-79)
- Workstream: `workstream/specification-prd-code-review-agent.md` (v1.8), `workstream/decisions-code-review-agent.md`
- Docs updated: [`docs/technical-guidelines.md`](../technical-guidelines.md) (§9, §11, §16, changelog 1.61), [`docs/product-context.md`](../product-context.md) (§5, changelog 1.9), [`docs/adr/ADR-010-code-review-agent-constraints.md`](ADR-010-code-review-agent-constraints.md) (addendum 2026-11-25), [`docs/runbooks/code-review-deployment.md`](../runbooks/code-review-deployment.md) (§1a step 3), [`README.md`](../../README.md) (ADR index)
