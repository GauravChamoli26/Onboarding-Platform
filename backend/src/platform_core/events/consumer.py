"""
Consumer base class and registry.

WHAT A CONSUMER IS
    A subscriber to some subset of event types. The Timeline builds a read
    model, the audit writer records entries, the notification service sends
    email. Each is a consumer, each independent, each able to fail without
    affecting the others.

IDEMPOTENCY IS NOT OPTIONAL
    Delivery is at-least-once. `process()` handles the bookkeeping so individual
    consumers do not have to: it records the event as processed and runs the
    handler in one transaction, and skips events already recorded.

    A consumer that overrode `process()` and skipped that would be a bug waiting
    for the first relay crash.
"""

import logging
from abc import ABC, abstractmethod
from typing import ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.db.types import uuid7
from platform_core.events.catalog import EventType
from platform_core.events.envelope import EventEnvelope
from platform_core.models.processed_event import ProcessedEvent

logger = logging.getLogger(__name__)


class EventConsumer(ABC):
    """
    Base class for every event consumer.

    Subclasses declare a name and the events they care about, then implement
    `handle`. Everything else — idempotency, transaction boundaries, logging —
    is handled here.
    """

    # Stable identifier, used as the idempotency key alongside event_id.
    # Renaming a consumer makes it reprocess history, so treat this as
    # permanent once deployed.
    name: ClassVar[str]

    # Which events this consumer wants. An empty set means all of them, which
    # is what the audit writer needs.
    subscribes_to: ClassVar[frozenset[EventType]] = frozenset()

    def wants(self, event_type: EventType) -> bool:
        """Whether this consumer subscribes to the given event type."""
        return not self.subscribes_to or event_type in self.subscribes_to

    @abstractmethod
    async def handle(self, envelope: EventEnvelope, session: AsyncSession) -> None:
        """
        Do the consumer's work.

        Runs inside a transaction that also contains the idempotency marker. If
        this raises, both roll back and the event is retried — so raising is the
        correct response to a transient failure.

        Args:
            envelope: the event.
            session: a tenant-scoped session, already inside a transaction. Do
                not commit; the caller owns the transaction.
        """

    async def process(self, envelope: EventEnvelope, session: AsyncSession) -> bool:
        """
        Handle an event exactly once, skipping it if already processed.

        Args:
            envelope: the event.
            session: tenant-scoped session inside a transaction.

        Returns:
            bool: True if handled, False if it was a duplicate and was skipped.

        The marker is inserted BEFORE the handler runs, and both share the
        transaction. If the handler fails, the rollback removes the marker and
        the event is retried. Inserting afterwards, or in a separate
        transaction, would give the opposite failure: an event marked processed
        that never was.
        """
        already = await session.execute(
            select(ProcessedEvent.id)
            .where(ProcessedEvent.consumer_name == self.name)
            .where(ProcessedEvent.event_id == envelope.event_id)
        )
        if already.first() is not None:
            logger.debug(
                "Skipping duplicate event",
                extra={"consumer": self.name, "event_type": envelope.event_type.value},
            )
            return False

        session.add(
            ProcessedEvent(
                id=uuid7(),
                organization_id=envelope.organization_id,
                consumer_name=self.name,
                event_id=envelope.event_id,
                event_type=envelope.event_type.value,
            )
        )

        await self.handle(envelope, session)

        logger.debug(
            "Event handled",
            extra={"consumer": self.name, "event_type": envelope.event_type.value},
        )
        return True


class ConsumerRegistry:
    """
    The set of consumers events are dispatched to.

    A registry rather than import-time discovery, so that tests can build one
    containing exactly the consumers under test. Magic auto-discovery makes it
    impossible to run a consumer in isolation.
    """

    def __init__(self) -> None:
        self._consumers: list[EventConsumer] = []

    def register(self, consumer: EventConsumer) -> None:
        """
        Add a consumer.

        Args:
            consumer: the consumer to register.

        Raises:
            ValueError: if a consumer with the same name is already registered.
                Two consumers sharing a name would share idempotency records,
                so each would skip the other's events.
        """
        if any(c.name == consumer.name for c in self._consumers):
            raise ValueError(
                f"A consumer named {consumer.name!r} is already registered. "
                f"Consumer names are idempotency keys and must be unique."
            )
        self._consumers.append(consumer)

    def for_event(self, event_type: EventType) -> list[EventConsumer]:
        """Return every consumer subscribing to the given event type."""
        return [c for c in self._consumers if c.wants(event_type)]

    def all(self) -> list[EventConsumer]:
        """Return every registered consumer."""
        return list(self._consumers)

    def clear(self) -> None:
        """Remove all consumers. For test isolation."""
        self._consumers.clear()


# Process-wide registry. Consumers register during application startup.
registry = ConsumerRegistry()
