# Span Fixtures

These fixture files represent the **expected** structure of OTEL spans as stored by AWS ADOT (OpenTelemetry Distro) in CloudWatch Logs Insights.

## Status: Pending Live Verification

The field paths are based on:

- [OpenTelemetry Span data model](https://opentelemetry.io/docs/specs/otel/trace/api/)
- [AWS ADOT documentation](https://aws-otel.github.io/docs/introduction)
- AgentCore's span emission behavior (inferred from ADOT defaults)

Once a live run is deployed and spans are captured from `SPANS_LOG_GROUP`, these fixtures will be updated with actual data.

## Files

- `root-span.json` — A complete root span with all `llipe.*` resource attributes. Root spans have an empty `parentSpanId`.
- `gen-ai-child-span.json` — A model call child span with `gen_ai.*` attributes (tokens, model ID). Child spans have a populated `parentSpanId`.

## Usage

These fixtures are used by:

- `packages/shared/src/span-mapper.test.ts` — mapper unit tests (S-012)
- Future S-017 Logs Insights query tests
