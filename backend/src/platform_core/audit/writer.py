"""
Audit writer — appends entries and maintains the hash chain.

THE CONCURRENCY PROBLEM
    Each entry hashes the previous entry's hash. Two writers reading the same
    "last entry" at the same time would both compute the same previous_hash and
    both claim the same chain position, forking the chain.

    The fix is a PostgreSQL advisory lock keyed on the organisation, taken
    before reading the tail. It serialises audit writes within one tenant while
    leaving every other tenant unaffected, and it is released automatically when
    the transaction ends — including when it aborts, which a manually released
    lock would not be.

    The alternative is SERIALIZABLE isolation, which is heavier and turns the
    contention into serialisation failures the caller has to retry.

ORDERING WITHIN THE TRANSACTION
    The lock is taken inside the caller's transaction, so it is held for the
    remainder of that transaction. Audit writes should therefore happen near the
    end of a unit of work, not the start — holding a per-tenant lock across a
    long transaction serialises that tenant's writes for its duration.
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.audit.hashing import compute_entry_hash
from platform_core.auth.principal import get_principal_or_none
from platform_core.db.types import uuid7
from platform_core.events.catalog import ActorType, EventType
from platform_core.events.consumer import EventConsumer
from platform_core.events.envelope import EventEnvelope
from platform_core.models.audit_entry import GENESIS_HASH, AuditEntry
from platform_core.observability.context import get_correlation_id
from platform_core.tenancy.context import get_organization

logger = logging.getLogger(__name__)


def _advisory_lock_key(organization_id: UUID) -> int:
    """
    Derive a stable 64-bit advisory lock key from an organisation ID.

    PostgreSQL advisory locks are keyed on bigint, so the UUID is truncated to
    its first eight bytes. Collisions between organisations are possible in
    principle and harmless in practice: two tenants sharing a key would
    serialise against each other, which costs a little concurrency and breaks
    nothing.

    Args:
        organization_id: the tenant.

    Returns:
        int: a signed 64-bit lock key.
    """
    return int.from_bytes(organization_id.bytes[:8], byteorder="big", signed=True)


async def append_audit_entry(
    session: AsyncSession,
    *,
    action_type: str,
    entity_type: str,
    entity_id: UUID,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    event_id: UUID | None = None,
    actor_type: ActorType | None = None,
    actor_id: UUID | None = None,
    actor_role: str | None = None,
    ip_address: str | None = None,
    session_id: str | None = None,
    notes: str | None = None,
) -> AuditEntry:
    """
    Append one entry to the organisation's audit chain.

    Uses the caller's session and transaction, so the audit entry commits with
    whatever it records. An entry that could commit independently of the action
    it describes would be able to record things that did not happen.

    Args:
        session: the caller's session, already in a transaction.
        action_type: what happened.
        entity_type: what it happened to.
        entity_id: which one.
        before_state: prior state. Identifiers and status values only.
        after_state: resulting state. Same rule.
        event_id: the domain event that produced this, where applicable.
        actor_type: overrides the actor inferred from context.
        actor_id: overrides the user inferred from context.
        actor_role: the role in effect, recorded as it was at the time.
        ip_address: the caller's address, where known.
        session_id: the session, where known.
        notes: free text. Must contain no PII.

    Returns:
        AuditEntry: the appended entry, with its hash and chain position set.

    Raises:
        TenantContextError: if no organisation is in context.
    """
    organization_id = get_organization()

    # Serialise chain writes for this tenant. pg_advisory_xact_lock releases at
    # transaction end automatically, including on rollback.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": _advisory_lock_key(organization_id)},
    )

    # Read the tail of the chain. Safe to do unlocked-free now: the advisory
    # lock above means no other writer for this tenant can be between here and
    # our insert.
    result = await session.execute(
        select(AuditEntry.chain_position, AuditEntry.entry_hash)
        .order_by(AuditEntry.chain_position.desc())
        .limit(1)
    )
    tail = result.first()

    if tail is None:
        chain_position = 1
        previous_hash = GENESIS_HASH
    else:
        chain_position = tail.chain_position + 1
        previous_hash = tail.entry_hash

    # Infer the actor from context unless overridden.
    if actor_type is None:
        principal = get_principal_or_none()
        if principal is not None:
            actor_type = ActorType.USER
            actor_id = principal.user_id
        else:
            actor_type = ActorType.SYSTEM
            actor_id = None

    # Assigned here, not by the database, because it is part of the hashed
    # content and must be known before the hash is computed.
    occurred_at = datetime.now(UTC)
    correlation_id = get_correlation_id()

    entry_hash = compute_entry_hash(
        organization_id=organization_id,
        chain_position=chain_position,
        previous_hash=previous_hash,
        actor_type=actor_type.value,
        actor_id=actor_id,
        actor_role=actor_role,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        before_state=before_state,
        after_state=after_state,
        correlation_id=correlation_id,
        event_id=event_id,
        occurred_at=occurred_at,
    )

    entry = AuditEntry(
        id=uuid7(),
        organization_id=organization_id,
        chain_position=chain_position,
        previous_hash=previous_hash,
        entry_hash=entry_hash,
        actor_type=actor_type.value,
        actor_id=actor_id,
        actor_role=actor_role,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        before_state=before_state,
        after_state=after_state,
        correlation_id=correlation_id,
        event_id=event_id,
        ip_address=ip_address,
        session_id=session_id,
        occurred_at=occurred_at,
        notes=notes,
    )
    session.add(entry)
    return entry


class AuditConsumer(EventConsumer):
    """
    Writes an audit entry for every domain event.

    Subscribes to everything. `subscribes_to` is left at its empty default,
    which the registry reads as "all event types" — enumerating all ninety-five
    would produce a list guaranteed to fall out of date, and a missing entry
    there would be a silent gap in the audit trail.

    The entry and the idempotency marker share the consumer's transaction, so a
    duplicate delivery cannot append a duplicate entry — which matters here more
    than elsewhere, because a duplicated audit entry looks like the action
    happened twice.
    """

    name = "audit_log_writer"
    subscribes_to = frozenset()  # all events

    async def handle(self, envelope: EventEnvelope, session: AsyncSession) -> None:
        """
        Append an audit entry describing this event.

        Args:
            envelope: the event.
            session: tenant-scoped session inside a transaction.
        """
        await append_audit_entry(
            session,
            action_type=envelope.event_type.value,
            entity_type=envelope.entity_type,
            entity_id=envelope.entity_id,
            # The payload carries identifiers and state transitions, never PII
            # (SDD §2.1), so it is safe to record verbatim as the resulting
            # state. If that rule is ever broken, it is broken here too.
            after_state=envelope.payload or None,
            event_id=envelope.event_id,
            actor_type=ActorType(envelope.actor_type),
            actor_id=envelope.actor_id,
        )


# Event types that must always produce an audit entry, whatever else changes.
# Used by the acceptance tests: these are the ones a compliance review will ask
# to see, so a regression that stopped auditing them should fail the build.
COMPLIANCE_CRITICAL_EVENTS = frozenset(
    {
        EventType.SENSITIVE_DATA_ACCESSED,
        EventType.PII_EXPORTED,
        EventType.CONSENT_GRANTED,
        EventType.CONSENT_REVOKED,
        EventType.PROFILES_MERGED,
        EventType.RETENTION_PURGE_EXECUTED,
        EventType.OFFER_SIGNED,
        EventType.BGV_FLAG_RESOLVED,
        EventType.APPROVAL_GRANTED,
    }
)
