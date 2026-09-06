"""
Alembic environment configuration.

WHAT THIS DOES
    Wires Alembic to the application's database URL and model metadata, so that
    `alembic upgrade head` and `alembic revision --autogenerate` both work.

TWO THINGS THAT DIFFER FROM THE ALEMBIC DEFAULT

    1. The URL comes from the environment, not alembic.ini. Credentials in a
       committed file are a leak that survives deletion from git history
       (ADR-014, .gitignore).

    2. Migrations run through a SYNCHRONOUS driver even though the application
       is async. Alembic's migration context is synchronous, and mixing an
       async engine into it adds complexity for no benefit — migrations are a
       one-shot batch operation, not a request path. The URL is therefore
       rewritten from asyncpg to psycopg on the way in.

WHO RUNS MIGRATIONS
    A privileged role that owns the tables — NOT the application's app_user.
    This is why migrations can create RLS policies while the application cannot
    bypass them. See scripts/init-db.sql.
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# --- Make the application package importable --------------------------------
# Alembic runs from the project root, where src/ is not on the path by default.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Importing the models package registers every model on Base.metadata.
# Without this, `alembic revision --autogenerate` sees no tables defined and
# proposes dropping every table that exists in the database.
import platform_core.models  # noqa: E402, F401
from platform_core.db.base import Base  # noqa: E402  (import must follow path setup)

config = context.config

# Configure logging from alembic.ini, if it defines any.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- Database URL -----------------------------------------------------------
database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL is not set. Copy .env.example to .env, or export the "
        "variable directly. Alembic does not read .env automatically — on "
        "Windows, use:  $env:DATABASE_URL = 'postgresql+psycopg://...'"
    )

# Swap the async driver for a sync one. Alembic's migration context is
# synchronous; asyncpg cannot be used here.
database_url = database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
config.set_main_option("sqlalchemy.url", database_url)

# --- Model metadata ---------------------------------------------------------
# What `--autogenerate` compares the live database against. Every model module
# must be imported before this point, or autogenerate will propose dropping
# tables it cannot see. Phase 1 adds those imports here.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Emit SQL to stdout instead of running it.

    Used to review what a migration will do before applying it in staging or
    production, and to hand SQL to a DBA where direct access is restricted.
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and apply migrations."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        # NullPool: a migration run is short-lived and single-connection, so
        # pooling adds nothing and can leave connections open at exit.
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detect column type changes during autogenerate. Off by default,
            # which silently misses a varchar(50) becoming varchar(255).
            compare_type=True,
            # Detect server-side default changes too.
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
