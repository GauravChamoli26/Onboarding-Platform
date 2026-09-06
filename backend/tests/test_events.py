"""
Event infrastructure tests.

WHAT MATTERS MOST HERE
    The transactional guarantee: an event exists if and only if the state change
    that produced it committed. Everything else in this file is important;
    that one is load-bearing, because the Candidate 360 Timeline is a read-layer
    over the event stream and a lost event is a permanently wrong history.

    `test_event_rolls_back_with_its_transaction` and
    `test_event_commits_with_its_transaction` are the pair that prove it.
"""

from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from platform_core.db.types import uuid7
from platform_core.events.catalog import ActorType, EventType
from platform_core.events.consumer import ConsumerRegistry, EventConsumer
from platform_core.events.emitter import emit_event
from platform_core.events.envelope import EventEnvelope
from platform_core.events.publisher import NullPublisher
from platform_core.models.outbox_event import OutboxEvent, OutboxStatus
from platform_core.observability.context import correlation_scope
from platform_core.tenancy.context import organization_context

pytestmark = pytest.mark.integration


async def _count_outbox(factory: async_sessionmaker[AsyncSession], org_id: UUID) -> int:
    """Count outbox rows visible to an organisation."""
    async with factory() as s, s.begin():
        await s.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_id)},
        )
        result = await s.execute(text("SELECT count(*) FROM outbox_events"))
        return int(result.scalar_one())


# ===========================================================================
# The transactional guarantee
# ===========================================================================


async def test_event_commits_with_its_transaction(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """An event written alongside a committed state change is persisted."""
    org_a, _ = two_organizations

    with organization_context(org_a), correlation_scope("test-correlation"):
        async with session_factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.current_organization_id', :v, true)"),
                {"v": str(org_a)},
            )
            await session.execute(
                text("""
                    INSERT INTO feature_flags (id, organization_id, flag_key, enabled)
                    VALUES (:id, :org, 'TalentPool', true)
                """),
                {"id": uuid7(), "org": org_a},
            )
            await emit_event(
                session,
                event_type=EventType.FEATURE_FLAG_CHANGED,
                entity_type="FeatureFlag",
                entity_id=uuid7(),
                payload={"flag_key": "TalentPool", "enabled": True},
            )

    assert await _count_outbox(session_factory, org_a) == 1


async def test_event_rolls_back_with_its_transaction(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    An event whose transaction rolls back leaves no trace.

    This is the half of the outbox guarantee that a publish-after-commit
    implementation cannot provide. Without it the system emits events for state
    changes that never happened, and consumers act on fiction.
    """
    org_a, _ = two_organizations

    with organization_context(org_a), correlation_scope("test-correlation"):
        with pytest.raises(RuntimeError):
            async with session_factory() as session, session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_organization_id', :v, true)"),
                    {"v": str(org_a)},
                )
                await emit_event(
                    session,
                    event_type=EventType.SHORTLISTED,
                    entity_type="Application",
                    entity_id=uuid7(),
                )
                # Something goes wrong after the event was queued.
                raise RuntimeError("simulated failure after emitting")

    assert await _count_outbox(session_factory, org_a) == 0, (
        "Event survived a rolled-back transaction"
    )


async def test_events_are_tenant_isolated(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """One organisation's events are invisible to another."""
    org_a, org_b = two_organizations

    for org_id in (org_a, org_b):
        with organization_context(org_id), correlation_scope("iso-test"):
            async with session_factory() as session, session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_organization_id', :v, true)"),
                    {"v": str(org_id)},
                )
                await emit_event(
                    session,
                    event_type=EventType.SHORTLISTED,
                    entity_type="Application",
                    entity_id=uuid7(),
                )

    assert await _count_outbox(session_factory, org_a) == 1
    assert await _count_outbox(session_factory, org_b) == 1


# ===========================================================================
# Envelope content
# ===========================================================================


