"""
FastAPI dependencies — the wiring between a request and the data layer.

WHAT LIVES HERE
    `db_session`      yields a tenant-scoped database session
    `require_tenant`  asserts a tenant is present, for endpoints that need one

WHY require_tenant IS SEPARATE FROM db_session
    Not every endpoint needs a tenant — health checks do not. And an endpoint
    that *does* need one should say so explicitly rather than discovering the
    absence as an empty result set, which is indistinguishable from "this
    organisation genuinely has no data".

    So: the boundary always fails closed at the database, and endpoints opt in
    to failing loudly at the edge.
"""

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.auth.authorization import build_principal
from platform_core.auth.principal import NoPrincipalError, Principal, principal_scope
from platform_core.db.session import get_session
from platform_core.tenancy.context import get_organization


async def db_session() -> AsyncIterator[AsyncSession]:
    """
    Yield a database session scoped to the current request's tenant.

    The session opens a transaction, applies the tenant from context, and
    commits on clean exit or rolls back on exception. Route handlers never
    manage transactions themselves.

    Yields:
        AsyncSession: a tenant-scoped session.

    Example:
        @router.get("/things")
        async def list_things(session: AsyncSession = Depends(db_session)):
            result = await session.execute(select(Thing))
            return result.scalars().all()
    """
    async with get_session() as session:
        yield session


async def require_tenant() -> UUID:
    """
    Return the current tenant, rejecting the request if none is established.

    Add to any endpoint whose response would be meaningless without an
    organisation.

    Returns:
        UUID: the current organisation ID.

    Raises:
        TenantContextError: handled in errors.py, becomes a 403.

    Example:
        @router.get("/flags")
        async def list_flags(org_id: UUID = Depends(require_tenant)):
            ...
    """
    return get_organization()


async def authenticated_principal(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> AsyncIterator[Principal]:
    """
    Resolve the acting user into a Principal, with capabilities loaded.

    WHY THIS IS A DEPENDENCY AND NOT MIDDLEWARE
        Building a Principal requires reading role assignments, which requires a
        database session. Middleware runs before dependency injection and has no
        session — opening one there would mean managing a second transaction
        outside the one the request already uses.

        So middleware carries the user ID on the request scope, and this
        dependency turns it into a Principal at the point a session exists.

    The Principal is published to the context variable for the duration of the
    request, so that code far from the endpoint — audit writers, event emitters
    — can record who acted without it being threaded through every call.

    Yields:
        Principal: the authenticated actor with resolved capabilities.

    Raises:
        NoPrincipalError: if no user is authenticated, or the user is not Active
            or not visible in this tenant. Returned as 401 by errors.py.
    """
    user_id: UUID | None = request.scope.get("user_id")
    if user_id is None:
        raise NoPrincipalError("This request carries no authenticated user.")

    organization_id = get_organization()
    principal = await build_principal(session, user_id, organization_id)

    if principal is None:
        # The user does not exist in this tenant, or is suspended or offboarded.
        # Deliberately one message for all three: distinguishing them would
        # confirm whether an account exists in another organisation.
        raise NoPrincipalError("The authenticated user cannot act in this organisation.")

    with principal_scope(principal):
        yield principal
