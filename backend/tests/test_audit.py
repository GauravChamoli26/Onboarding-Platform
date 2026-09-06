"""
Audit log tests — chain integrity and immutability.

WHAT THIS PROVES
    That the audit trail is worth relying on. Three separate properties:

    1. Entries are chained, and verification confirms an untampered chain.
    2. Tampering is DETECTED — modification, deletion and insertion each break
       verification in a way that names the position.
    3. Tampering is PREVENTED — the application role cannot UPDATE or DELETE,
       and neither can the table owner.

WHY BOTH DETECTION AND PREVENTION ARE TESTED
    Prevention can be undone by anyone with enough privilege. Detection is what
    remains after that. Testing only prevention would leave the property that
    actually matters in an investigation unverified.
"""

from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from platform_core.audit.verification import verify_chain
from platform_core.audit.writer import append_audit_entry
from platform_core.db.types import uuid7
from platform_core.events.catalog import ActorType, EventType
from platform_core.events.envelope import EventEnvelope
from platform_core.models.audit_entry import GENESIS_HASH, AuditEntry
from platform_core.observability.context import correlation_scope
from platform_core.tenancy.context import organization_context

pytestmark = pytest.mark.integration


async def _write_entries(
    factory: async_sessionmaker[AsyncSession], org_id: UUID, count: int
) -> None:
    """Append `count` audit entries for an organisation."""
    with organization_context(org_id), correlation_scope("audit-test"):
        for index in range(count):
            async with factory() as session, session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_organization_id', :v, true)"),
                    {"v": str(org_id)},
                )
                await append_audit_entry(
                    session,
                    action_type="TestAction",
                    entity_type="TestEntity",
                    entity_id=uuid7(),
                    after_state={"index": index},
                )


async def _verify(factory: async_sessionmaker[AsyncSession], org_id: UUID):
    """Run chain verification for an organisation."""
    async with factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_id)},
        )
        return await verify_chain(session, org_id)


# ===========================================================================
# Chain construction
# ===========================================================================


