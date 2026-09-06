# ADR-008: No LLM orchestration framework

**Status:** Accepted
**Date:** 2026-08-30
**Decision Log ref:** A-10

## Context

Four LLM paths: JD generation, resume parsing, scoring, and the Copilot. LangChain, LlamaIndex and similar frameworks exist precisely for this shape of work.

Three of our requirements are unusual, though. Every call must stamp a `model_version_id` for fairness review. Every call must assert its endpoint region and fail closed on a non-India endpoint. Every prompt change counts as a new model version requiring fresh fairness sign-off.

## Decision

Direct `boto3` calls to AWS Bedrock, wrapped in our own thin service layer. Structured output via Pydantic models, using `instructor` or plain tool-use parsing.

## Consequences

Region assertion, model-version stamping and prompt pinning are all trivial because we own the call site. Under a framework, each becomes a fight with an abstraction that was designed for a different problem.

The service layer is roughly 200 lines. Frameworks would save some of that and cost more in indirection.

We give up the framework ecosystem — retrieval chains, agent loops, prebuilt integrations. None of them is on our roadmap. If retrieval-augmented matching becomes a product feature later, this decision is worth revisiting for that module specifically.

Every LLM response is validated against a Pydantic schema. Free text that fails validation is an error, never a silent fallback.

## Alternatives considered

**LangChain** — largest ecosystem, and the default choice. Rejected because the abstraction sits exactly where our compliance controls need to be.

**LiteLLM as a thin multi-provider layer** — reasonable if we expected to switch providers often. We do not; residency pins us to India-region endpoints.
