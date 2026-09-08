"""
Tenant isolation suite — the test that must never fail.

WHAT THIS PROVES
    That PostgreSQL row-level security actually hides other tenants' rows, in
    both directions (read and write), including when no tenant is set.

WHY IT RUNS ON EVERY PULL REQUEST, FOREVER
    Cross-tenant leakage is the worst failure this system has: a DPDP breach, a
    customer-terminating event, and unrecoverable in reputation terms. It is
    also the kind of bug that is invisible in normal use — everything works
    fine until someone sees data that is not theirs.

    SDD §7.0 makes this a standing requirement rather than a one-off check. It
    lands in week 2 of Phase 0 and never comes out.

WHAT A FAILURE HERE MEANS
    Stop. Do not merge, do not work around it. Every failure in this file is
    either a missing FORCE ROW LEVEL SECURITY, a missing policy on a new table,
    a session that skipped _apply_tenant, or a connection running as a
    privileged role. All four are boundary failures.
"""

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from platform_core.db.session import TENANT_SETTING
from platform_core.db.types import uuid7

pytestmark = pytest.mark.integration  # requires a real PostgreSQL container


async def _set_tenant(session: AsyncSession, org_id: UUID | None) -> None:
    """
    Apply a tenant to the session's transaction.

    Mirrors platform_core.db.session._apply_tenant. Duplicated deliberately:
    if the production helper regressed, a test importing it would regress with
    it and still pass. The test asserts against the database's behaviour, not
    against our own abstraction over it.
    """
    value = str(org_id) if org_id is not None else ""
    await session.execute(text(f"SELECT set_config('{TENANT_SETTING}', :v, true)"), {"v": value})


async def _insert_flag(session: AsyncSession, org_id: UUID, key: str) -> UUID:
    """Insert one feature flag row for an organisation and return its ID."""
    flag_id = uuid7()
    await session.execute(
        text("""
            INSERT INTO feature_flags (id, organization_id, flag_key, enabled)
            VALUES (:id, :org, :key, true)
        """),
        {"id": flag_id, "org": org_id, "key": key},
    )
    return flag_id


async def _count_flags(session: AsyncSession) -> int:
    """Count rows visible in feature_flags under the current tenant setting."""
    result = await session.execute(text("SELECT count(*) FROM feature_flags"))
    return int(result.scalar_one())


# ===========================================================================
# READ ISOLATION
# ===========================================================================


