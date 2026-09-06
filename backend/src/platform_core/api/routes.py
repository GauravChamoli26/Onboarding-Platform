"""
Routes — health checks and a feature-flag endpoint that exercises tenancy.

WHY A FEATURE-FLAG ENDPOINT EXISTS AT PHASE 0
    It is the smallest real thing that proves the whole request path works:
    an HTTP request resolves a tenant, opens a scoped session, queries a
    tenant-scoped table, and gets back only that organisation's rows. Two curls
    with different organisation headers demonstrate the boundary end to end.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.api.dependencies import db_session, require_tenant
from platform_core.config.settings import get_settings
from platform_core.models.feature_flag import FeatureFlag

logger = logging.getLogger(__name__)

health_router = APIRouter(tags=["health"])
flags_router = APIRouter(prefix="/v1/feature-flags", tags=["feature-flags"])


# ===========================================================================
# Health
# ===========================================================================
# Two endpoints, because container orchestrators ask two different questions.
#
#   /health/live   Is the process alive? No dependency checks. A failure here
#                  means "restart the container".
#   /health/ready  Can it serve traffic? Checks the database. A failure means
#                  "stop routing requests here", but restarting would not help.
#
# Conflating them is a common and costly mistake: if liveness checked the
# database, a brief database blip would restart every container at once, turning
# a recoverable degradation into an outage.


class LivenessResponse(BaseModel):
    """Process is running."""

    status: str = Field(examples=["alive"])
    environment: str = Field(examples=["local"])


class ReadinessResponse(BaseModel):
    """Process can serve traffic."""

    status: str = Field(examples=["ready", "not_ready"])
    database: str = Field(examples=["connected", "unavailable"])


@health_router.get("/health/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    """
    Liveness probe. Deliberately checks nothing external.

    Returns:
        LivenessResponse: always 200 if the process can respond at all.
    """
    return LivenessResponse(status="alive", environment=get_settings().app_env)


@health_router.get("/health/ready", response_model=ReadinessResponse)
async def readiness(session: AsyncSession = Depends(db_session)) -> ReadinessResponse:
    """
    Readiness probe. Verifies the database is reachable.

    Note this runs with no tenant — the query is `SELECT 1`, which touches no
    RLS-protected table, so it works without an organisation in context.

    Returns:
        ReadinessResponse: database connectivity state.
    """
    from sqlalchemy import text

    try:
        await session.execute(text("SELECT 1"))
        return ReadinessResponse(status="ready", database="connected")
    except Exception:
        # Logged rather than raised: a readiness probe should report failure,
        # not return a 500 that an orchestrator may interpret differently.
        logger.exception("Readiness check failed")
        return ReadinessResponse(status="not_ready", database="unavailable")


# ===========================================================================
# Feature flags
# ===========================================================================


class FeatureFlagResponse(BaseModel):
    """A single flag's state."""

    flag_key: str
    enabled: bool

    model_config = {"from_attributes": True}  # populate directly from ORM objects


@flags_router.get(
    "",
    response_model=list[FeatureFlagResponse],
    status_code=status.HTTP_200_OK,
    summary="List feature flags for the current organisation",
)
async def list_feature_flags(
    organization_id: UUID = Depends(require_tenant),
    session: AsyncSession = Depends(db_session),
) -> list[FeatureFlag]:
    """
    Return every flag belonging to the current organisation.

    Note what is absent: there is no `WHERE organization_id = ...` clause. The
    row-level security policy applies it at the database, using the tenant this
    session set on its transaction. Adding a manual filter here would be
    harmless but misleading — it would suggest the application is what enforces
    isolation, when the whole point of ADR-002 is that it is not.

    Returns:
        list[FeatureFlag]: flags for the current tenant only.
    """
    result = await session.execute(select(FeatureFlag).order_by(FeatureFlag.flag_key))
    return list(result.scalars().all())
