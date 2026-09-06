"""
Event emission — writing to the outbox inside the caller's transaction.

THE ONE RULE
    `emit_event` uses the session you pass it. It does not commit, and it does
    not open its own transaction. The event row is therefore part of whatever
    unit of work the caller is already performing, and commits or rolls back
    with it.

    Calling `session.commit()` inside this function would break the entire
    guarantee, which is why it does not.

WHAT COMES FROM CONTEXT
    Organisation, correlation ID and actor are all read from context variables
    rather than passed by the caller. That keeps call sites short and, more
    importantly, means they cannot get them wrong — an event attributed to the
    wrong actor is worse than no event.

Example:
    async with get_session() as session:
        application.status = "Shortlisted"
        session.add(application)
        await emit_event(
            session,
            event_type=EventType.SHORTLISTED,
            entity_type="Application",
            entity_id=application.id,
            application_id=application.id,
            payload={"from_status": "Scored", "to_status": "Shortlisted"},
        )
    # One transaction. Both the state change and the event, or neither.
"""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.auth.principal import get_principal_or_none
from platform_core.db.types import uuid7
from platform_core.events.catalog import ActorType, EventType
from platform_core.events.envelope import CURRENT_SCHEMA_VERSION
from platform_core.models.outbox_event import OutboxEvent
from platform_core.observability.context import get_correlation_id
from platform_core.tenancy.context import get_organization

logger = logging.getLogger(__name__)


async def emit_event(
    session: AsyncSession,
    *,
    event_type: EventType,
    entity_type: str,
    entity_id: UUID,
    payload: dict[str, Any] | None = None,
    application_id: UUID | None = None,
    candidate_profile_id: UUID | None = None,
    causation_id: UUID | None = None,
    contains_pii: bool = False,
    actor_type: ActorType | None = None,
    actor_id: UUID | None = None,
) -> UUID:
    """
    Write a domain event to the outbox within the caller's transaction.

    Args:
        session: the session performing the state change. Not committed here.
        event_type: which event, from the catalogue.
        entity_type: the entity this concerns, e.g. "Application".
        entity_id: that entity's ID.
        payload: identifiers and state transitions. **Never PII** — see the note
            below.
        application_id: denormalised so the Timeline needs no join. Optional.
        candidate_profile_id: likewise.
        causation_id: the event that caused this one, where applicable.
        contains_pii: set True only if the payload genuinely must carry personal
            data. Drives redaction downstream. Defaults False, and should stay
            False in practice.
        actor_type: overrides the actor inferred from context. Used by system
            jobs and vendor webhooks, which have no principal.
        actor_id: overrides the user inferred from context.

    Returns:
        UUID: the new event's ID, usable as a `causation_id` for anything this
        action goes on to trigger.

    Raises:
        TenantContextError: if no organisation is in context. An event that
            cannot be attributed to a tenant is not one we can store.

    ON PAYLOADS AND PII
        The payload rule is what keeps the event store outside the retention
        purge path. Events are append-only; if they contained personal data,
        every purge would have to rewrite history, which an append-only log
        cannot do. Pass identifiers, not values.
    """
    organization_id = get_organization()

    # Infer the actor from context unless the caller overrode it. A system job
    # has no principal, and attributing its action to a user would make the
    # audit trail lie.
    if actor_type is None:
        principal = get_principal_or_none()
        if principal is not None:
            actor_type = ActorType.USER
            actor_id = principal.user_id
        else:
            actor_type = ActorType.SYSTEM
            actor_id = None

    event_id = uuid7()

    session.add(
        OutboxEvent(
            id=event_id,
            organization_id=organization_id,
            event_type=event_type.value,
            schema_version=CURRENT_SCHEMA_VERSION,
            entity_type=entity_type,
            entity_id=entity_id,
            application_id=application_id,
            candidate_profile_id=candidate_profile_id,
            actor_type=actor_type.value,
            actor_id=actor_id,
            correlation_id=get_correlation_id(),
            causation_id=causation_id,
            payload=payload or {},
            contains_pii=contains_pii,
        )
    )

    # Deliberately no commit. The caller's transaction owns this row, which is
    # the entire point of the outbox pattern.

    logger.debug(
        "Event queued to outbox",
        extra={"event_type": event_type.value, "entity_type": entity_type},
    )
    return event_id
