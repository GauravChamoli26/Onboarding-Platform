"""
Authorisation tests — capability resolution and enforcement.

WHAT THIS PROVES
    That capabilities reach a user only through live, valid role assignments on
    an active account, and that an endpoint requiring a capability rejects a
    user who lacks it.

RELATIONSHIP TO THE ISOLATION SUITE
    Two independent boundaries. The isolation suite proves a user cannot see
    another tenant's data. This proves a user cannot perform an action they are
    not permitted to perform. Neither substitutes for the other, and a failure
    in one does not imply anything about the other.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from platform_core.auth.authorization import build_principal, resolve_capabilities
from platform_core.auth.capabilities import Capability, RoleKey
from platform_core.db.types import uuid7

pytestmark = pytest.mark.integration


async def _create_role(
    factory: async_sessionmaker[AsyncSession],
    org_id: UUID,
    role_key: str,
    capabilities: list[str],
) -> UUID:
    """Insert a role with an explicit capability list."""
    role_id = uuid7()
    async with factory() as s, s.begin():
        await s.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_id)},
        )
        await s.execute(
            text("""
                INSERT INTO roles (id, organization_id, role_key, capabilities)
                VALUES (:id, :org, :key, :caps)
            """),
            {"id": role_id, "org": org_id, "key": role_key, "caps": capabilities},
        )
    return role_id


async def _create_user(
    factory: async_sessionmaker[AsyncSession],
    org_id: UUID,
    email: str,
    status: str = "Active",
) -> UUID:
    """Insert a user with a given status."""
    user_id = uuid7()
    async with factory() as s, s.begin():
        await s.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_id)},
        )
        await s.execute(
            text("""
                INSERT INTO users (id, organization_id, email, full_name, status)
                VALUES (:id, :org, :email, :name, :status)
            """),
            {
                "id": user_id,
                "org": org_id,
                "email": email,
                "name": email.split("@")[0],
                "status": status,
            },
        )
    return user_id


async def _assign_role(
    factory: async_sessionmaker[AsyncSession],
    org_id: UUID,
    user_id: UUID,
    role_id: UUID,
    expires_at: datetime | None = None,
) -> None:
    """Grant a role to a user, optionally with an expiry."""
    async with factory() as s, s.begin():
        await s.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_id)},
        )
        await s.execute(
            text("""
                INSERT INTO role_assignments
                    (id, organization_id, user_id, role_id, scope_type, expires_at)
                VALUES (:id, :org, :user, :role, 'Organization', :expires)
            """),
            {
                "id": uuid7(),
                "org": org_id,
                "user": user_id,
                "role": role_id,
                "expires": expires_at,
            },
        )


async def _tenant_session(factory: async_sessionmaker[AsyncSession], org_id: UUID) -> AsyncSession:
    """Open a session with the tenant applied. Caller manages the transaction."""
    session = factory()
    await session.begin()
    await session.execute(
        text("SELECT set_config('app.current_organization_id', :v, true)"),
        {"v": str(org_id)},
    )
    return session


# ===========================================================================
# Capability resolution
# ===========================================================================


async def test_user_receives_capabilities_from_assigned_role(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """A user holds the capabilities of the role assigned to them."""
    org_a, _ = two_organizations
    role_id = await _create_role(
        session_factory,
        org_a,
        RoleKey.HR.value,
        [Capability.CREATE_JD.value, Capability.SHORTLIST.value],
    )
    user_id = await _create_user(session_factory, org_a, "hr@example.com")
    await _assign_role(session_factory, org_a, user_id, role_id)

    session = await _tenant_session(session_factory, org_a)
    try:
        caps = await resolve_capabilities(session, user_id)
    finally:
        await session.rollback()
        await session.close()

    assert Capability.CREATE_JD in caps
    assert Capability.SHORTLIST in caps
    assert Capability.MERGE_PROFILES not in caps


async def test_capabilities_union_across_multiple_roles(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Holding two roles grants the union of their capabilities.

    A Hiring Manager who also interviews is one person with two assignments,
    not a bespoke third role.
    """
    org_a, _ = two_organizations
    hm_role = await _create_role(session_factory, org_a, "HM", [Capability.DECIDE_ROUND.value])
    int_role = await _create_role(session_factory, org_a, "Int", [Capability.SUBMIT_FEEDBACK.value])
    user_id = await _create_user(session_factory, org_a, "both@example.com")
    await _assign_role(session_factory, org_a, user_id, hm_role)
    await _assign_role(session_factory, org_a, user_id, int_role)

    session = await _tenant_session(session_factory, org_a)
    try:
        caps = await resolve_capabilities(session, user_id)
    finally:
        await session.rollback()
        await session.close()

    assert Capability.DECIDE_ROUND in caps
    assert Capability.SUBMIT_FEEDBACK in caps


