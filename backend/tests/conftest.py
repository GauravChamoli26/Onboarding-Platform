"""
Shared test fixtures.

WHY testcontainers RATHER THAN A MOCK OR SQLITE
    ADR-002 makes PostgreSQL row-level security the tenant boundary. RLS does
    not exist in SQLite and cannot be mocked meaningfully — a mock would assert
    that our code calls set_config, not that the database then hides other
    tenants' rows. Only a real PostgreSQL proves the boundary holds.

    Each test session starts a container, creates the schema, and creates the
    non-superuser application role. That is the same shape as production, which
    is the point: a test running as superuser would bypass every policy and
    pass for the wrong reason.

ON EVENT LOOP SCOPE
    pytest-asyncio 1.0 removed the old pattern of redefining an `event_loop`
    fixture. The replacement is `loop_scope`, set per fixture and configured
    globally in pyproject.toml. The whole suite shares one session-scoped loop,
    which is correct here: every test talks to the same container, so there is
    nothing to isolate between loops and a shared loop avoids cross-loop errors
    when a session-scoped resource is used by a function-scoped test.
"""

import os
from collections.abc import AsyncIterator, Iterator
from urllib.parse import urlparse, urlunparse
from uuid import UUID

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# testcontainers 4.x moved community modules; fall back for older installs.
try:
    from testcontainers.community.postgres import PostgresContainer
except ImportError:  # pragma: no cover - depends on installed version
    from testcontainers.postgres import PostgresContainer

from platform_core.db.types import uuid7

# ===========================================================================
# Test environment, established at import time
# ===========================================================================
# pytest imports conftest.py BEFORE collecting any test module, which makes
# this the only place these can be set in time.
#
# WHY THIS IS NECESSARY
#     Importing certain application modules triggers configuration loading.
#     `platform_core.auth.dev_stub` runs its environment guard at import — by
#     design, so that a header-based auth stub can never be loaded in a
#     deployed environment — and that guard calls get_settings(), which
#     validates the entire Settings model including DATABASE_URL.
#
#     Locally that succeeds because .env exists. On a CI runner it does not:
#     .env holds credentials and is correctly gitignored. Collection then fails
#     before a single test runs, which is what broke the first CI build.
#
# WHY setdefault RATHER THAN ASSIGNMENT
#     A developer who has already exported these keeps their values. This only
#     fills the gap.
#
# WHY A PLACEHOLDER URL IS SAFE
#     Nothing connects to a database at import time; the value only has to be
#     present and well-formed for Settings to validate. The autouse
#     `configure_application_settings` fixture replaces it with the real
#     container URL before any test executes.
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
)


# Credentials for the deliberately unprivileged application role. Mirrors
# scripts/init-db.sql — see that file for why this separation matters.
APP_USER = "app_user"
APP_PASSWORD = "app_password"

# Every tenant-scoped table. Must stay in step with the migrations — the
# migration parity tests in test_migrations.py assert that it does.
TENANT_SCOPED_TABLES = (
    "feature_flags",
    "roles",
    "identity_provider_configs",
    "users",
    "role_assignments",
    "outbox_events",
    "processed_events",
    "audit_entries",
    "sla_policies",
    "holidays",
    "approval_delegations",
    "approval_requests",
    "approval_actions",
)


def _swap_credentials(url: str, username: str, password: str) -> str:
    """
    Return `url` with its username and password replaced.

    Built by parsing rather than string replacement so it does not depend on
    what credentials testcontainers happens to generate, which vary by version.

    Args:
        url: a full database URL.
        username: the username to substitute.
        password: the password to substitute.

    Returns:
        str: the URL with new credentials, everything else unchanged.
    """
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{username}:{password}@{host}{port}"
    return urlunparse(parsed._replace(netloc=netloc))


