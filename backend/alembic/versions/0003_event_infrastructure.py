"""
Migration 0003 — event infrastructure.

CREATES
    outbox_events     domain events awaiting or having completed publication
    processed_events  consumer-side idempotency records

Both are tenant-scoped and follow the three-step RLS pattern.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TENANT_SETTING = "app.current_organization_id"
TENANT_TABLES = ("outbox_events", "processed_events")


def upgrade() -> None:
    """Create the outbox and idempotency tables."""

    # ------------------------------------------------------------------
    # outbox_events
    # ------------------------------------------------------------------
    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        # --- Envelope ---
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("causation_id", postgresql.UUID(as_uuid=True), nullable=True),
        # BigInteger identity column. Assigned by the database so ordering
        # cannot be affected by clock skew between application instances.
        sa.Column(
            "sequence_number",
            sa.BigInteger(),
            sa.Identity(always=True),
            nullable=False,
        ),
        # JSONB rather than JSON: queryable, indexable, and stored in a binary
        # form that does not preserve insignificant whitespace.
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("contains_pii", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "emitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # --- Publication state ---
        sa.Column("status", sa.String(length=16), nullable=False, server_default="Pending"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_outbox_events_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("sequence_number", name="uq_outbox_events_sequence_number"),
        sa.CheckConstraint(
            "status IN ('Pending', 'Published', 'Failed')",
            name="ck_outbox_events_status",
        ),
    )
    op.create_index("ix_outbox_events_organization_id", "outbox_events", ["organization_id"])
    # The relay's hot query: pending rows whose retry time has arrived, in
    # sequence order. A partial index keeps it small — published rows accumulate
    # and are irrelevant to this lookup.
    op.create_index(
        "ix_outbox_events_pending",
        "outbox_events",
        ["organization_id", "next_attempt_at", "sequence_number"],
        postgresql_where=sa.text("status = 'Pending'"),
    )
    # The Timeline read-model reads by application.
    op.create_index("ix_outbox_events_application_id", "outbox_events", ["application_id"])

    # ------------------------------------------------------------------
    # processed_events
    # ------------------------------------------------------------------
    op.create_table(
        "processed_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("consumer_name", sa.String(length=64), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_processed_events"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_processed_events_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        # THE constraint that makes idempotency work. On (consumer, event), not
        # on event alone — several consumers must each process the same event.
        sa.UniqueConstraint("consumer_name", "event_id", name="uq_processed_events_consumer_name"),
    )
    op.create_index("ix_processed_events_organization_id", "processed_events", ["organization_id"])

    # ------------------------------------------------------------------
    # Row-level security
    # ------------------------------------------------------------------
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (
                    organization_id
                    = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid
                )
                WITH CHECK (
                    organization_id
                    = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid
                )
            """
        )


def downgrade() -> None:
    """Reverse the migration."""
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_index("ix_processed_events_organization_id", table_name="processed_events")
    op.drop_table("processed_events")

    op.drop_index("ix_outbox_events_application_id", table_name="outbox_events")
    op.drop_index("ix_outbox_events_pending", table_name="outbox_events")
    op.drop_index("ix_outbox_events_organization_id", table_name="outbox_events")
    op.drop_table("outbox_events")