async def test_tenant_sees_only_own_rows(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Organisation A sees its own row and not B's.

    The baseline assertion. If this fails, nothing else in the suite matters.
    """
    org_a, org_b = two_organizations

    # Seed one flag for each organisation, each inside its own tenant context.
    async with session_factory() as s, s.begin():
        await _set_tenant(s, org_a)
        await _insert_flag(s, org_a, "TalentPool")
    async with session_factory() as s, s.begin():
        await _set_tenant(s, org_b)
        await _insert_flag(s, org_b, "AICopilot")

    # A sees exactly one row, and it is A's.
    async with session_factory() as s, s.begin():
        await _set_tenant(s, org_a)
        assert await _count_flags(s) == 1
        result = await s.execute(text("SELECT organization_id FROM feature_flags"))
        assert result.scalar_one() == org_a

    # B likewise sees exactly one row, and it is B's.
    async with session_factory() as s, s.begin():
        await _set_tenant(s, org_b)
        assert await _count_flags(s) == 1
        result = await s.execute(text("SELECT organization_id FROM feature_flags"))
        assert result.scalar_one() == org_b


async def test_no_tenant_set_returns_zero_rows(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    An unset tenant yields no rows, never all rows.

    This is the fail-closed property. A bug that drops the tenant context must
    produce an empty screen, not a cross-tenant data dump.
    """
    org_a, _ = two_organizations

    async with session_factory() as s, s.begin():
        await _set_tenant(s, org_a)
        await _insert_flag(s, org_a, "TalentPool")

    async with session_factory() as s, s.begin():
        await _set_tenant(s, None)  # explicitly no tenant
        assert await _count_flags(s) == 0


async def test_targeted_read_of_another_tenants_row_returns_nothing(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Knowing another tenant's row ID does not grant access to it.

    This is the database-level backstop for IDOR — threat #1 in SDD §1.4.
    Application-layer authorisation is the primary control; this proves that
    even if it were bypassed, the row is still unreachable.
    """
    org_a, org_b = two_organizations

    async with session_factory() as s, s.begin():
        await _set_tenant(s, org_b)
        b_flag_id = await _insert_flag(s, org_b, "InternalNotes")

    async with session_factory() as s, s.begin():
        await _set_tenant(s, org_a)
        result = await s.execute(
            text("SELECT count(*) FROM feature_flags WHERE id = :id"), {"id": b_flag_id}
        )
        assert int(result.scalar_one()) == 0


# ===========================================================================
# WRITE ISOLATION
# ===========================================================================


async def test_cannot_insert_row_for_another_tenant(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Organisation A cannot create a row belonging to B.

    This is what the policy's WITH CHECK clause enforces. Without it, a caller
    could write into another tenant's data even though they could not read it —
    which would be worse than a read leak, not better.
    """
    org_a, org_b = two_organizations

    with pytest.raises(DBAPIError):  # PostgreSQL raises an RLS violation
        async with session_factory() as s, s.begin():
            await _set_tenant(s, org_a)
            await _insert_flag(s, org_b, "TalentPool")  # B's ID under A's context


async def test_cannot_update_another_tenants_row(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    An UPDATE from A does not touch B's rows.

    RLS filters the UPDATE's row set rather than raising, so the assertion is
    that zero rows changed and B's value is intact.
    """
    org_a, org_b = two_organizations

    async with session_factory() as s, s.begin():
        await _set_tenant(s, org_b)
        await _insert_flag(s, org_b, "AICopilot")  # enabled = true

    # A attempts a blanket update.
    async with session_factory() as s, s.begin():
        await _set_tenant(s, org_a)
        result = await s.execute(text("UPDATE feature_flags SET enabled = false"))
        assert result.rowcount == 0

    # B's row is unchanged.
    async with session_factory() as s, s.begin():
        await _set_tenant(s, org_b)
        result = await s.execute(text("SELECT enabled FROM feature_flags"))
        assert result.scalar_one() is True


async def test_cannot_delete_another_tenants_row(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """A blanket DELETE from A removes none of B's rows."""
    org_a, org_b = two_organizations

    async with session_factory() as s, s.begin():
        await _set_tenant(s, org_b)
        await _insert_flag(s, org_b, "KitDispatch")

    async with session_factory() as s, s.begin():
        await _set_tenant(s, org_a)
        result = await s.execute(text("DELETE FROM feature_flags"))
        assert result.rowcount == 0

    async with session_factory() as s, s.begin():
        await _set_tenant(s, org_b)
        assert await _count_flags(s) == 1


# ===========================================================================
# CONNECTION POOL SAFETY
# ===========================================================================


async def test_tenant_does_not_leak_across_transactions(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    A tenant setting does not survive its transaction.

    This is the pooled-connection footgun described in session.py. If
    set_config were called without is_local=true, the setting would persist on
    the connection and the next request to reuse it would silently inherit the
    previous tenant's identity.

    The test runs two transactions in sequence and asserts the second starts
    with no tenant. It is the single most important test in this file, because
    the bug it catches is invisible under load testing and catastrophic in
    production.
    """
    org_a, _ = two_organizations

    async with session_factory() as s, s.begin():
        await _set_tenant(s, org_a)
        await _insert_flag(s, org_a, "TalentPool")

    async with session_factory() as s, s.begin():
        # Deliberately do NOT set a tenant. If the previous transaction's
        # setting leaked, this would see A's row.
        result = await s.execute(text(f"SELECT current_setting('{TENANT_SETTING}', true)"))
        leaked = result.scalar_one()
        assert leaked in (None, ""), f"Tenant leaked across transactions: {leaked!r}"
        assert await _count_flags(s) == 0


# ===========================================================================
# CONFIGURATION GUARDS
# ===========================================================================


async def test_application_role_is_not_superuser(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """
    The application connects as a non-superuser.

    PostgreSQL exempts superusers from RLS. If the application ever connected as
    one, every test above would still pass while every policy did nothing — the
    most dangerous kind of green build. This asserts the premise they all rest on.
    """
    async with session_factory() as s, s.begin():
        result = await s.execute(text("SELECT usesuper FROM pg_user WHERE usename = current_user"))
        assert result.scalar_one() is False, (
            "Application role has superuser privileges — row-level security is "
            "being bypassed and every isolation test above is meaningless."
        )


async def test_rls_is_forced_on_tenant_tables(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """
    Every tenant-scoped table has RLS both enabled and FORCED.

    Catches the most common mistake when adding a table: enabling RLS but
    forgetting FORCE, which leaves the owning role exempt.

    As tables are added in Phase 1 onward, add them to this list. A tenant-scoped
    table missing from it is a gap in the boundary.
    """
    # Every tenant-scoped table. A table added to a migration but missing from
    # this list is a hole in the boundary that nothing else would catch.
    tenant_scoped_tables = [
        "feature_flags",
        "roles",
        "identity_provider_configs",
        "users",
        "role_assignments",
        "outbox_events",
        "processed_events",
        "audit_entries",
        "sla_policies",
        "holidays",
        "approval_delegations",
        "approval_requests",
        "approval_actions",
        "notification_templates",
        "notification_logs",
    ]

    async with session_factory() as s, s.begin():
        for table in tenant_scoped_tables:
            result = await s.execute(
                text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"),
                {"t": table},
            )
            enabled, forced = result.one()
            assert enabled, f"{table}: RLS is not enabled"
            assert forced, (
                f"{table}: RLS is enabled but not FORCED. The table owner "
                f"bypasses every policy. Add ALTER TABLE {table} FORCE ROW "
                f"LEVEL SECURITY to the migration."
            )