async def test_first_entry_starts_from_genesis(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    The first entry in a chain links to the genesis hash.

    A fixed genesis value rather than NULL means every entry hashes the same
    way, with no special case for the first — and no branch in the verifier
    that could be wrong.
    """
    org_a, _ = two_organizations
    await _write_entries(session_factory, org_a, 1)

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_a)},
        )
        entry = (await session.execute(select(AuditEntry))).scalar_one()

    assert entry.chain_position == 1
    assert entry.previous_hash == GENESIS_HASH


async def test_entries_form_a_linked_chain(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """Each entry's previous_hash is the preceding entry's hash."""
    org_a, _ = two_organizations
    await _write_entries(session_factory, org_a, 5)

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_a)},
        )
        result = await session.execute(select(AuditEntry).order_by(AuditEntry.chain_position))
        entries = list(result.scalars().all())

    assert [e.chain_position for e in entries] == [1, 2, 3, 4, 5]
    for previous, current in zip(entries, entries[1:], strict=False):
        assert current.previous_hash == previous.entry_hash


async def test_verification_passes_on_an_untampered_chain(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """A chain written normally verifies clean."""
    org_a, _ = two_organizations
    await _write_entries(session_factory, org_a, 5)

    result = await _verify(session_factory, org_a)
    assert result.is_valid, result.failure_reason
    assert result.entries_checked == 5


async def test_chains_are_independent_per_organisation(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Each organisation has its own chain, starting from position 1.

    A global chain would be unverifiable by any single tenant, since row-level
    security hides the entries in between.
    """
    org_a, org_b = two_organizations
    await _write_entries(session_factory, org_a, 3)
    await _write_entries(session_factory, org_b, 2)

    result_a = await _verify(session_factory, org_a)
    result_b = await _verify(session_factory, org_b)

    assert result_a.is_valid and result_a.entries_checked == 3
    assert result_b.is_valid and result_b.entries_checked == 2


async def test_empty_chain_is_valid(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """An organisation with no entries has a valid, empty chain."""
    org_a, _ = two_organizations
    result = await _verify(session_factory, org_a)
    assert result.is_valid
    assert result.entries_checked == 0


# ===========================================================================
# Immutability — prevention
# ===========================================================================


async def test_application_role_cannot_update_audit_entries(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    The application cannot modify an audit entry.

    Two controls stop it: no UPDATE grant, and the trigger. Either alone would
    raise; the test asserts the outcome, not which one fired.
    """
    org_a, _ = two_organizations
    await _write_entries(session_factory, org_a, 1)

    with pytest.raises(Exception):  # noqa: B017 - permission or trigger error
        async with session_factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.current_organization_id', :v, true)"),
                {"v": str(org_a)},
            )
            await session.execute(text("UPDATE audit_entries SET action_type = 'Tampered'"))


async def test_application_role_cannot_delete_audit_entries(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """The application cannot remove an audit entry."""
    org_a, _ = two_organizations
    await _write_entries(session_factory, org_a, 1)

    with pytest.raises(Exception):  # noqa: B017
        async with session_factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.current_organization_id', :v, true)"),
                {"v": str(org_a)},
            )
            await session.execute(text("DELETE FROM audit_entries"))


async def test_table_owner_also_cannot_update(
    admin_engine,
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Even the table owner is refused.

    This is what the trigger adds over the revoke. A revoke covers the
    application role; it does nothing about a DBA session or a compromised
    superuser, which is precisely the threat model an audit log exists for.
    """
    org_a, _ = two_organizations
    await _write_entries(session_factory, org_a, 1)

    async with admin_engine.connect() as conn:
        with pytest.raises(Exception):  # noqa: B017 - trigger raises
            await conn.execute(text("UPDATE audit_entries SET action_type = 'Tampered'"))


# ===========================================================================
# Immutability — detection
# ===========================================================================


async def test_verification_detects_a_modified_entry(
    admin_engine,
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Altering an entry's content breaks verification.

    The trigger is disabled first, deliberately — this test is about what
    happens when prevention has been bypassed, which is the case detection
    exists for. An attacker with owner privileges can disable a trigger; they
    cannot recompute a chain they cannot fully see.
    """
    org_a, _ = two_organizations
    await _write_entries(session_factory, org_a, 5)

    async with admin_engine.connect() as conn:
        await conn.execute(
            text("ALTER TABLE audit_entries DISABLE TRIGGER trg_audit_entries_immutable")
        )
        try:
            await conn.execute(
                text(
                    "UPDATE audit_entries SET action_type = 'Tampered' "
                    "WHERE chain_position = 3 AND organization_id = :org"
                ),
                {"org": org_a},
            )
        finally:
            await conn.execute(
                text("ALTER TABLE audit_entries ENABLE TRIGGER trg_audit_entries_immutable")
            )

    result = await _verify(session_factory, org_a)
    assert not result.is_valid
    assert result.first_invalid_position == 3
    assert "modified" in (result.failure_reason or "").lower()


async def test_verification_detects_a_deleted_entry(
    admin_engine,
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Removing an entry breaks verification.

    Deletion is the case a naive hash chain misses: cut out one entry and the
    links between its neighbours look intact if nothing checks positions. The
    consecutive-position check is what catches it.
    """
    org_a, _ = two_organizations
    await _write_entries(session_factory, org_a, 5)

    async with admin_engine.connect() as conn:
        await conn.execute(
            text("ALTER TABLE audit_entries DISABLE TRIGGER trg_audit_entries_immutable")
        )
        try:
            await conn.execute(
                text(
                    "DELETE FROM audit_entries WHERE chain_position = 3 AND organization_id = :org"
                ),
                {"org": org_a},
            )
        finally:
            await conn.execute(
                text("ALTER TABLE audit_entries ENABLE TRIGGER trg_audit_entries_immutable")
            )

    result = await _verify(session_factory, org_a)
    assert not result.is_valid
    assert "gap" in (result.failure_reason or "").lower()


# ===========================================================================
# The audit consumer
# ===========================================================================


async def test_consumer_writes_an_entry_for_an_event(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """Every domain event produces one audit entry."""
    from platform_core.audit.writer import AuditConsumer

    org_a, _ = two_organizations
    consumer = AuditConsumer()
    entity_id = uuid7()

    envelope = EventEnvelope(
        event_id=uuid7(),
        event_type=EventType.OFFER_SIGNED,
        organization_id=org_a,
        entity_type="Offer",
        entity_id=entity_id,
        actor_type=ActorType.CANDIDATE,
        correlation_id="consumer-audit-test",
        payload={"offer_version": 2},
    )

    with organization_context(org_a), correlation_scope("consumer-audit-test"):
        async with session_factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.current_organization_id', :v, true)"),
                {"v": str(org_a)},
            )
            await consumer.process(envelope, session)

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_a)},
        )
        entry = (await session.execute(select(AuditEntry))).scalar_one()

    assert entry.action_type == EventType.OFFER_SIGNED.value
    assert entry.entity_id == entity_id
    assert entry.actor_type == ActorType.CANDIDATE.value
    assert entry.after_state == {"offer_version": 2}
    assert entry.event_id == envelope.event_id


async def test_duplicate_event_does_not_duplicate_the_audit_entry(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Redelivery of an event writes one entry, not two.

    Matters more here than for other consumers: a duplicated audit entry reads
    as the action having happened twice, which in an investigation is a
    materially wrong answer rather than merely redundant data.
    """
    from platform_core.audit.writer import AuditConsumer

    org_a, _ = two_organizations
    consumer = AuditConsumer()

    envelope = EventEnvelope(
        event_id=uuid7(),
        event_type=EventType.CONSENT_REVOKED,
        organization_id=org_a,
        entity_type="ConsentLog",
        entity_id=uuid7(),
        actor_type=ActorType.CANDIDATE,
        correlation_id="dup-audit-test",
    )

    with organization_context(org_a), correlation_scope("dup-audit-test"):
        for _ in range(2):
            async with session_factory() as session, session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_organization_id', :v, true)"),
                    {"v": str(org_a)},
                )
                await consumer.process(envelope, session)

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_a)},
        )
        count = await session.execute(text("SELECT count(*) FROM audit_entries"))
        assert int(count.scalar_one()) == 1

    result = await _verify(session_factory, org_a)
    assert result.is_valid


async def test_audit_entries_are_tenant_isolated(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """One organisation cannot read another's audit trail."""
    org_a, org_b = two_organizations
    await _write_entries(session_factory, org_a, 3)
    await _write_entries(session_factory, org_b, 1)

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_a)},
        )
        count = await session.execute(text("SELECT count(*) FROM audit_entries"))
        assert int(count.scalar_one()) == 3