async def test_emitted_event_captures_context(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Organisation and correlation ID come from context, not from arguments.

    Keeping them off the call site is what stops them being passed wrongly — an
    event attributed to the wrong actor or tenant is worse than no event.
    """
    org_a, _ = two_organizations

    with organization_context(org_a), correlation_scope("known-correlation-id"):
        async with session_factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.current_organization_id', :v, true)"),
                {"v": str(org_a)},
            )
            await emit_event(
                session,
                event_type=EventType.OFFER_SIGNED,
                entity_type="Offer",
                entity_id=uuid7(),
            )

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_a)},
        )
        row = (await session.execute(select(OutboxEvent))).scalar_one()

    assert row.organization_id == org_a
    assert row.correlation_id == "known-correlation-id"
    # No principal in context, so the actor is the system rather than a
    # fabricated user.
    assert row.actor_type == ActorType.SYSTEM.value
    assert row.actor_id is None


async def test_sequence_numbers_are_monotonic(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Sequence numbers increase in emission order.

    Consumers rely on this for ordering within an organisation.
    """
    org_a, _ = two_organizations

    with organization_context(org_a), correlation_scope("seq-test"):
        for _ in range(3):
            async with session_factory() as session, session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_organization_id', :v, true)"),
                    {"v": str(org_a)},
                )
                await emit_event(
                    session,
                    event_type=EventType.SHORTLISTED,
                    entity_type="Application",
                    entity_id=uuid7(),
                )

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_a)},
        )
        result = await session.execute(
            select(OutboxEvent.sequence_number).order_by(OutboxEvent.sequence_number)
        )
        sequences = [row[0] for row in result]

    assert len(sequences) == 3
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == 3, "Sequence numbers were not unique"


# ===========================================================================
# Relay behaviour
# ===========================================================================


async def test_relay_publishes_pending_events(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """The relay delivers pending events and marks them published."""
    from platform_core.events.relay import relay_organization

    org_a, _ = two_organizations
    publisher = NullPublisher()

    with organization_context(org_a), correlation_scope("relay-test"):
        async with session_factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.current_organization_id', :v, true)"),
                {"v": str(org_a)},
            )
            await emit_event(
                session,
                event_type=EventType.KIT_DISPATCHED,
                entity_type="DispatchRecord",
                entity_id=uuid7(),
            )

        published, failed = await relay_organization(publisher)

    assert published == 1
    assert failed == 0
    assert len(publisher.published) == 1
    assert publisher.published[0].event_type == EventType.KIT_DISPATCHED


async def test_relay_retries_with_backoff_then_dead_letters(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    A persistently failing event is retried, then dead-lettered.

    Retrying forever would mean one poison event blocking a queue indefinitely;
    dropping it would mean losing an event silently. Dead-lettering keeps the
    row, marked Failed, where alerting can find it.
    """
    from platform_core.events.relay import MAX_ATTEMPTS, relay_organization

    org_a, _ = two_organizations

    class AlwaysFailingPublisher:
        async def publish(self, envelope: EventEnvelope) -> None:
            raise RuntimeError("bus unavailable")

    publisher = AlwaysFailingPublisher()

    with organization_context(org_a), correlation_scope("dlq-test"):
        async with session_factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.current_organization_id', :v, true)"),
                {"v": str(org_a)},
            )
            await emit_event(
                session,
                event_type=EventType.BGV_INITIATED,
                entity_type="BGVRecord",
                entity_id=uuid7(),
            )

        # Each cycle sets next_attempt_at into the future, so the row is
        # deliberately made eligible again to drive it through every attempt.
        for _ in range(MAX_ATTEMPTS):
            await relay_organization(publisher)
            async with session_factory() as session, session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_organization_id', :v, true)"),
                    {"v": str(org_a)},
                )
                # Rewind using the DATABASE clock, not Python's. Setting this
                # from the application would compare against a different clock
                # than the relay's query uses, which is the skew this whole
                # change removes.
                await session.execute(
                    text("UPDATE outbox_events SET next_attempt_at = now() - interval '1 second'")
                )

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_a)},
        )
        row = (await session.execute(select(OutboxEvent))).scalar_one()

    assert row.status == OutboxStatus.FAILED.value
    assert row.attempt_count >= MAX_ATTEMPTS
    assert "bus unavailable" in (row.last_error or "")


async def test_relay_does_not_republish_published_events(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """A second relay cycle does not re-deliver already-published events."""
    from platform_core.events.relay import relay_organization

    org_a, _ = two_organizations
    publisher = NullPublisher()

    with organization_context(org_a), correlation_scope("republish-test"):
        async with session_factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.current_organization_id', :v, true)"),
                {"v": str(org_a)},
            )
            await emit_event(
                session,
                event_type=EventType.ONBOARDED,
                entity_type="Application",
                entity_id=uuid7(),
            )

        await relay_organization(publisher)
        await relay_organization(publisher)

    assert len(publisher.published) == 1, "Event was published twice"


# ===========================================================================
# Consumer idempotency
# ===========================================================================


class _RecordingConsumer(EventConsumer):
    """Counts how many times it handled an event. For duplicate testing."""

    name = "test_recording_consumer"
    subscribes_to = frozenset({EventType.SHORTLISTED})

    def __init__(self) -> None:
        self.handled: list[UUID] = []

    async def handle(self, envelope: EventEnvelope, session: AsyncSession) -> None:
        self.handled.append(envelope.event_id)


async def test_consumer_skips_duplicate_delivery(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Delivering the same event twice runs the handler once.

    At-least-once delivery makes duplicates a certainty, not a possibility — the
    relay can publish and then crash before marking the row. This is what makes
    that safe.
    """
    org_a, _ = two_organizations
    consumer = _RecordingConsumer()

    envelope = EventEnvelope(
        event_id=uuid7(),
        event_type=EventType.SHORTLISTED,
        organization_id=org_a,
        entity_type="Application",
        entity_id=uuid7(),
        actor_type=ActorType.SYSTEM,
        correlation_id="dup-test",
    )

    for _ in range(2):
        async with session_factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.current_organization_id', :v, true)"),
                {"v": str(org_a)},
            )
            await consumer.process(envelope, session)

    assert len(consumer.handled) == 1, "Handler ran more than once for one event"


