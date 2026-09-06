"""
Outbox relay — moves pending events from the outbox to the publisher.

WHAT IT DOES
    Reads Pending outbox rows whose retry time has arrived, publishes each, and
    marks the row Published. On failure it increments the attempt count, applies
    exponential backoff, and after the maximum number of attempts moves the row
    to Failed — the dead-letter state.

WHY IT ITERATES ORGANISATIONS
    The outbox is tenant-scoped and carries row-level security like every other
    table. A relay that bypassed RLS would be a process reading every tenant's
    rows with a single query, which is exactly the shape of thing that leaks.

    Instead it lists organisation IDs through a system session — the documented
    legitimate use of `system_context()` — then processes each organisation
    inside `organization_context()`, so every query is scoped by the database
    exactly as an application query would be.

    The cost is one query per organisation per cycle. At this volume that is
    nothing, and the alternative is a privileged code path in the hot loop.

ON ORDERING
    Rows are processed in `sequence_number` order. That column is a global
    sequence, so it is monotonic within an organisation as a subsequence, which
    is what ordering requires. It does NOT support per-organisation gap
    detection, since gaps appear where other tenants' events fell. That is a
    deliberate simplification: per-tenant sequences need a counter table and
    contention, and nothing currently needs gap detection.

CONCURRENCY
    Rows are claimed with FOR UPDATE SKIP LOCKED, so several relay instances can
    run without processing the same row twice or blocking each other.

ON CLOCKS
    `next_attempt_at` is written by the database — `server_default=func.now()`
    on insert, and `now() + interval` on retry. It is therefore compared against
    the DATABASE clock, never against `datetime.now()` in Python.

    Mixing the two is a real bug, not a purism. The application and the database
    are different machines in every deployed environment, and their clocks drift
    independently; locally, Docker Desktop runs PostgreSQL inside a WSL2 VM
    whose clock drifts against the Windows host, particularly after sleep. If
    the database clock runs even slightly ahead, a freshly inserted row looks
    scheduled for the future and the relay silently skips it — intermittently,
    which is the worst way to find out.
"""

import logging
from datetime import timedelta

from sqlalchemy import func, select

from platform_core.events.catalog import ActorType, EventType
from platform_core.events.envelope import EventEnvelope
from platform_core.events.publisher import EventPublisher
from platform_core.models.outbox_event import OutboxEvent, OutboxStatus
from platform_core.tenancy.context import organization_context, system_context

logger = logging.getLogger(__name__)

# After this many failures a row is dead-lettered rather than retried forever.
MAX_ATTEMPTS = 5

# Backoff schedule in seconds, indexed by attempt count. Matches SDD §2.2.
# Jitter is not applied here because the relay is a single scheduled process,
# not many clients stampeding a service.
BACKOFF_SECONDS = (1, 4, 15, 60, 300)


def _to_envelope(row: OutboxEvent) -> EventEnvelope:
    """Rebuild the envelope from a stored outbox row."""
    return EventEnvelope(
        event_id=row.id,
        event_type=EventType(row.event_type),
        schema_version=row.schema_version,
        organization_id=row.organization_id,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        application_id=row.application_id,
        candidate_profile_id=row.candidate_profile_id,
        actor_type=ActorType(row.actor_type),
        actor_id=row.actor_id,
        correlation_id=row.correlation_id,
        causation_id=row.causation_id,
        sequence_number=row.sequence_number,
        payload=row.payload,
        contains_pii=row.contains_pii,
        emitted_at=row.emitted_at,
    )


async def relay_organization(publisher: EventPublisher, batch_size: int = 100) -> tuple[int, int]:
    """
    Publish pending events for the organisation currently in context.

    Args:
        publisher: where to deliver events.
        batch_size: maximum rows to process in one call.

    Returns:
        tuple[int, int]: (published count, failed count).
    """
    from platform_core.db.session import get_session

    published = 0
    failed = 0

    async with get_session() as session:
        # SKIP LOCKED lets multiple relay instances run concurrently: each
        # claims different rows rather than blocking on the same ones.
        #
        # func.now() rather than a Python datetime: both sides of this
        # comparison must come from the same clock. See the module docstring.
        result = await session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.status == OutboxStatus.PENDING.value)
            .where(OutboxEvent.next_attempt_at <= func.now())
            .order_by(OutboxEvent.sequence_number)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        rows = list(result.scalars().all())

        for row in rows:
            try:
                await publisher.publish(_to_envelope(row))
                row.status = OutboxStatus.PUBLISHED.value
                # Database clock, for consistency with next_attempt_at. Every
                # timestamp on this row then comes from one source.
                row.published_at = func.now()
                row.last_error = None
                published += 1

            except Exception as exc:  # noqa: BLE001 - a failing event must not
                # stop the batch; the rest are independent.
                row.attempt_count += 1
                # Truncated: an exception string can be long, and the useful
                # part is at the front.
                row.last_error = str(exc)[:2000]

                if row.attempt_count >= MAX_ATTEMPTS:
                    # Dead-letter. Alerting on the count of Failed rows is the
                    # monitored SLO from SDD §2.2.
                    row.status = OutboxStatus.FAILED.value
                    failed += 1
                    logger.error(
                        "Event dead-lettered after exhausting retries",
                        extra={
                            "event_type": row.event_type,
                            "attempt_count": row.attempt_count,
                            "outbox_event_id": str(row.id),
                        },
                    )
                else:
                    delay = BACKOFF_SECONDS[min(row.attempt_count - 1, len(BACKOFF_SECONDS) - 1)]
                    # now() + interval, evaluated by the database. Computing
                    # this in Python would schedule the retry against a clock
                    # the relay's own query does not use.
                    row.next_attempt_at = func.now() + timedelta(seconds=delay)
                    logger.warning(
                        "Event publication failed; will retry",
                        extra={
                            "event_type": row.event_type,
                            "attempt_count": row.attempt_count,
                            "retry_in_seconds": delay,
                        },
                    )

            session.add(row)

    return published, failed


async def relay_all_organizations(
    publisher: EventPublisher, batch_size: int = 100
) -> tuple[int, int]:
    """
    Run one relay cycle across every organisation.

    Args:
        publisher: where to deliver events.
        batch_size: maximum rows per organisation per cycle.

    Returns:
        tuple[int, int]: total (published, failed) across all organisations.
    """
    from sqlalchemy import text

    from platform_core.db.session import get_system_session

    # Listing organisations is the one documented legitimate use of a system
    # session: you cannot scope by tenant a query whose purpose is to discover
    # which tenants exist. Everything after this runs tenant-scoped.
    with system_context():
        async with get_system_session() as session:
            result = await session.execute(text("SELECT id FROM organizations"))
            organization_ids = [row[0] for row in result]

    total_published = 0
    total_failed = 0

    for organization_id in organization_ids:
        with organization_context(organization_id):
            published, failed = await relay_organization(publisher, batch_size)
            total_published += published
            total_failed += failed

    if total_published or total_failed:
        logger.info(
            "Relay cycle complete",
            extra={
                "published": total_published,
                "failed": total_failed,
                "organizations": len(organization_ids),
            },
        )

    return total_published, total_failed
