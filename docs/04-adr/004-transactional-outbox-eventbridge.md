# ADR-004: Transactional outbox to EventBridge to per-consumer SQS

**Status:** Accepted
**Date:** 2026-08-30
**Decision Log ref:** A-06

## Context

Every module emits domain events. Six consumers subscribe: Candidate 360 Timeline, Notification Service, Audit Log, Reporting, Talent Pool, SLA/Escalation and Retention. The spec requires resilience — retry with backoff, dead-letter queues — applied to the event bus and not only to external integrations.

The naive implementation writes the state change to the database and then publishes to the bus. If the publish fails, the state changed and no event exists. The Timeline is a read-layer over the event stream, so a lost event is a permanently wrong candidate history.

## Decision

**Transactional outbox.** The event row is written in the same database transaction as the state change. A relay process reads the outbox and publishes. No dual-write.

**EventBridge for routing**, giving content-based rules so consumers subscribe to patterns rather than receiving everything and filtering.

**Per-consumer SQS queues** with their own dead-letter queues. Age of the oldest DLQ entry is a monitored SLO.

Delivery is at-least-once. Every consumer is idempotent by `event_id` and keeps a processed-event table. Ordering is guaranteed per `(organization_id, application_id)` partition key; global ordering is neither guaranteed nor needed.

## Consequences

An event is never lost and never emitted for a state change that rolled back.

The relay is a new moving part that must be monitored — if it stalls, the system looks healthy while events silently stop flowing. Relay lag is an alerting metric.

Consumers must be written idempotently, which is a real discipline cost on every consumer.

Events carry identifiers and state transitions, never PII, so the event store sits outside the purge path. That is a deliberate constraint on payload design.

## Alternatives considered

**Publish directly after commit** — simplest, and loses events. Rejected outright given the Timeline dependency.

**SNS fan-out** — workable but the filtering is less expressive than EventBridge rules.

**Kafka or MSK** — operationally heavy for this volume, and nothing in the requirements needs log replay semantics.
