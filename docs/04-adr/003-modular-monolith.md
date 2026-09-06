# ADR-003: Modular monolith over microservices

**Status:** Accepted
**Date:** 2026-08-30
**Decision Log ref:** A-03

## Context

The system has eleven functional modules with genuinely different concerns, and the spec already mandates that modules communicate through domain events rather than direct calls. That event-driven design is usually the reason teams reach for microservices.

The team is small and the company is pre-seed.

## Decision

One deployable API application organised into modules with enforced boundaries, plus separate worker and relay processes:

`api` · `worker-default` · `worker-llm` (separate pool, so slow LLM calls do not starve fast jobs) · `outbox-relay` · `scheduler`

Modules communicate through events and published interfaces, never by importing each other's internals. The boundary is enforced in code review and by import linting.

## Consequences

We get the decoupling without distributed transactions, without network failure between every module, and without eleven deployment pipelines for a small team.

Local development is one process. Debugging crosses module boundaries in a single stack trace.

The cost is that module boundaries are a discipline rather than a physical constraint. A determined engineer can import across them. Import linting catches most of it; review catches the rest.

If a module genuinely needs to split out later — the most likely candidate is LLM processing, if inference volume grows — the seam already exists because the communication is already event-based.

## Alternatives considered

**Microservices from the start** — would be the most expensive mistake available at this stage. The operational overhead lands immediately; the benefits arrive at a scale this system will not reach for years.

**Serverless functions per module** — attractive for cost at low volume, but cold starts hurt the LLM paths and the local development story is poor.
