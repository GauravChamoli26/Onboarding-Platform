"""
Request-path tenancy tests.

WHAT THIS PROVES
    That the isolation established at the database in Unit 1 survives the trip
    through HTTP: an inbound request resolves a tenant, opens a scoped session,
    and gets back only that organisation's rows.

    Unit 1 tested the boundary. This tests the wiring to it — which is where
    tenancy is usually lost, because the contextvar has to survive middleware,
    dependency injection and the async task the handler runs in.

WHY THE DEV STUB GUARDS ARE TESTED HERE
    The stub resolves tenants from a header, which is a real vulnerability
    scoped to local development. Its guards are the only thing keeping it there,
    so the guards get tested like any other security control.
"""

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from platform_core.auth.dev_stub import DEV_TENANT_HEADER
from platform_core.db.types import uuid7

pytestmark = pytest.mark.integration


async def _seed_flag(
    factory: async_sessionmaker[AsyncSession], org_id: UUID, key: str, enabled: bool
) -> None:
    """Insert one feature flag for an organisation, inside its tenant context."""
    async with factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_id)},
        )
        await session.execute(
            text("""
                INSERT INTO feature_flags (id, organization_id, flag_key, enabled)
                VALUES (:id, :org, :key, :enabled)
            """),
            {"id": uuid7(), "org": org_id, "key": key, "enabled": enabled},
        )


# ===========================================================================
# Health
# ===========================================================================


async def test_liveness_needs_no_tenant(api_client: AsyncClient) -> None:
    """
    Liveness responds without any tenant or database.

    A liveness probe that depended on either would restart healthy containers
    during a database blip, turning a degradation into an outage.
    """
    response = await api_client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


async def test_readiness_reports_database_connectivity(api_client: AsyncClient) -> None:
    """Readiness reaches the database and reports it, with no tenant set."""
    response = await api_client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "connected"}


# ===========================================================================
# Tenancy across the request path
# ===========================================================================


async def test_request_returns_only_own_organizations_flags(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Two requests, two organisations, two disjoint result sets.

    The end-to-end assertion for Unit 2: the tenant set by middleware reaches
    the database session opened by the dependency, and RLS filters on it.
    """
    org_a, org_b = two_organizations
    await _seed_flag(session_factory, org_a, "TalentPool", True)
    await _seed_flag(session_factory, org_b, "AICopilot", False)

    response_a = await api_client.get("/v1/feature-flags", headers={DEV_TENANT_HEADER: str(org_a)})
    assert response_a.status_code == 200
    assert [f["flag_key"] for f in response_a.json()] == ["TalentPool"]

    response_b = await api_client.get("/v1/feature-flags", headers={DEV_TENANT_HEADER: str(org_b)})
    assert response_b.status_code == 200
    assert [f["flag_key"] for f in response_b.json()] == ["AICopilot"]


async def test_request_without_tenant_header_is_rejected(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    No tenant header means 403, not an empty list.

    `require_tenant` makes the absence explicit. Returning `[]` would be
    indistinguishable from an organisation that genuinely has no flags, which
    hides bugs.
    """
    org_a, _ = two_organizations
    await _seed_flag(session_factory, org_a, "TalentPool", True)

    response = await api_client.get("/v1/feature-flags")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "no_organization_context"


async def test_unknown_organization_returns_empty_not_error(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    A well-formed but unknown organisation ID yields an empty list.

    This is the fail-closed property at the HTTP layer: an attacker guessing
    organisation IDs learns nothing, because a valid-but-foreign ID and an
    organisation with no data are indistinguishable in the response.
    """
    org_a, _ = two_organizations
    await _seed_flag(session_factory, org_a, "TalentPool", True)

    response = await api_client.get("/v1/feature-flags", headers={DEV_TENANT_HEADER: str(uuid4())})
    assert response.status_code == 200
    assert response.json() == []


async def test_malformed_tenant_header_does_not_leak(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    A malformed header is treated as no tenant, not as an error to probe.

    Rejected at the tenant check with 403 rather than 500 — a 500 would tell a
    caller their input reached something that broke, which is information.
    """
    org_a, _ = two_organizations
    await _seed_flag(session_factory, org_a, "TalentPool", True)

    response = await api_client.get("/v1/feature-flags", headers={DEV_TENANT_HEADER: "not-a-uuid"})
    assert response.status_code == 403


async def test_tenant_does_not_persist_between_requests(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    A tenant set on one request does not survive into the next.

    The HTTP-layer counterpart of the pooled-connection test in Unit 1. If the
    contextvar leaked between requests, the second call here would return A's
    flag instead of 403.
    """
    org_a, _ = two_organizations
    await _seed_flag(session_factory, org_a, "TalentPool", True)

    first = await api_client.get("/v1/feature-flags", headers={DEV_TENANT_HEADER: str(org_a)})
    assert first.status_code == 200
    assert len(first.json()) == 1

    second = await api_client.get("/v1/feature-flags")
    assert second.status_code == 403, "Tenant context leaked between requests"


# ===========================================================================
# Correlation and error handling
# ===========================================================================


async def test_every_response_carries_a_correlation_id(
    api_client: AsyncClient,
) -> None:
    """Every response carries a correlation ID for log tracing."""
    response = await api_client.get("/health/live")
    assert response.headers.get("x-correlation-id")


async def test_inbound_correlation_id_is_honoured(api_client: AsyncClient) -> None:
    """A caller-supplied correlation ID is preserved, so traces join up."""
    supplied = "trace-from-upstream-12345"
    response = await api_client.get("/health/live", headers={"X-Correlation-Id": supplied})
    assert response.headers["x-correlation-id"] == supplied


async def test_error_response_includes_correlation_id(
    api_client: AsyncClient,
) -> None:
    """
    Errors carry the correlation ID in the body, not just the header.

    Support asks the user for this; the user is reading the response body, not
    inspecting headers.
    """
    response = await api_client.get("/v1/feature-flags")
    assert response.status_code == 403
    body = response.json()
    assert body["error"]["correlation_id"]
    assert body["error"]["correlation_id"] == response.headers["x-correlation-id"]


# ===========================================================================
# Development auth stub guards
# ===========================================================================


async def test_dev_stub_refuses_non_local_environment(monkeypatch) -> None:
    """
    The stub raises when APP_ENV is not local.

    Guard 1 from dev_stub.py. This test is the reason all three guards exist:
    a comment can be ignored and a check can be commented out, but removing
    this makes the build go red.

    Delete this test in Phase 1 together with the stub itself.
    Tracking: PHASE1-AUTH-REMOVE-DEV-STUB
    """
    import platform_core.auth.dev_stub as dev_stub
    from platform_core.config.settings import get_settings

    # Settings are cached per process, so clear the cache before repointing
    # the environment variable.
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production")

    try:
        with pytest.raises(dev_stub.DevStubInProductionError) as exc_info:
            dev_stub.resolve_organization_from_headers({})
        # The message must tell the reader to delete the file, not to change
        # the check — otherwise the obvious "fix" is to weaken the guard.
        assert "delete" in str(exc_info.value).lower()
    finally:
        # Restore, or every later test in the session sees APP_ENV=production.
        monkeypatch.delenv("APP_ENV", raising=False)
        get_settings.cache_clear()
