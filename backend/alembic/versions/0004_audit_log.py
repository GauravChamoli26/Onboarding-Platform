"""
Migration 0004 — audit log.

CREATES
    audit_entries        append-only, hash-chained audit records
    audit_entries_immutable()  trigger function refusing UPDATE and DELETE

THREE LAYERS OF IMMUTABILITY (ADR-016)
    1. REVOKE UPDATE, DELETE from the application role.
    2. A BEFORE UPDATE OR DELETE trigger that raises — this stops the table
       owner too, which the revoke does not.
    3. The hash chain, maintained in application code, which makes any
       alteration detectable even if layers 1 and 2 were somehow bypassed.

WHY BOTH THE REVOKE AND THE TRIGGER
    The revoke is the primary control and covers the application. The trigger
    covers everyone else — a migration, a DBA session, a compromised superuser.
    Neither alone is sufficient: privileges can be re-granted, and a trigger can
    be disabled, but doing either is a deliberate, auditable act rather than an
    accident.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TENANT_SETTING = "app.current_organization_id"


def upgrade() -> None:
    """Create the audit table, its policy, and its immutability guards."""

    op.create_table(
        "audit_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        # --- Chain ---
        # Assigned by the application under an advisory lock, not by a sequence.
        # A sequence leaves gaps when a transaction rolls back, and a gap is
        # indistinguishable from a deleted entry.
        sa.Column("chain_position", sa.BigInteger(), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.Column("entry_hash", sa.String(length=64), nullable=False),
        # --- Who ---
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.String(length=64), nullable=True),
        # --- What ---
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("before_state", postgresql.JSONB(), nullable=True),
        sa.Column("after_state", postgresql.JSONB(), nullable=True),
        # --- Context ---
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_audit_entries"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_audit_entries_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        # One entry per position per organisation. This is what stops two
        # concurrent writers forking the chain if the advisory lock were ever
        # bypassed — the second insert fails rather than duplicating a position.
        sa.UniqueConstraint(
            "organization_id",
            "chain_position",
            name="uq_audit_entries_organization_id",
        ),
    )
    op.create_index("ix_audit_entries_organization_id", "audit_entries", ["organization_id"])
    # Verification walks the chain in order; the unique constraint above already
    # provides this ordering, but an explicit index keeps entity lookups fast.
    op.create_index("ix_audit_entries_entity", "audit_entries", ["entity_type", "entity_id"])
    op.create_index("ix_audit_entries_actor_id", "audit_entries", ["actor_id"])

    # ------------------------------------------------------------------
    # Row-level security
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE audit_entries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_entries FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON audit_entries
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

    # ------------------------------------------------------------------
    # Immutability layer 2: the trigger
    # ------------------------------------------------------------------
    # Refuses UPDATE and DELETE from anyone, including the table owner. The
    # error message names the table and operation so the failure is
    # self-explanatory to whoever hits it.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_entries_immutable()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'audit_entries is append-only; % is not permitted (ADR-016)',
                TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_entries_immutable
            BEFORE UPDATE OR DELETE ON audit_entries
            FOR EACH ROW
            EXECUTE FUNCTION audit_entries_immutable();
        """
    )

    # ------------------------------------------------------------------
    # Immutability layer 1: revoke the grants
    # ------------------------------------------------------------------
    # init-db.sql grants SELECT, INSERT, UPDATE, DELETE on all new tables to
    # app_user via ALTER DEFAULT PRIVILEGES, so this table would inherit UPDATE
    # and DELETE without an explicit revoke.
    #
    # Guarded by a role-existence check: the migration test runs against a fresh
    # database where app_user does not exist, and REVOKE on a missing role is a
    # hard error.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
                REVOKE UPDATE, DELETE ON audit_entries FROM app_user;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """
    Reverse the migration.

    Note that dropping the table is permitted — DROP is DDL and the row-level
    trigger does not intercept it. That is correct: a downgrade is a deliberate
    schema operation, not a data modification.
    """
    op.execute("DROP TRIGGER IF EXISTS trg_audit_entries_immutable ON audit_entries")
    op.execute("DROP FUNCTION IF EXISTS audit_entries_immutable()")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON audit_entries")
    op.drop_index("ix_audit_entries_actor_id", table_name="audit_entries")
    op.drop_index("ix_audit_entries_entity", table_name="audit_entries")
    op.drop_index("ix_audit_entries_organization_id", table_name="audit_entries")
    op.drop_table("audit_entries")
