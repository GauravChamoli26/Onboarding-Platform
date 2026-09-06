"""
ASGI middleware — correlation IDs and tenant resolution.

WHY PURE ASGI MIDDLEWARE AND NOT BaseHTTPMiddleware
    Starlette's BaseHTTPMiddleware runs the downstream application inside a
    separate anyio task. Context variables and task boundaries interact in ways
    that are easy to get subtly wrong, and the tenant context variable is the
    thing the entire security boundary depends on.

    Pure ASGI middleware calls the downstream app in the *same* coroutine
    context, so a contextvar set here is unambiguously visible to the route
    handler and to the database session it opens. For a mechanism this
    load-bearing, "unambiguous" is worth the extra fifteen lines.

ORDER MATTERS
    Correlation runs outermost, so every log line — including one written while
    tenant resolution fails — carries a request ID.
"""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from platform_core.db.types import uuid7
from platform_core.observability.context import correlation_scope
from platform_core.tenancy.context import request_tenant_scope

# ASGI type aliases. Spelled out rather than imported from starlette so the
# shape of the protocol is visible: an app is a callable taking a scope, a
# receive channel and a send channel.
Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

CORRELATION_HEADER = b"x-correlation-id"


class CorrelationIdMiddleware:
    """
    Attach a correlation ID to every request and echo it in the response.

    Every log line, domain event and audit entry produced while handling a
    request carries this ID, so one user-reported problem can be traced across
    the API, a queue worker and a vendor call (SDD §2.1, §6.6).

    An inbound `X-Correlation-Id` is honoured so that a caller — or a load
    balancer — can supply its own and have traces join up across systems.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Lifespan and websocket scopes pass straight through; only HTTP
        # requests carry headers we care about.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        incoming = headers.get(CORRELATION_HEADER)
        correlation_id = incoming.decode() if incoming else str(uuid4())

        # Stash on the scope so route handlers and error handlers can read it.
        scope["correlation_id"] = correlation_id

        async def send_with_correlation(message: dict[str, Any]) -> None:
            """Append the correlation header to the response start message."""
            if message["type"] == "http.response.start":
                # Headers on the message are a list of (name, value) byte pairs.
                message.setdefault("headers", [])
                message["headers"].append((CORRELATION_HEADER, correlation_id.encode()))
            await send(message)

        # Also publish the ID to the logging context, so every log line
        # written while handling this request carries it without any call site
        # having to pass it along.
        with correlation_scope(correlation_id):
            await self.app(scope, receive, send_with_correlation)


class TenantMiddleware:
    """
    Establish the tenant context for the request.

    ⚠️  Currently resolves the tenant from a development header via
    platform_core.auth.dev_stub. In Phase 1 this is replaced by reading the
    organisation from the authenticated principal, and the stub is deleted.

    WHAT HAPPENS WHEN NO TENANT RESOLVES
        Nothing is raised, and the context is set explicitly to None. Every
        RLS-protected query then returns zero rows. That asymmetry is
        deliberate and is what makes the boundary fail closed: a bug that loses
        the tenant produces an empty response, never another organisation's
        data.

        Note "set explicitly to None" rather than "left unset" — see
        request_tenant_scope for why the difference matters.

        Endpoints that genuinely require a tenant say so explicitly, via the
        `require_tenant` dependency in dependencies.py.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # ---- TEMPORARY: development tenant resolution ----------------------
        # Replace this block with principal-based resolution in Phase 1, and
        # delete platform_core/auth/dev_stub.py. Tracking:
        # PHASE1-AUTH-REMOVE-DEV-STUB
        from platform_core.auth.dev_stub import (
            resolve_organization_from_headers,
            resolve_user_from_headers,
        )

        headers = {key.decode().lower(): value.decode() for key, value in scope.get("headers", [])}
        organization_id = resolve_organization_from_headers(headers)
        user_id = resolve_user_from_headers(headers)
        # ---- END TEMPORARY -------------------------------------------------

        # Establish the tenant for this request and tear it down afterwards —
        # unconditionally, including when nothing resolved.
        #
        # Setting only on success would leave a previous request's tenant in
        # place for a request that has none, which is a cross-tenant leak
        # wherever requests share a context. `request_tenant_scope` accepts
        # None precisely so that "no tenant" is a state we set, not a state we
        # fall back into.
        if organization_id is not None:
            scope["organization_id"] = organization_id
        # The user is carried on the scope rather than resolved into a Principal
        # here, because building a Principal needs a database session and
        # middleware has none. The `authenticated_principal` dependency does it,
        # where a session is available. See api/dependencies.py.
        if user_id is not None:
            scope["user_id"] = user_id

        with request_tenant_scope(organization_id):
            # Because this is pure ASGI middleware, the downstream app runs in
            # the same context, so the value set above is visible to the route
            # handler and the session it opens.
            await self.app(scope, receive, send)


def new_request_id() -> str:
    """
    Generate a request identifier.

    UUIDv7 rather than v4 so that request IDs sort by time, which makes log
    scanning meaningfully easier during an incident.
    """
    return str(uuid7())
