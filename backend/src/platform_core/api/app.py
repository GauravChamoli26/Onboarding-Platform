"""
Application factory.

WHAT THIS MODULE DOES
    Builds and configures the FastAPI application: lifespan management,
    middleware stack, error handlers and routes.

WHY A FACTORY RATHER THAN A MODULE-LEVEL APP
    Tests need to build an application with different settings without
    re-importing modules. A factory makes that trivial; a module-level
    singleton makes it awkward.

    A module-level `app` is still exported at the bottom, because uvicorn needs
    something to point at.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from platform_core.api.errors import register_error_handlers
from platform_core.api.middleware import CorrelationIdMiddleware, TenantMiddleware
from platform_core.api.routes import flags_router, health_router
from platform_core.config.settings import get_settings
from platform_core.db.session import dispose_engine, get_engine
from platform_core.observability import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Startup and shutdown.

    Startup creates the database engine eagerly rather than lazily on first
    request, so a bad DATABASE_URL surfaces when the container starts and fails
    its health check — not as a confusing 500 for whoever happens to send the
    first request.

    Shutdown disposes the connection pool so the process exits cleanly instead
    of leaving connections for the database to time out.
    """
    settings = get_settings()

    # Configure logging first, so that everything after this — including a
    # failure to construct the engine — is captured in the right format and
    # passes through the redaction filter.
    configure_logging(level=settings.log_level, json_format=settings.log_json)

    logger.info(
        "Starting application",
        extra={"environment": settings.app_env, "region": settings.aws_region},
    )

    get_engine()  # construct now; fail now if misconfigured

    yield

    logger.info("Shutting down")
    await dispose_engine()


def create_app() -> FastAPI:
    """
    Build a configured FastAPI application.

    Returns:
        FastAPI: the application, ready to serve.

    Raises:
        RuntimeError: if the development auth stub would be loaded outside
            APP_ENV=local. See guard 2 below.
    """
    settings = get_settings()

    app = FastAPI(
        title="Employee Onboarding & Recruitment Platform",
        version="0.1.0",
        # Interactive docs are development-only. In production they hand an
        # attacker a complete map of the API surface for free.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )

    # ---- GUARD 2: startup-time check on the development auth stub ----------
    # dev_stub.py raises on import (guard 1). This is the second, independent
    # check: even if someone removed the import-time guard, the application
    # still refuses to wire header-based tenant resolution outside local.
    #
    # Delete this block together with dev_stub.py in Phase 1.
    # Tracking: PHASE1-AUTH-REMOVE-DEV-STUB
    if settings.app_env != "local":
        raise RuntimeError(
            f"TenantMiddleware currently resolves the tenant from a request "
            f"header via the development auth stub, and APP_ENV is "
            f"{settings.app_env!r}. Complete Phase 1 authentication and delete "
            f"platform_core/auth/dev_stub.py before running outside local."
        )
    logger.warning(
        "DEVELOPMENT AUTH STUB ACTIVE — tenant resolved from the "
        "X-Dev-Organization-Id header. Never run this outside local."
    )
    # ---- END TEMPORARY -----------------------------------------------------

    # ---- Middleware --------------------------------------------------------
    # Order is significant. ASGI middleware wraps outward-in: the LAST one added
    # is the OUTERMOST, so it sees the request first.
    #
    # We want correlation outermost, so that a request ID exists even when
    # tenant resolution itself fails and needs logging. Therefore tenant is
    # added first, correlation second.
    app.add_middleware(TenantMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    register_error_handlers(app)

    app.include_router(health_router)
    app.include_router(flags_router)

    return app


# Module-level instance for uvicorn:
#   uvicorn platform_core.api.app:app --reload
app = create_app()
