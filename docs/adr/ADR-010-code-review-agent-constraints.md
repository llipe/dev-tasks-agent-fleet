# ADR-010: Code-review agent architectural constraints (Wave A)

## Status

Accepted

## Context

The `code-review` agent is the fleet's fourth agent. Its Wave A base (stories S-204–S-213, issues #406–#415) is implemented in `agents/code-review/app/codeReview/`: a `/review` PR comment starts one run, and the run posts one PR comment. The PRD ([`docs/requirements/prd-code-review-agent.md`](../requirements/prd-code-review-agent.md) v1.2) and the spec ([`workstream/specification-prd-code-review-agent.md`](../../workstream/specification-prd-code-review-agent.md) v1.3) fix the constraints. Four of them are architectural rules that the guidelines must state, because the agent's safety and cost depend on them:

- the review is one model review per run (at most 5 Converse calls: retries without a rejected option and one repair) with no tools and no agent loop;
- the model is from a non-Anthropic family on Bedrock, so the reviewer is not the family that wrote the code;
- the wrapper, not the model, enforces the blocking contract and computes the verdict;
- the agent's GitHub access is an allowlist with one write.

Wave B (S-214 deploy and enable, S-215 live verification) is not done. The `agents` row is seeded disabled with the placeholder `runtime_arn` `pending-deploy:code-review`. The agent is not deployed and reviews no PR.

Sibling agents recorded their status changes in `docs/technical-guidelines.md`'s changelog without an ADR. This ADR is written because the guidelines' change rule requires one for any change to that file, and because this change adds enforceable constraints rather than only status.

## Decision

1. **One model review, no tools, no loop.** The wrapper makes one Bedrock Converse review call (plus at most 4 retry or repair calls, capped by `MAX_CALLS`) with the assembled context, the rubric, and the forced `submit_review` output schema (`agents/code-review/app/codeReview/bedrock_adapter.py`, `findings_schema.py`; PRD FR-18, spec §6.3, D-07). The adapter reads the forced tool's `input` and never sends a tool result back or loops on `tool_use`. Strands and any other agent framework are not dependencies.
2. **Non-Anthropic model family on Bedrock.** `MODEL_ID` is a required environment variable (`config.py`). The approved default is OpenAI GPT-5.6 Sol on Bedrock, with DeepSeek V4 Pro on Bedrock as the approved fallback (PRD FR-19, D-09, D-17, D-18). The final default is still subject to the 5-PR smoke in Wave B and the Layer 3 evaluation, which is not built (PRD §10, L3).
3. **The wrapper enforces the blocking contract and the verdict.** `agents/code-review/app/codeReview/validate.py` downgrades a blocking finding that has no failure scenario or no location in the diff to a suggestion, and drops any finding with no consequence. The verdict (`clear`, `blocking`) is computed by the wrapper from the validated findings and is never taken from the model (D-08, D-15; spec §8.6, §8.7).
4. **GitHub access is an allowlist with one write.** `agents/code-review/app/codeReview/github_client.py` permits only the seven `(method, path template)` pairs of spec §6.2, bound to the invoked repository and PR number. Any other call raises `ForbiddenCall` before the transport is touched. The only write is one new `POST` comment on the invoked PR (PRD FR-27, AC-10). The agent never approves, merges, pushes, edits a comment, or creates a review or check run (D-10).
5. **No credentials for the model.** The model receives no tools and no credentials. The wrapper alone holds the GitHub App installation token and the Supabase key, obtained from AWS Secrets Manager (`credentials.py`), and scrubs both from logs, events, and the comment (`scrubber.py`).
6. **Existing ADRs apply unchanged.** The clock invariant and the heartbeat keep-alive are those of [ADR-006](ADR-006-long-step-keepalive-and-clock-invariant.md) (`config.assert_clock_invariant()`, `heartbeat.py`). Error logging on Bedrock and AWS failures follows [ADR-009](ADR-009-allowlisted-aws-error-logging.md) (`bedrock_adapter.py`).
7. **Not deployed until Wave B.** The `agents` seed row is `is_enabled = false` with the placeholder ARN (D-39). S-214 sets `runtime_arn` and `is_enabled = true` in one explicit update after the first deploy.

## Alternatives Considered

- **Agent loop with tools (Strands, repository clone, file-reading tools).** Rejected (D-07). A loop adds a tool-execution surface, unbounded cost, and nondeterminism. The wrapper already assembles the context under a budget.
- **Anthropic model family.** Rejected (D-09). The PRD's goal is a reviewer from a different model family than the one that wrote the code.
- **Model-computed verdict or model-enforced blocking contract.** Rejected (D-08). The model's output is untrusted; the checks are deterministic and testable in the wrapper.
- **GitHub Reviews API or a check run as the output channel.** Rejected (D-10). One comment is the only write the agent needs; a review or check run would widen the write surface.
- **Seed the row enabled with the placeholder ARN.** Rejected (D-39). A disabled row cannot be invoked with a placeholder.
- **Status-only changelog entry with no ADR, as the sibling agents' rows did.** Rejected for this change because it adds enforceable constraints, which the guidelines' change rule covers.

## Consequences

**Positive**

- The reviewer's safety boundary is stated in one place: no tools, one allowlisted write, no credentials for the model, and a wrapper-side verdict.
- Future reviewers or agents can be checked against the same constraints.

**Negative**

- The allowlist and the model-family rule are per-agent. Future change to either is an architectural change that needs its own ADR.
- Until Wave B, the constraints describe code that has not run against a real PR or a deployed runtime.

**Follow-up actions**

- Wave B (S-214, S-215, issues #416–#417): deploy the runtime, add `agents/code-review/agentcore/agentcore.json` (its `maxLifetime` must equal the seed's `max_runtime_seconds`, 1800), write the runbook required by FR-49a, add the `/review` webhook rule, run the 5-PR smoke, and confirm or change the default `MODEL_ID`. Then update `docs/technical-guidelines.md` §9 and the status lines in `docs/product-context.md`, `README.md`, and `docs/roadmap.md` (planner-owned).
- Re-check this ADR's Decision 2 after the Layer 3 evaluation or the smoke, if the default model changes.

## Related

- Requirements: [`docs/requirements/prd-code-review-agent.md`](../requirements/prd-code-review-agent.md) (v1.2), [`docs/requirements/prd-webhook-triggers.md`](../requirements/prd-webhook-triggers.md) (trigger mechanism)
- Workstream: [`workstream/specification-prd-code-review-agent.md`](../../workstream/specification-prd-code-review-agent.md) (v1.3), [`workstream/decisions-code-review-agent.md`](../../workstream/decisions-code-review-agent.md) (D-01–D-55), [`workstream/planner-state-code-review-agent-wave-a.md`](../../workstream/planner-state-code-review-agent-wave-a.md), [`workstream/fidelity-report-S-204.md`](../../workstream/fidelity-report-S-204.md) to [`workstream/fidelity-report-S-213.md`](../../workstream/fidelity-report-S-213.md)
- Related ADRs: [ADR-006](ADR-006-long-step-keepalive-and-clock-invariant.md), [ADR-009](ADR-009-allowlisted-aws-error-logging.md)
- Docs updated: [`docs/technical-guidelines.md`](../technical-guidelines.md) (§6, §9, §11, §16, changelog 1.54), [`docs/product-context.md`](../product-context.md) (§5, §6, changelog 1.4), [`README.md`](../../README.md) (agent layout, active-codebase paragraph, ADR index)