@pytest_asyncio.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    """
    Start a PostgreSQL 16 container for the test session.

    Same major version as production. `driver="asyncpg"` makes
    get_connection_url() return an asyncpg URL directly, rather than us
    rewriting a psycopg2 one and hoping the prefix matches.

    Started once and reused, since container startup dominates the suite's
    runtime.
    """
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as container:
        yield container


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def setup_database(postgres_container: PostgresContainer) -> AsyncIterator[str]:
    """
    Create the application role and schema, and yield its connection URL.

    Creates the schema directly rather than invoking Alembic, so the test suite
    has no dependency on Alembic's configuration loading. The SQL below must
    stay in step with migration 0001.

    Yields:
        str: an asyncpg connection URL authenticated as the unprivileged
             application role — NOT the superuser that created the schema.
    """
    admin_url = postgres_container.get_connection_url()

    # AUTOCOMMIT because CREATE ROLE cannot run inside a transaction block.
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")

    async with admin_engine.connect() as conn:
        # --- Application role (mirrors scripts/init-db.sql) ------------------
        await conn.execute(text(f"CREATE ROLE {APP_USER} WITH LOGIN PASSWORD '{APP_PASSWORD}'"))
        await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {APP_USER}"))

        # --- Schema (mirrors migration 0001) ---------------------------------
        await conn.execute(
            text("""
            CREATE TABLE organizations (
                id UUID PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                legal_entity_name VARCHAR(255),
                timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Kolkata',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        )
        await conn.execute(
            text("""
            CREATE TABLE feature_flags (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL
                    REFERENCES organizations(id) ON DELETE RESTRICT,
                flag_key VARCHAR(64) NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT false,
                changed_by UUID,
                change_reason TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_feature_flags_organization_id
                    UNIQUE (organization_id, flag_key)
            )
        """)
        )

        # --- Identity and access (mirrors migration 0002) --------------------
        await conn.execute(
            text("""
            CREATE TABLE roles (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL
                    REFERENCES organizations(id) ON DELETE RESTRICT,
                role_key VARCHAR(64) NOT NULL,
                capabilities VARCHAR(64)[] NOT NULL DEFAULT '{}',
                description VARCHAR(255),
                is_system BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_roles_organization_id UNIQUE (organization_id, role_key)
            )
        """)
        )
        await conn.execute(
            text("""
            CREATE TABLE identity_provider_configs (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL
                    REFERENCES organizations(id) ON DELETE RESTRICT,
                protocol VARCHAR(16) NOT NULL,
                display_name VARCHAR(255) NOT NULL,
                metadata_url TEXT,
                client_id VARCHAR(255),
                client_secret_ref VARCHAR(255),
                certificate_ref VARCHAR(255),
                attribute_mapping JSONB NOT NULL DEFAULT '{}',
                jit_provisioning_enabled BOOLEAN NOT NULL DEFAULT false,
                default_role_id UUID REFERENCES roles(id) ON DELETE SET NULL,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        )
        await conn.execute(
            text("""
            CREATE TABLE users (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL
                    REFERENCES organizations(id) ON DELETE RESTRICT,
                email VARCHAR(320) NOT NULL,
                full_name VARCHAR(255) NOT NULL,
                employee_code VARCHAR(64),
                status VARCHAR(32) NOT NULL DEFAULT 'Active',
                external_idp_subject VARCHAR(255),
                idp_config_id UUID
                    REFERENCES identity_provider_configs(id) ON DELETE SET NULL,
                last_login_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_users_organization_id UNIQUE (organization_id, email),
                CONSTRAINT ck_users_status
                    CHECK (status IN ('Active', 'Suspended', 'Offboarded'))
            )
        """)
        )
        await conn.execute(
            text("""
            CREATE TABLE role_assignments (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL
                    REFERENCES organizations(id) ON DELETE RESTRICT,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role_id UUID NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
                scope_type VARCHAR(32) NOT NULL DEFAULT 'Organization',
                scope_id UUID,
                granted_by UUID REFERENCES users(id) ON DELETE SET NULL,
                granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                expires_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ck_role_assignments_scope_type
                    CHECK (scope_type IN ('Organization', 'Department', 'JobPosting')),
                CONSTRAINT ck_role_assignments_scope_consistency
                    CHECK ((scope_type = 'Organization' AND scope_id IS NULL)
                        OR (scope_type <> 'Organization' AND scope_id IS NOT NULL))
            )
        """)
        )

        # --- Event infrastructure (mirrors migration 0003) -------------------
        await conn.execute(
            text("""
            CREATE TABLE outbox_events (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL
                    REFERENCES organizations(id) ON DELETE RESTRICT,
                event_type VARCHAR(64) NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                entity_type VARCHAR(64) NOT NULL,
                entity_id UUID NOT NULL,
                application_id UUID,
                candidate_profile_id UUID,
                actor_type VARCHAR(16) NOT NULL,
                actor_id UUID,
                correlation_id VARCHAR(64) NOT NULL,
                causation_id UUID,
                sequence_number BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
                payload JSONB NOT NULL DEFAULT '{}',
                contains_pii BOOLEAN NOT NULL DEFAULT false,
                emitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                status VARCHAR(16) NOT NULL DEFAULT 'Pending',
                published_at TIMESTAMPTZ,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ck_outbox_events_status
                    CHECK (status IN ('Pending', 'Published', 'Failed'))
            )
        """)
        )
        await conn.execute(
            text("""
            CREATE TABLE processed_events (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL
                    REFERENCES organizations(id) ON DELETE RESTRICT,
                consumer_name VARCHAR(64) NOT NULL,
                event_id UUID NOT NULL,
                event_type VARCHAR(64) NOT NULL,
                processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_processed_events_consumer_name
                    UNIQUE (consumer_name, event_id)
            )
        """)
        )

        # --- Approval engine (mirrors migration 0005) ------------------------
        # Order matters: approval_requests references both approval_delegations
        # and sla_policies.
        await conn.execute(
            text("""
            CREATE TABLE sla_policies (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL
                    REFERENCES organizations(id) ON DELETE RESTRICT,
                sla_type VARCHAR(32) NOT NULL,
                duration_business_days INTEGER NOT NULL,
                reminder_offsets INTEGER[] NOT NULL DEFAULT '{}',
                escalation_target VARCHAR(32) NOT NULL DEFAULT 'HRQueue',
                escalation_target_user_id VARCHAR(64),
                escalation_after_misses INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_sla_policies_organization_id
                    UNIQUE (organization_id, sla_type),
                CONSTRAINT ck_sla_policies_duration_business_days
                    CHECK (duration_business_days >= 0)
            )
        """)
        )
        await conn.execute(
            text("""
            CREATE TABLE holidays (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL
                    REFERENCES organizations(id) ON DELETE RESTRICT,
                holiday_date DATE NOT NULL,
                name VARCHAR(128) NOT NULL,
                region VARCHAR(64),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_holidays_organization_id
                    UNIQUE (organization_id, holiday_date, region)
            )
        """)
        )
        await conn.execute(
            text("""
            CREATE TABLE approval_delegations (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL
                    REFERENCES organizations(id) ON DELETE RESTRICT,
                delegator_user_id UUID NOT NULL
                    REFERENCES users(id) ON DELETE CASCADE,
                delegate_user_id UUID NOT NULL
                    REFERENCES users(id) ON DELETE CASCADE,
                capability VARCHAR(64) NOT NULL,
                valid_from DATE NOT NULL,
                valid_to DATE NOT NULL,
                reason TEXT,
                revoked_at TIMESTAMPTZ,
                revoked_by UUID REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ck_approval_delegations_valid_range
                    CHECK (valid_to >= valid_from),
                CONSTRAINT ck_approval_delegations_not_self
                    CHECK (delegator_user_id <> delegate_user_id)
            )
        """)
        )
        await conn.execute(
            text("""
            CREATE TABLE approval_requests (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL
                    REFERENCES organizations(id) ON DELETE RESTRICT,
                approval_type VARCHAR(32) NOT NULL,
                entity_type VARCHAR(64) NOT NULL,
                entity_id UUID NOT NULL,
                application_id UUID,
                required_capability VARCHAR(64) NOT NULL,
                assigned_to_user_id UUID NOT NULL
                    REFERENCES users(id) ON DELETE RESTRICT,
                resolved_via_delegation_id UUID
                    REFERENCES approval_delegations(id) ON DELETE SET NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'Pending',
                sla_policy_id UUID REFERENCES sla_policies(id) ON DELETE SET NULL,
                due_at TIMESTAMPTZ,
                escalated_at TIMESTAMPTZ,
                escalated_to_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
                reminder_count INTEGER NOT NULL DEFAULT 0,
                context_snapshot JSONB NOT NULL DEFAULT '{}',
                requested_by UUID REFERENCES users(id) ON DELETE SET NULL,
                requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                resolved_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ck_approval_requests_status
                    CHECK (status IN ('Pending', 'Approved', 'Rejected',
                                      'Escalated', 'Withdrawn', 'Expired'))
            )
        """)
        )
        await conn.execute(
            text("""
            CREATE TABLE approval_actions (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL
                    REFERENCES organizations(id) ON DELETE RESTRICT,
                approval_request_id UUID NOT NULL
                    REFERENCES approval_requests(id) ON DELETE CASCADE,
                action VARCHAR(16) NOT NULL,
                actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
                comment TEXT,
                acted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        )

        # --- Audit log (mirrors migration 0004) ------------------------------
        await conn.execute(
            text("""
            CREATE TABLE audit_entries (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL
                    REFERENCES organizations(id) ON DELETE RESTRICT,
                chain_position BIGINT NOT NULL,
                previous_hash VARCHAR(64) NOT NULL,
                entry_hash VARCHAR(64) NOT NULL,
                actor_type VARCHAR(16) NOT NULL,
                actor_id UUID,
                actor_role VARCHAR(64),
                action_type VARCHAR(64) NOT NULL,
                entity_type VARCHAR(64) NOT NULL,
                entity_id UUID NOT NULL,
                before_state JSONB,
                after_state JSONB,
                correlation_id VARCHAR(64) NOT NULL,
                event_id UUID,
                ip_address INET,
                session_id VARCHAR(64),
                occurred_at TIMESTAMPTZ NOT NULL,
                notes TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_audit_entries_organization_id
                    UNIQUE (organization_id, chain_position)
            )
        """)
        )

        # Immutability layer 2: the trigger. Refuses UPDATE and DELETE from
        # anyone, including the table owner.
        await conn.execute(
            text("""
            CREATE OR REPLACE FUNCTION audit_entries_immutable()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION
                    'audit_entries is append-only; % is not permitted (ADR-016)',
                    TG_OP;
            END;
            $$ LANGUAGE plpgsql;
        """)
        )
        await conn.execute(
            text("""
            CREATE TRIGGER trg_audit_entries_immutable
                BEFORE UPDATE OR DELETE ON audit_entries
                FOR EACH ROW
                EXECUTE FUNCTION audit_entries_immutable();
        """)
        )

        # --- The three-step RLS pattern --------------------------------------
        # 1. ENABLE turns policies on.
        # 2. FORCE applies them to the table owner too — the step people miss,
        #    and missing it is invisible without the test that checks for it.
        # 3. The policy itself.
        # Applied to every tenant-scoped table. Keeping this as a loop means a
        # new table cannot be added to the schema above without a deliberate
        # decision about whether it belongs in this list.
        for table in TENANT_SCOPED_TABLES:
            await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            await conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
            await conn.execute(
                text(f"""
                CREATE POLICY tenant_isolation ON {table}
                    USING (organization_id
                           = NULLIF(current_setting('app.current_organization_id', true), '')::uuid)
                    WITH CHECK (organization_id
                           = NULLIF(current_setting('app.current_organization_id', true), '')::uuid)
            """)
            )

        await conn.execute(
            text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_USER}"
            )
        )
        # Immutability layer 1: take back UPDATE and DELETE on the audit table.
        # Must come after the blanket grant above, exactly as migration 0004
        # comes after init-db.sql's ALTER DEFAULT PRIVILEGES.
        await conn.execute(text(f"REVOKE UPDATE, DELETE ON audit_entries FROM {APP_USER}"))

    await admin_engine.dispose()

    yield _swap_credentials(admin_url, APP_USER, APP_PASSWORD)


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def configure_application_settings(setup_database: str) -> AsyncIterator[None]:
    """
    Point the application's own engine at the test database, for the session.

    WHY THIS IS AUTOUSE AND SESSION-SCOPED
        Most tests reach the database through the `session_factory` fixture,
        which is built explicitly from the container URL. But anything calling
        production code that opens its own session — the outbox relay, the audit
        verification job, any future background worker — goes through
        `platform_core.db.session.get_session()`, which reads DATABASE_URL from
        settings.

        Without this fixture those tests only pass if some earlier test happened
        to set DATABASE_URL as a side effect. That is test-order coupling: it
        works until a new test file changes the collection order, and then fails
        somewhere unrelated to the change.

        Setting it once, up front, autouse, removes the coupling entirely.

    The engine is disposed at session end rather than per test, because tests
    sharing it must not have it torn down underneath them.
    """
    from platform_core.config.settings import get_settings
    from platform_core.db.session import dispose_engine

    os.environ["DATABASE_URL"] = setup_database
    # Required for the development auth stub to load at all — see its guards.
    os.environ["APP_ENV"] = "local"
    get_settings.cache_clear()

    yield

    await dispose_engine()
    get_settings.cache_clear()


@pytest_asyncio.fixture(loop_scope="session")
async def session_factory(
    setup_database: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """
    Yield a session factory bound to the unprivileged application role.

    A fresh engine per test keeps connection state from leaking between tests —
    which matters here, because "does tenant state leak between uses of a
    connection" is one of the things under test.
    """
    engine = create_async_engine(setup_database)
    yield async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def two_organizations(
    setup_database: str, postgres_container
) -> AsyncIterator[tuple[UUID, UUID]]:
    """
    Create two organisations and yield their IDs.

    The core fixture of the isolation suite. Every integration test runs with at
    least two tenants present, because a single-tenant test cannot detect a
    missing boundary — everything looks correct when there is nothing to leak
    from.

    Yields:
        tuple[UUID, UUID]: IDs of organisation A and organisation B.
    """
    # Superuser connection rather than the application role. Teardown has to
    # disable the audit immutability trigger, which the application role cannot
    # do — and should not be able to. Row-level security still applies to the
    # owner because every tenant table is FORCE'd, so the per-tenant deletes
    # below still set a tenant.
    engine = create_async_engine(
        postgres_container.get_connection_url(), isolation_level="AUTOCOMMIT"
    )
    org_a, org_b = uuid7(), uuid7()

    async with engine.connect() as conn:
        for org_id, name in ((org_a, "Org A"), (org_b, "Org B")):
            await conn.execute(
                text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
                {"id": org_id, "name": name},
            )

    yield org_a, org_b

    # Clean up so rows do not accumulate across the session. Order matters:
    # feature_flags references organizations with ON DELETE RESTRICT.
    #
    # Runs on the superuser connection because audit_entries teardown must
    # disable a trigger, which the application role cannot do — and should not
    # be able to.
    #
    # Deleting feature_flags requires bypassing RLS, which the app role cannot
    # do — so this runs with a tenant set for each organisation in turn.
    async with engine.connect() as conn:
        for org_id in (org_a, org_b):
            await conn.execute(
                text("SELECT set_config('app.current_organization_id', :v, false)"),
                {"v": str(org_id)},
            )
            # Reverse dependency order: assignments reference users and roles.
            # audit_entries is append-only and cannot be DELETEd, so the
            # trigger is disabled for teardown only. This runs as the superuser
            # fixture connection, never as the application role.
            await conn.execute(
                text("ALTER TABLE audit_entries DISABLE TRIGGER trg_audit_entries_immutable")
            )
            await conn.execute(text("DELETE FROM audit_entries"))
            await conn.execute(
                text("ALTER TABLE audit_entries ENABLE TRIGGER trg_audit_entries_immutable")
            )
            # Reverse dependency order: actions reference requests, requests
            # reference delegations and policies, all reference users.
            await conn.execute(text("DELETE FROM approval_actions"))
            await conn.execute(text("DELETE FROM approval_requests"))
            await conn.execute(text("DELETE FROM approval_delegations"))
            await conn.execute(text("DELETE FROM holidays"))
            await conn.execute(text("DELETE FROM sla_policies"))
            await conn.execute(text("DELETE FROM processed_events"))
            await conn.execute(text("DELETE FROM outbox_events"))
            await conn.execute(text("DELETE FROM role_assignments"))
            await conn.execute(text("DELETE FROM users"))
            await conn.execute(text("DELETE FROM identity_provider_configs"))
            await conn.execute(text("DELETE FROM roles"))
            await conn.execute(text("DELETE FROM feature_flags"))
        await conn.execute(text("SELECT set_config('app.current_organization_id', '', false)"))
        await conn.execute(
            text("DELETE FROM organizations WHERE id IN (:a, :b)"),
            {"a": org_a, "b": org_b},
        )
    await engine.dispose()


# ===========================================================================
# API fixtures (Unit 2)
# ===========================================================================


@pytest_asyncio.fixture(loop_scope="session")
async def api_client(setup_database: str) -> AsyncIterator[AsyncClient]:
    """
    Yield an HTTP client wired to the application in-process.

    ASGITransport calls the app directly rather than over a socket, so there is
    no server to start and no port to allocate — but the full middleware stack,
    dependency injection and error handling all run exactly as they would in
    production. That is what makes these genuine request-path tests rather than
    unit tests with an HTTP-shaped wrapper.

    Settings already point at the test container, courtesy of the autouse
    `configure_application_settings` fixture, so this only builds the app.

    Note it does NOT dispose the engine on teardown. The engine is shared with
    every test that opens a session through production code, and tearing it down
    per test would break them.
    """
    # Imported here, not at module scope: importing the app module triggers
    # create_app(), which reads settings. The environment has to be set first.
    from platform_core.api.app import create_app

    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture(loop_scope="session")
async def admin_engine(postgres_container):
    """
    Yield an engine connected as the container superuser.

    Needed only by tests that must act outside the application's privileges:
    disabling the audit immutability trigger to simulate tampering, and
    asserting that even the table owner is refused an UPDATE.

    Deliberately a separate fixture rather than a convenience on
    `session_factory`, so that any test using elevated privileges is obvious
    from its signature.
    """
    engine = create_async_engine(
        postgres_container.get_connection_url(), isolation_level="AUTOCOMMIT"
    )
    yield engine
    await engine.dispose()
