"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  ⚠️  TEMPORARY DEVELOPMENT SCAFFOLDING — DELETE IN PHASE 1  ⚠️               ║
║                                                                              ║
║  This module resolves the tenant from an HTTP HEADER. That is precisely the  ║
║  vulnerability row-level security exists to prevent: taking the organisation ║
║  from user input rather than from an authenticated principal.                ║
║                                                                              ║
║  It exists only so the request path can be built and exercised before real   ║
║  SSO lands (Decision Log D-13, Option A).                                    ║
║                                                                              ║
║  REMOVAL, NOT DISABLING. When Phase 1 authentication is done, this file is   ║
║  deleted and the import in api/middleware.py is replaced. A flag left off is ║
║  a flag someone can turn on.                                                 ║
║                                                                              ║
║  Tracking: PHASE1-AUTH-REMOVE-DEV-STUB                                       ║
╚══════════════════════════════════════════════════════════════════════════════╝

THREE INDEPENDENT GUARDS
    1. Import-time  — importing this module outside APP_ENV=local raises.
    2. Startup-time — the app factory refuses to register it outside local.
    3. Test         — test_api_tenancy.py asserts guard 1 actually fires.

    Three because one is a comment someone can ignore, two is a check someone
    can comment out, and three means the build goes red.
"""

from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict

# The headers carrying tenant and user. Named to be conspicuous in logs and in
# any proxy configuration — nobody should mistake these for normal API headers.
DEV_TENANT_HEADER = "X-Dev-Organization-Id"
DEV_USER_HEADER = "X-Dev-User-Id"


class DevStubInProductionError(RuntimeError):
    """Raised when the development auth stub is loaded outside local."""


class _EnvironmentProbe(BaseSettings):
    """
    Reads APP_ENV alone, from the environment or .env.

    WHY NOT USE get_settings()
        The guard below needs exactly one field. Constructing the full Settings
        model would require DATABASE_URL and everything else to be present, so a
        process missing an unrelated setting fails on import with a validation
        error about the wrong field — instead of either loading cleanly or
        raising this module's own, explanatory error.

        That coupling broke CI: a runner has no .env, because .env holds
        credentials and is correctly gitignored, so importing this module
        failed on a missing database URL that the guard does not care about.

        A safety check must work in a partially configured process. That is
        precisely when you least want a header-based auth stub loading quietly.

    `extra="ignore"` so the other keys in .env do not cause a validation error
    here, and the default matches Settings so behaviour is identical when
    APP_ENV is absent.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "local"


def _assert_local_environment() -> None:
    """
    Refuse to operate outside APP_ENV=local.

    Raises:
        DevStubInProductionError: in any environment other than local.
    """
    app_env = _EnvironmentProbe().app_env
    if app_env != "local":
        raise DevStubInProductionError(
            f"The development authentication stub was loaded with "
            f"APP_ENV={app_env!r}. This module resolves the tenant "
            f"from a request header and must never run outside local "
            f"development. If Phase 1 authentication is complete, delete "
            f"platform_core/auth/dev_stub.py rather than changing this check."
        )


# GUARD 1 — import time.
# Placed at module level so the failure happens when the module is first
# imported, not when a request arrives. An application that would resolve
# tenants from headers should fail to start, not fail on the first request.
_assert_local_environment()


def resolve_organization_from_headers(headers: dict[str, str]) -> UUID | None:
    """
    Extract the tenant from the development header.

    Args:
        headers: request headers, lowercased keys.

    Returns:
        UUID | None: the organisation ID, or None if the header is absent or
        malformed. None means no tenant, which under RLS yields zero rows —
        the correct failure mode. A malformed value is deliberately treated the
        same as a missing one rather than raising, so that a typo produces an
        empty result rather than a 500.
    """
    _assert_local_environment()  # re-checked per call, cheap and unambiguous

    raw = headers.get(DEV_TENANT_HEADER.lower())
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


def resolve_user_from_headers(headers: dict[str, str]) -> UUID | None:
    """
    Extract the acting user from the development header.

    In Phase 1 proper this comes from the SSO assertion. Here it is a header,
    which is why this whole module is temporary.

    Args:
        headers: request headers, lowercased keys.

    Returns:
        UUID | None: the user ID, or None if absent or malformed. None means
        unauthenticated, and any endpoint requiring a capability will reject the
        request — a malformed value must not be treated as more privileged than
        no value at all.
    """
    _assert_local_environment()

    raw = headers.get(DEV_USER_HEADER.lower())
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None
