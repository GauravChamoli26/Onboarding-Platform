"""
Tenant context — which organisation the current unit of work belongs to.

WHAT THIS MODULE DOES
    Holds the current organisation ID for the duration of a request or a
    background job, so that the database session layer can apply it to every
    connection without every call site having to pass it around.

WHY A CONTEXTVAR AND NOT A GLOBAL
    The application is async. Many requests are in flight on one thread at the
    same time, so a module-level global would leak one tenant's identity into
    another's request. `contextvars.ContextVar` is the async-safe equivalent:
    each task gets its own value, and values propagate into tasks spawned from
    the current one.

WHY THIS IS NOT THE SECURITY BOUNDARY
    This module only records intent. The boundary itself is a PostgreSQL
    row-level security policy (ADR-002). If this context is wrong, RLS shows the
    wrong tenant's data; if this context is *unset*, RLS shows nothing at all.
    That asymmetry is deliberate — the failure mode is an empty result, never a
    leak.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

# ---------------------------------------------------------------------------
# The context variable itself
# ---------------------------------------------------------------------------
# Default is None, meaning "no tenant established". Any database read in that
# state returns zero rows, because the RLS policy compares against NULL.
_current_organization_id: ContextVar[UUID | None] = ContextVar(
    "current_organization_id", default=None
)

# Set to True only inside `system_context()`. See the warning on that function.
_system_mode: ContextVar[bool] = ContextVar("system_mode", default=False)


class TenantContextError(RuntimeError):
    """Raised when a tenant-scoped operation is attempted with no tenant set."""


def set_organization(organization_id: UUID) -> None:
    """
    Establish the tenant for the current async context.

    Called by the authentication middleware once per request, after the
    principal has been identified — never from a request parameter. Taking the
    organisation from user input is exactly the vulnerability RLS exists to
    prevent (ADR-002, and threat #1 in SDD §1.4).

    Args:
        organization_id: the organisation the caller belongs to.
    """
    _current_organization_id.set(organization_id)


def get_organization() -> UUID:
    """
    Return the current tenant, raising if none is set.

    Use this where a tenant is required and its absence is a programming error.

    Returns:
        UUID: the current organisation ID.

    Raises:
        TenantContextError: if no tenant has been established.
    """
    org_id = _current_organization_id.get()
    if org_id is None:
        raise TenantContextError(
            "No organisation in context. Tenant-scoped work requires "
            "set_organization() to have been called — normally by auth "
            "middleware or a job runner."
        )
    return org_id


def get_organization_or_none() -> UUID | None:
    """
    Return the current tenant, or None if unset.

    Use this in the session layer, which must handle the unset case by applying
    a NULL tenant (yielding zero rows) rather than raising.
    """
    return _current_organization_id.get()


def is_system_mode() -> bool:
    """True when running inside `system_context()`. Checked by the session layer."""
    return _system_mode.get()


@contextmanager
def organization_context(organization_id: UUID) -> Iterator[None]:
    """
    Temporarily run as a specific organisation, restoring the previous one after.

    The main use is background jobs that iterate over organisations — the
    retention job, SLA sweeps, notification batches. Each organisation is
    processed inside its own context, so RLS scopes every query correctly
    without the job needing to filter manually.

    Args:
        organization_id: the organisation to run as.

    Example:
        for org_id in all_organization_ids:
            with organization_context(org_id):
                await run_retention_sweep()
    """
    token = _current_organization_id.set(organization_id)
    try:
        yield
    finally:
        # Reset rather than set-to-None, so nested contexts restore correctly.
        _current_organization_id.reset(token)


@contextmanager
def request_tenant_scope(organization_id: UUID | None) -> Iterator[None]:
    """
    Establish the tenant for exactly one request, then tear it down.

    Differs from `organization_context()` in two ways that matter:

    1. It accepts None. A request with no resolvable tenant gets an explicit
       "no tenant" state rather than inheriting whatever was set previously.
    2. It always resets on exit, including when the handler raises.

    WHY THIS IS NOT OPTIONAL
        Setting the context without resetting it relies on each request running
        in its own task, so that context variables are isolated by the task
        boundary. That holds under uvicorn today. It does not hold when the app
        is called directly in a shared context — an in-process test client, an
        embedded invocation, or any middleware that runs the downstream app in
        the caller's context.

        The failure mode when that assumption breaks is one request inheriting
        another's tenant, which is a cross-tenant leak and would be silent.
        Depending on task isolation for the security boundary is not worth the
        three lines it saves, so the boundary is made explicit here.

    Args:
        organization_id: the tenant for this request, or None if none resolved.

    Example:
        with request_tenant_scope(org_id):
            await self.app(scope, receive, send)
    """
    token = _current_organization_id.set(organization_id)
    try:
        yield
    finally:
        # reset() restores the value that was in place before set() was called,
        # which correctly unwinds nesting rather than blanking the variable.
        _current_organization_id.reset(token)


@contextmanager
def system_context() -> Iterator[None]:
    """
    Run with row-level security bypassed. Use almost never.

    ⚠️  THIS DISABLES THE TENANT BOUNDARY.

    There are exactly three legitimate uses:
        1. Alembic migrations (run as the owning role anyway).
        2. Reading the organizations table itself, to discover which tenants
           exist before iterating them.
        3. Cross-tenant platform administration — currently nothing.

    It is NOT for convenience, NOT for "just this one query", and NOT for
    background jobs, which should iterate organisations with
    `organization_context()` instead.

    Every use of this function should be greppable, reviewed, and justified in
    a comment at the call site. If this appears in a pull request without one,
    that is a blocking review comment.
    """
    token = _system_mode.set(True)
    try:
        yield
    finally:
        _system_mode.reset(token)