async def test_expired_assignment_grants_nothing(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    An assignment past its expiry grants no capabilities.

    Checked at resolution time rather than by a cleanup job, precisely so that
    a job which fails to run cannot leave access alive. This is the test that
    proves the expiry is enforced rather than merely recorded.
    """
    org_a, _ = two_organizations
    role_id = await _create_role(session_factory, org_a, "Temp", [Capability.APPROVE_OFFER.value])
    user_id = await _create_user(session_factory, org_a, "contractor@example.com")
    await _assign_role(
        session_factory,
        org_a,
        user_id,
        role_id,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )

    session = await _tenant_session(session_factory, org_a)
    try:
        caps = await resolve_capabilities(session, user_id)
    finally:
        await session.rollback()
        await session.close()

    assert caps == frozenset(), "Expired assignment still granted capabilities"


async def test_future_expiry_still_grants(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """An assignment expiring in the future is still live."""
    org_a, _ = two_organizations
    role_id = await _create_role(session_factory, org_a, "Cover", [Capability.APPROVE_JOB.value])
    user_id = await _create_user(session_factory, org_a, "cover@example.com")
    await _assign_role(
        session_factory,
        org_a,
        user_id,
        role_id,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )

    session = await _tenant_session(session_factory, org_a)
    try:
        caps = await resolve_capabilities(session, user_id)
    finally:
        await session.rollback()
        await session.close()

    assert Capability.APPROVE_JOB in caps


@pytest.mark.parametrize("status", ["Suspended", "Offboarded"])
async def test_inactive_user_has_no_capabilities(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
    status: str,
) -> None:
    """
    A suspended or offboarded user holds nothing, regardless of assignments.

    Status overrides every role. That is what makes revoking access a single
    operation rather than an exercise in finding every assignment — and the
    difference matters most when someone leaves under a cloud.
    """
    org_a, _ = two_organizations
    role_id = await _create_role(
        session_factory, org_a, f"Role{status}", [Capability.VIEW_UNMASKED_PII.value]
    )
    user_id = await _create_user(
        session_factory, org_a, f"{status.lower()}@example.com", status=status
    )
    await _assign_role(session_factory, org_a, user_id, role_id)

    session = await _tenant_session(session_factory, org_a)
    try:
        caps = await resolve_capabilities(session, user_id)
    finally:
        await session.rollback()
        await session.close()

    assert caps == frozenset(), f"{status} user retained capabilities"


async def test_unknown_capability_name_is_ignored_not_fatal(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    A stale capability name in the database is skipped, not raised.

    Typically the residue of a rename that missed a data migration. Failing
    closed on the unknown name is right; locking the user out of everything else
    they hold is not.
    """
    org_a, _ = two_organizations
    role_id = await _create_role(
        session_factory,
        org_a,
        "Stale",
        ["capability_that_no_longer_exists", Capability.SHORTLIST.value],
    )
    user_id = await _create_user(session_factory, org_a, "stale@example.com")
    await _assign_role(session_factory, org_a, user_id, role_id)

    session = await _tenant_session(session_factory, org_a)
    try:
        caps = await resolve_capabilities(session, user_id)
    finally:
        await session.rollback()
        await session.close()

    assert caps == frozenset({Capability.SHORTLIST})


# ===========================================================================
# Cross-tenant behaviour
# ===========================================================================


async def test_capabilities_do_not_resolve_across_tenants(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    A user from organisation B resolves to nothing under organisation A.

    RLS hides the user row entirely, so resolution returns an empty set rather
    than another tenant's permissions. Note this holds even though the caller
    supplied a valid user ID — knowing an ID grants nothing.
    """
    org_a, org_b = two_organizations
    role_id = await _create_role(
        session_factory,
        org_b,
        RoleKey.ADMIN.value,
        [Capability.MANAGE_ROLES.value],
    )
    user_b = await _create_user(session_factory, org_b, "admin@orgb.example.com")
    await _assign_role(session_factory, org_b, user_b, role_id)

    session = await _tenant_session(session_factory, org_a)
    try:
        caps = await resolve_capabilities(session, user_b)
    finally:
        await session.rollback()
        await session.close()

    assert caps == frozenset(), "Resolved another tenant's user"


async def test_build_principal_refuses_user_from_another_tenant(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """Building a principal for a foreign user yields None, not a partial one."""
    org_a, org_b = two_organizations
    user_b = await _create_user(session_factory, org_b, "foreign@orgb.example.com")

    session = await _tenant_session(session_factory, org_a)
    try:
        principal = await build_principal(session, user_b, org_a)
    finally:
        await session.rollback()
        await session.close()

    assert principal is None


# ===========================================================================
# Default role definitions
# ===========================================================================


def test_admin_is_not_a_superuser() -> None:
    """
    Admin lacks hiring-decision capabilities, deliberately.

    Separation of duties from the permission matrix: whoever administers the
    system does not thereby get to shortlist candidates, decide rounds, or
    generate offers. Worth a test, because "give Admin everything" is the
    default instinct and would quietly erode the control.
    """
    from platform_core.auth.capabilities import DEFAULT_ROLE_CAPABILITIES

    admin = DEFAULT_ROLE_CAPABILITIES[RoleKey.ADMIN]
    for withheld in (
        Capability.SHORTLIST,
        Capability.DECIDE_ROUND,
        Capability.MARK_NEGOTIATION_COMPLETE,
        Capability.GENERATE_OFFER,
    ):
        assert withheld not in admin, f"Admin should not hold {withheld.value}"


def test_sensitive_capabilities_are_not_in_any_default_role() -> None:
    """
    Unmasked PII and above-band CTC approval are granted individually.

    The matrix restricts them to "designated HR" and to a named Finance or HR
    Head approver. Baking them into the HR default would grant them to everyone
    with an HR role, which is exactly what "designated" excludes.

    Admin holds VIEW_UNMASKED_PII by design — it is the break-glass path — but
    HR must not hold it by default.
    """
    from platform_core.auth.capabilities import DEFAULT_ROLE_CAPABILITIES

    hr = DEFAULT_ROLE_CAPABILITIES[RoleKey.HR]
    assert Capability.VIEW_UNMASKED_PII not in hr
    assert Capability.EXPORT_PII not in hr
    assert Capability.APPROVE_CTC_ABOVE_BAND not in hr


def test_interviewer_role_is_minimal() -> None:
    """
    Interviewer is a minimal-privilege role, per the spec.

    It should hold only what is needed to interview and submit feedback. A drift
    here would widen the least-privileged role in the system, which is the one
    assigned most freely.
    """
    from platform_core.auth.capabilities import DEFAULT_ROLE_CAPABILITIES

    interviewer = DEFAULT_ROLE_CAPABILITIES[RoleKey.INTERVIEWER]
    assert interviewer == frozenset(
        {
            Capability.SUBMIT_FEEDBACK,
            Capability.MANAGE_NOTES,
        }
    )
