"""
Event publishers — where a published event actually goes.

WHY AN INTERFACE
    Locally there is no EventBridge. Running LocalStack to provide one would add
    a dependency to every developer's machine for no benefit, because the parts
    with real bugs in them are the outbox and the consumers, and those are
    identical either way.

    So publication sits behind an interface, the same adapter pattern as every
    vendor integration (ADR-015). Local development dispatches in-process;
    deployment uses EventBridge. Neither the emitter nor any consumer knows
    which is in use.

WHAT A PUBLISHER MUST GUARANTEE
    Only that `publish` raises on failure. The relay treats any exception as a
    retryable failure and applies backoff, so a publisher that swallows errors
    would silently drop events — which is the one thing this whole design exists
    to prevent.
"""

import logging
from typing import Protocol

from platform_core.events.consumer import ConsumerRegistry
from platform_core.events.envelope import EventEnvelope

logger = logging.getLogger(__name__)


class EventPublisher(Protocol):
    """Anything that can deliver an event."""

    async def publish(self, envelope: EventEnvelope) -> None:
        """
        Deliver one event.

        Args:
            envelope: the event to deliver.

        Raises:
            Exception: on any delivery failure. The relay retries with backoff.
                Swallowing failures here would silently drop events.
        """
        ...


class InProcessPublisher:
    """
    Dispatches events to registered consumers in the same process.

    Used in local development and in tests. Each consumer runs in its own
    session and transaction, so one failing consumer does not roll back another
    — the same isolation separate SQS queues give in deployment.

    Failures are collected and re-raised together, so a single failing consumer
    causes the outbox row to be retried while successful consumers, having
    already recorded their idempotency markers, skip it on the next attempt.
    """

    def __init__(self, registry: ConsumerRegistry) -> None:
        self._registry = registry

    async def publish(self, envelope: EventEnvelope) -> None:
        """
        Dispatch to every subscribing consumer.

        Args:
            envelope: the event to dispatch.

        Raises:
            RuntimeError: if any consumer failed, naming which.
        """
        from platform_core.db.session import get_session
        from platform_core.tenancy.context import organization_context

        consumers = self._registry.for_event(envelope.event_type)
        if not consumers:
            logger.debug(
                "No consumers subscribed",
                extra={"event_type": envelope.event_type.value},
            )
            return

        failures: list[tuple[str, Exception]] = []

        for consumer in consumers:
            try:
                # Each consumer gets its own transaction, scoped to the event's
                # organisation. The relay may be running under a different
                # tenant context, so this is set explicitly rather than assumed.
                with organization_context(envelope.organization_id):
                    async with get_session() as session:
                        await consumer.process(envelope, session)
            except Exception as exc:  # noqa: BLE001 - one consumer must not
                # prevent the others from running.
                logger.exception(
                    "Consumer failed",
                    extra={
                        "consumer": consumer.name,
                        "event_type": envelope.event_type.value,
                    },
                )
                failures.append((consumer.name, exc))

        if failures:
            names = ", ".join(name for name, _ in failures)
            raise RuntimeError(f"Event delivery failed for consumers: {names}")


class NullPublisher:
    """
    Discards everything. For tests that exercise emission without delivery.

    Named explicitly rather than being a mock, so that a test using it is
    obviously not testing delivery.
    """

    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> None:
        """Record the event and do nothing else."""
        self.published.append(envelope)
