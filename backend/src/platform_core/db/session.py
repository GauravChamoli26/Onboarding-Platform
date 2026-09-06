"""
Database engine and session handling — where tenant isolation is applied.

WHAT THIS MODULE DOES
    Creates the async engine and provides the session factories that every
    database access goes through. Critically, it sets the PostgreSQL session
    variable that row-level security policies read.

THE ONE THING TO UNDERSTAND HERE
    RLS policies compare `organization_id` against a PostgreSQL runtime setting
    called `app.current_organization_id`. That setting has to be applied to the
    connection before any query runs. This module is the only place that
    happens, which is what makes the boundary enforceable at a single layer
    rather than at hundreds of call sites (ADR-002).

THE POOLED-CONNECTION FOOTGUN
    Connections are reused across requests. If the tenant setting persisted
    beyond a request, the next request on that connection would inherit the
    previous tenant's identity — a cross-tenant leak, the worst failure this
    system has.

    The defence is `set_config(..., is_local => true)`, which scopes the setting
    to the current TRANSACTION. When the transaction commits or rolls back,
    PostgreSQL discards it. A connection returned to the pool carries nothing.
    This is why every session below opens a transaction before setting the
    tenant, and why we never use the non-local form of set_config.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from platform_core.config.settings import get_settings
from platform_core.tenancy.context import get_organization_or_none, is_system_mode

# The PostgreSQL runtime parameter name that RLS policies read. Must match the
# name used in the policy definitions in the migrations exactly — a typo here
# produces a policy that always evaluates to NULL, which returns zero rows.
# That fails safe, but silently, so the isolation test asserts both directions.
TENANT_SETTING = "app.current_organization_id"

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """
    Return the process-wide async engine, creating it on first use.

    One engine per process. It owns the connection pool, so creating more than
    one would multiply the connection count against the database.

    Returns:
        AsyncEngine: the shared engine.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            str(settings.database_url),
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            # Verify a connection is alive before handing it out. Guards against
            # connections killed by an RDS failover or an idle timeout.
            pool_pre_ping=True,
            # Recycle connections after an hour so long-lived pods do not hold
            # connections across a database restart.
            pool_recycle=3600,
            echo=False,  # SQL logging is handled by the observability layer
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    Return the process-wide session factory, creating it on first use.

    Returns:
        async_sessionmaker: factory producing AsyncSession instances.
    """
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            # Keep ORM objects usable after commit. Without this, accessing any
            # attribute post-commit triggers a lazy refresh — which in async
            # code raises rather than silently querying.
            expire_on_commit=False,
            autoflush=False,  # flush explicitly; implicit flushes hide ordering bugs
        )
    return _session_factory


async def _apply_tenant(session: AsyncSession, organization_id: UUID | None) -> None:
    """
    Apply the tenant to the current transaction so RLS policies can read it.

    Args:
        session: an AsyncSession with a transaction already open.
        organization_id: the tenant, or None to apply a NULL tenant.

    Implementation notes:

    1. We use `set_config()` rather than `SET LOCAL` because SET LOCAL does not
       accept bind parameters. Building it by string interpolation would be SQL
       injection against our own tenancy boundary — the last place to hand-roll
       a query string.

    2. The third argument (`is_local`) is TRUE. This scopes the setting to the
       transaction, so it is discarded on commit or rollback and cannot follow a
       pooled connection into the next request. See the module docstring.

    3. A None tenant sets the parameter to empty string. The policy casts it,
       yielding NULL, and `organization_id = NULL` is never true — so the query
       returns zero rows. Unset tenant means no data, never all data.
    """
    value = str(organization_id) if organization_id is not None else ""
    await session.execute(
        text(f"SELECT set_config('{TENANT_SETTING}', :org_id, true)"),
        {"org_id": value},
    )
    # The setting NAME is interpolated (it is a module constant, never user
    # input); the VALUE is bound. That distinction is the whole point.


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """
    Yield a tenant-scoped database session.

    This is the session every piece of application code should use. It reads the
    tenant from the async context (set by auth middleware or a job runner),
    applies it to the transaction, and commits on clean exit or rolls back on
    exception.

    If no tenant is in context, the session still works but every RLS-protected
    query returns zero rows. That is the intended failure mode.

    Yields:
        AsyncSession: a session scoped to the current tenant.

    Example:
        async with get_session() as session:
            result = await session.execute(select(FeatureFlag))
            # Only the current organisation's flags come back.
    """
    factory = get_session_factory()
    async with factory() as session:
        # begin() opens the transaction that set_config's local scope binds to.
        async with session.begin():
            await _apply_tenant(session, get_organization_or_none())
            yield session
            # session.begin() commits on clean exit, rolls back on exception.


@asynccontextmanager
async def get_system_session() -> AsyncIterator[AsyncSession]:
    """
    Yield a session that bypasses row-level security. Use almost never.

    ⚠️  THIS CROSSES THE TENANT BOUNDARY.

    Requires `system_context()` to be active, so that bypassing isolation is
    always an explicit, greppable decision at the call site rather than an
    accident of which session helper was imported.

    Legitimate uses are listed on `tenancy.context.system_context`. In practice
    the only one today is enumerating the organizations table before iterating
    tenants.

    Yields:
        AsyncSession: an unscoped session.

    Raises:
        RuntimeError: if called outside `system_context()`.
    """
    if not is_system_mode():
        raise RuntimeError(
            "get_system_session() requires an active system_context(). "
            "If you need cross-tenant access, make that explicit at the call "
            "site with a comment justifying it. If you are iterating "
            "organisations, use organization_context() per organisation instead."
        )

    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            # Deliberately does NOT call _apply_tenant. The connecting role has
            # BYPASSRLS off, so this only sees unprotected tables — which is
            # why organizations itself carries no RLS policy.
            yield session


async def dispose_engine() -> None:
    """
    Close all pooled connections. Call on application shutdown and in test
    teardown so the process can exit without dangling connections.
    """
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
