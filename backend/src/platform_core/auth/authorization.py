"""
Authorisation — resolving and enforcing capabilities.

TWO PIECES
    `resolve_capabilities` reads a user's effective capabilities from the
    database. `require_capability` is a FastAPI dependency that rejects a
    request lacking one.

THE RESOLUTION RULES, IN ORDER
    1. A user who is not Active has no capabilities. Status overrides every
       role assignment they hold — one field revokes access, rather than
       unpicking assignments one at a time.
    2. An assignment past its expiry grants nothing. Checked at read time, not
       by a cleanup job, so a job that fails to run cannot leave access alive.
    3. Effective capabilities are the union across remaining assignments.

WHY THIS IS NOT THE ONLY BOUNDARY
    Capabilities answer "may this person do this?". Row-level security answers
    "whose data is this?" and is enforced by the database (ADR-002). A user with
    every capability still sees only their own organisation's rows. Neither
    layer substitutes for the other, and a bug in this file cannot cause a
    cross-tenant leak.
"""

import logging
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.auth.capabilities import Capability
from platform_core.auth.principal import Principal, get_principal
from platform_core.models.role import Role, RoleAssignment
from platform_core.models.user import User, UserStatus

logger = logging.getLogger(__name__)


async def resolve_capabilities(session: AsyncSession, user_id: UUID) -> frozenset[Capability]:
    """
    Read a user's effective capabilities from the database.

    Args:
        session: a tenant-scoped session. Row-level security means a user in
            another organisation is simply not visible, so this cannot resolve
            capabilities across a tenant boundary even if given a foreign ID.
        user_id: the user to resolve.

    Returns:
        frozenset[Capability]: every capability the user currently holds.
        Empty if the user is unknown, not Active, or holds no live assignments.
    """
    from datetime import UTC, datetime

    user = await session.get(User, user_id)
    if user is None:
        # Either the user does not exist, or they belong to another tenant and
        # RLS hid them. Both mean no capabilities, and deliberately produce the
        # same result — distinguishing them would confirm the existence of an
        # account in another organisation.
        return frozenset()

    if user.status != UserStatus.ACTIVE:
        logger.info(
            "Capability resolution refused for non-active user",
            extra={"user_status": user.status},
        )
        return frozenset()

    now = datetime.now(UTC)

    result = await session.execute(
        select(Role.capabilities)
        .join(RoleAssignment, RoleAssignment.role_id == Role.id)
        .where(RoleAssignment.user_id == user_id)
        .where(
            # Null expiry means indefinite; a future expiry is still live.
            (RoleAssignment.expires_at.is_(None)) | (RoleAssignment.expires_at > now)
        )
    )

    granted: set[Capability] = set()
    for (capability_names,) in result:
        for name in capability_names or []:
            try:
                granted.add(Capability(name))
            except ValueError:
                # A capability name in the database that no longer exists in
                # code — typically a rename that missed a data migration.
                # Ignored rather than raised: an unknown capability grants
                # nothing, which fails closed, and one stale row should not
                # lock a user out of everything else they hold.
                logger.warning(
                    "Unknown capability in role definition; ignoring",
                    extra={"capability_name": name},
                )

    return frozenset(granted)


async def build_principal(
    session: AsyncSession, user_id: UUID, organization_id: UUID
) -> Principal | None:
    """
    Load a user and resolve their capabilities into a Principal.

    Args:
        session: tenant-scoped session.
        user_id: the authenticated user.
        organization_id: the tenant, from the request context.

    Returns:
        Principal | None: the principal, or None if the user is not visible in
        this tenant or is not Active.
    """
    user = await session.get(User, user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        return None

    capabilities = await resolve_capabilities(session, user_id)
    return Principal(
        user_id=user_id,
        organization_id=organization_id,
        email=user.email,
        capabilities=capabilities,
    )


def require_capability(
    capability: Capability,
) -> Callable[[], Coroutine[Any, Any, Principal]]:
    """
    Build a FastAPI dependency enforcing one capability.

    Args:
        capability: the capability the endpoint requires.

    Returns:
        A dependency returning the Principal, or raising 403.

    Example:
        @router.post("/jobs")
        async def create_job(
            principal: Principal = Depends(require_capability(Capability.CREATE_JD)),
        ):
            ...

    The endpoint receives the Principal, so a handler needing further checks —
    a scoped permission, say — already has what it needs without another query.
    """

    async def dependency() -> Principal:
        principal = get_principal()

        if not principal.has(capability):
            # Logged with the capability but not with the full capability set:
            # enumerating what someone *does* hold in a log line accessible to
            # support staff is more disclosure than the diagnosis needs.
            logger.warning(
                "Authorisation denied",
                extra={
                    "required_capability": capability.value,
                    "user_id": str(principal.user_id),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "insufficient_capability",
                    "message": f"This action requires the {capability.value} capability.",
                },
            )

        return principal

    return dependency


def require_any_capability(
    *capabilities: Capability,
) -> Callable[[], Coroutine[Any, Any, Principal]]:
    """
    Build a dependency satisfied by any one of several capabilities.

    Used where the matrix grants an action to more than one role through
    different capabilities — approving an offer, for instance, which both HR and
    Admin may do.

    Args:
        *capabilities: the acceptable capabilities.

    Returns:
        A dependency returning the Principal, or raising 403.
    """

    async def dependency() -> Principal:
        principal = get_principal()

        if not principal.has_any(*capabilities):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "insufficient_capability",
                    "message": (
                        "This action requires one of: " + ", ".join(c.value for c in capabilities)
                    ),
                },
            )

        return principal

    return dependency
