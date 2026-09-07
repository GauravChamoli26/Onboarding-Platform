"""
Migration tests — proving Alembic produces the schema the suite assumes.

THE PROBLEM THIS CLOSES
    conftest.py creates the schema with raw SQL rather than by running Alembic,
    deliberately: a test that imports the production migration would regress
    alongside it and still pass. But that leaves two descriptions of the same
    tables, free to drift apart.

    So this file applies the real migrations to a real database and asserts the
    result matches what the rest of the suite assumes. Drift now fails the build
    instead of surfacing in staging.

WHY A SEPARATE DATABASE RATHER THAN A SEPARATE CONTAINER
    The session container is already running and conftest has created tables in
    its default database. Creating a second database inside the same container
    costs a fraction of a second; a second container costs twenty.
"""

import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration

MIGRATION_DB = "migration_check"

# Tables that must exist after migration 0001, and which of them are
# tenant-scoped. Extend as later migrations add tables — a tenant-scoped table
# missing from this list is a gap in the isolation boundary.
EXPECTED_TABLES = {
    "alembic_version",
    "organizations",
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
}
TENANT_SCOPED_TABLES = {
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
}


@pytest_asyncio.fixture(loop_scope="session")
async def migrated_database(postgres_container):
    """
    Create a clean database, apply all migrations to it, and yield its URL.

    WHY THIS TAKES postgres_container AND NOT setup_database
        `setup_database` yields a URL authenticated as app_user — the
        deliberately unprivileged application role created in
        scripts/init-db.sql. That role has no CREATEDB privilege, and it should
        not: the application has no business creating databases.

        Migrations are a different job with different authority. They run as the
        owning role, which is what allows them to create tables and RLS policies
        that the application itself cannot bypass. So this fixture connects with
        the container's superuser credentials, exactly as a deploy pipeline
        would.

        The failure this caused was the privilege separation working correctly.

    Alembic runs as a subprocess rather than through its Python API so that the
    test exercises the same entry point a developer or a deploy pipeline uses —
    `alembic upgrade head`, reading alembic.ini and env.py exactly as they will
    in production.
    """
    parsed = urlparse(postgres_container.get_connection_url())
    admin_url = urlunparse(parsed._replace(path="/postgres"))
    target_url = urlunparse(parsed._replace(path=f"/{MIGRATION_DB}"))

    # CREATE DATABASE cannot run inside a transaction block.
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {MIGRATION_DB}"))
        await conn.execute(text(f"CREATE DATABASE {MIGRATION_DB}"))
    await admin_engine.dispose()

    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        env={
            "DATABASE_URL": target_url,
            "PATH": __import__("os").environ.get("PATH", ""),
            "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
        },
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            f"alembic upgrade head failed\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )

    yield target_url

    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {MIGRATION_DB}"))
    await admin_engine.dispose()


async def test_migrations_apply_cleanly(migrated_database: str) -> None:
    """
    `alembic upgrade head` succeeds against an empty database.

    The fixture fails the test if it does not, so reaching this point is the
    assertion. Worth having as a named test so a migration failure is reported
    as a migration failure rather than as an error in whatever ran next.
    """
    engine = create_async_engine(migrated_database)
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        assert result.scalar_one() == "0005"
    await engine.dispose()


async def test_migration_creates_expected_tables(migrated_database: str) -> None:
    """Every expected table exists, and nothing unexpected does."""
    engine = create_async_engine(migrated_database)
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        tables = {row[0] for row in result}
    await engine.dispose()

    assert tables == EXPECTED_TABLES, (
        f"Schema drift. Missing: {EXPECTED_TABLES - tables}. Unexpected: {tables - EXPECTED_TABLES}"
    )


async def test_migration_enables_and_forces_rls(migrated_database: str) -> None:
    """
    Every tenant-scoped table has RLS both ENABLED and FORCED.

    The same assertion the isolation suite makes against the test schema, now
    made against the real migration. If a future migration adds a table and
    forgets FORCE, the boundary silently does nothing for that table — and this
    is what catches it.
    """
    engine = create_async_engine(migrated_database)
    async with engine.connect() as conn:
        for table in TENANT_SCOPED_TABLES:
            result = await conn.execute(
                text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"),
                {"t": table},
            )
            enabled, forced = result.one()
            assert enabled, f"{table}: RLS not enabled by migration"
            assert forced, (
                f"{table}: RLS enabled but not FORCED by migration. The table "
                f"owner bypasses every policy. Add "
                f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY."
            )
    await engine.dispose()


async def test_migration_creates_tenant_isolation_policy(
    migrated_database: str,
) -> None:
    """
    The policy exists and covers writes as well as reads.

    A policy with USING but no WITH CHECK would let a tenant insert rows
    belonging to another tenant even though it could not read them back — worse
    than a read leak, not better.
    """
    engine = create_async_engine(migrated_database)
    async with engine.connect() as conn:
        for table in TENANT_SCOPED_TABLES:
            result = await conn.execute(
                text("SELECT policyname, qual, with_check FROM pg_policies WHERE tablename = :t"),
                {"t": table},
            )
            policies = result.all()

            assert len(policies) == 1, (
                f"{table}: expected exactly one policy, found {len(policies)}"
            )
            name, using_clause, check_clause = policies[0]
            assert name == "tenant_isolation", f"{table}: unexpected policy name {name}"
            assert using_clause is not None, (
                f"{table}: policy has no USING clause — reads unprotected"
            )
            assert check_clause is not None, (
                f"{table}: policy has no WITH CHECK clause — writes unprotected"
            )
            # Both clauses must reference the setting the session layer writes.
            assert "app.current_organization_id" in using_clause
            assert "app.current_organization_id" in check_clause
    await engine.dispose()


async def test_downgrade_reverses_the_migration(migrated_database: str) -> None:
    """
    `alembic downgrade base` cleans up after itself.

    An untested downgrade is a downgrade that fails at the worst possible
    moment. Running it here means a broken rollback path is found now.

    Runs with the same owning-role credentials as the upgrade, since dropping
    tables requires the same authority that created them.
    """
    import os

    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        cwd=project_root,
        env={
            "DATABASE_URL": migrated_database,
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"alembic downgrade base failed\n{result.stdout}\n{result.stderr}"
    )

    engine = create_async_engine(migrated_database)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        remaining = {row[0] for row in rows}
    await engine.dispose()

    # alembic_version survives a downgrade by design; the domain tables must not.
    assert remaining <= {"alembic_version"}, f"Downgrade left tables behind: {remaining}"