async def test_failed_handler_rolls_back_its_idempotency_marker(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    A handler that raises leaves the event unprocessed, so it is retried.

    The marker and the work share a transaction precisely for this. Recording
    the marker separately would produce the worst outcome available: an event
    marked processed that never was, retried by nothing, lost forever.
    """
    org_a, _ = two_organizations

    class FailingConsumer(EventConsumer):
        name = "test_failing_consumer"
        subscribes_to = frozenset({EventType.SHORTLISTED})

        async def handle(self, envelope: EventEnvelope, session: AsyncSession) -> None:
            raise RuntimeError("handler failed")

    consumer = FailingConsumer()
    envelope = EventEnvelope(
        event_id=uuid7(),
        event_type=EventType.SHORTLISTED,
        organization_id=org_a,
        entity_type="Application",
        entity_id=uuid7(),
        actor_type=ActorType.SYSTEM,
        correlation_id="rollback-test",
    )

    with pytest.raises(RuntimeError):
        async with session_factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.current_organization_id', :v, true)"),
                {"v": str(org_a)},
            )
            await consumer.process(envelope, session)

    # No marker survived, so a retry would run the handler again.
    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_a)},
        )
        result = await session.execute(text("SELECT count(*) FROM processed_events"))
        assert int(result.scalar_one()) == 0


async def test_two_consumers_each_process_the_same_event(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Idempotency is per consumer, not per event.

    The Timeline, the audit writer and the notification service all need the
    same event. A uniqueness constraint on event_id alone would let whichever
    ran first starve the others.
    """
    org_a, _ = two_organizations

    class SecondConsumer(_RecordingConsumer):
        name = "test_second_consumer"

    first = _RecordingConsumer()
    second = SecondConsumer()

    envelope = EventEnvelope(
        event_id=uuid7(),
        event_type=EventType.SHORTLISTED,
        organization_id=org_a,
        entity_type="Application",
        entity_id=uuid7(),
        actor_type=ActorType.SYSTEM,
        correlation_id="two-consumers",
    )

    for consumer in (first, second):
        async with session_factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.current_organization_id', :v, true)"),
                {"v": str(org_a)},
            )
            await consumer.process(envelope, session)

    assert len(first.handled) == 1
    assert len(second.handled) == 1


# ===========================================================================
# Registry
# ===========================================================================


def test_registry_rejects_duplicate_consumer_names() -> None:
    """
    Two consumers sharing a name is rejected.

    Consumer names are idempotency keys. Two consumers sharing one would share
    processed-event records, so each would skip the other's events — a silent,
    partial failure that would be very hard to diagnose.
    """
    reg = ConsumerRegistry()
    reg.register(_RecordingConsumer())
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_RecordingConsumer())


def test_registry_routes_by_subscription() -> None:
    """A consumer receives only the event types it subscribes to."""
    reg = ConsumerRegistry()
    reg.register(_RecordingConsumer())  # subscribes to SHORTLISTED only

    assert len(reg.for_event(EventType.SHORTLISTED)) == 1
    assert len(reg.for_event(EventType.OFFER_SIGNED)) == 0


def test_empty_subscription_means_all_events() -> None:
    """
    A consumer with no declared subscriptions receives everything.

    This is what the audit writer needs — it records every event, and
    enumerating all 95 types would be a list guaranteed to fall out of date.
    """

    class AuditLike(EventConsumer):
        name = "test_audit_like"
        # subscribes_to deliberately left at its empty default

        async def handle(self, envelope: EventEnvelope, session: AsyncSession) -> None:
            pass

    reg = ConsumerRegistry()
    reg.register(AuditLike())

    assert len(reg.for_event(EventType.SHORTLISTED)) == 1
    assert len(reg.for_event(EventType.KIT_DELIVERED)) == 1
