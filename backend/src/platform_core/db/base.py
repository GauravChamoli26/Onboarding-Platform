"""
Declarative base classes and the conventions every table follows.

WHAT THIS MODULE DOES
    Defines the two base classes every model inherits from, so that the
    conventions in SDD §0 are applied structurally rather than remembered.

THE TWO BASES
    `Base`        — no tenant column. Used only by Organization itself, which
                    *is* the tenant, and by any future genuinely global table.
    `TenantModel` — carries `organization_id`. Used by everything else.

WHY THE SPLIT MATTERS
    SDD §0 requires `organization_id` on every entity "without exception,
    including child records", so that isolation is enforceable at one layer
    rather than inferred through joins. Making it a base class means a developer
    cannot forget it — a tenant-scoped table that does not inherit TenantModel
    is visible in review as a missing base class, not as an absent column
    somewhere in a long definition.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from platform_core.db.types import uuid7

# ---------------------------------------------------------------------------
# Naming conventions
# ---------------------------------------------------------------------------
# Without these, Alembic autogenerates constraint names that differ between
# environments, which makes migrations that drop constraints fail unpredictably.
# Setting them once here means every index, constraint and key has a
# deterministic name derived from the table and columns it covers.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",  # index
    "uq": "uq_%(table_name)s_%(column_0_name)s",  # unique constraint
    "ck": "ck_%(table_name)s_%(constraint_name)s",  # check constraint
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """
    Root declarative base. Applies naming conventions and the shared columns
    that every table has regardless of tenancy.

    Inherit from this ONLY for tables that are not tenant-scoped — currently
    just Organization. Everything else uses TenantModel.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # --- Primary key --------------------------------------------------------
    # UUIDv7, generated in Python rather than by the database. Generating it
    # application-side means the ID is known before the INSERT, which is what
    # lets us build an object graph (and its outbox event) in memory and commit
    # the whole thing in one transaction.
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid7,
    )

    # --- Timestamps ---------------------------------------------------------
    # Stored as timestamptz in UTC. Display conversion to Asia/Kolkata happens
    # at the presentation layer, never in the database.
    #
    # server_default=func.now() means the database supplies the value, so rows
    # inserted by a migration or a manual fix still get correct timestamps.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),  # SQLAlchemy sets this on any ORM-level UPDATE
        nullable=False,
    )


class TenantModel(Base):
    """
    Base for every tenant-scoped entity.

    Adds `organization_id`, which is the column every row-level security policy
    compares against. A table inheriting this base and having RLS enabled is
    isolated; one missing either is not.

    The migration that creates such a table MUST also enable and force RLS and
    create the policy — see alembic/versions/0001 for the pattern, and the
    isolation test that catches omissions.
    """

    __abstract__ = True  # no table of its own; only subclasses become tables

    organization_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,  # every tenant-scoped query filters on this column
    )
    # ondelete="RESTRICT" is deliberate: deleting an organisation with data
    # should fail loudly rather than cascade. Tenant offboarding is a deliberate,
    # audited process (Phase 8), not a foreign key side effect.
