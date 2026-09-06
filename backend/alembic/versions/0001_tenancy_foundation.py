"""
Migration 0001 — tenancy foundation.

WHAT THIS MIGRATION CREATES
    organizations   the tenant table itself (SDD §A1, minimal subset for Phase 0)
    feature_flags   the first tenant-scoped table (SDD §A4)

WHY feature_flags SPECIFICALLY
    Row-level security cannot be tested without a tenant-scoped table to test
    against. Feature flags are the simplest genuinely-needed entity in the
    system, so they serve as both the first real table and the proof that the
    isolation pattern works. Every tenant-scoped table added from here follows
    the same three-step pattern shown below.

THE PATTERN EVERY TENANT-SCOPED TABLE MUST FOLLOW
    1. ENABLE ROW LEVEL SECURITY   — turns policies on
    2. FORCE ROW LEVEL SECURITY    — applies them to the table owner too
    3. CREATE POLICY               — the actual rule

    Step 2 is the one people miss, and missing it is invisible: policies exist,
    the migration succeeds, and the table owner sees every row. The isolation
    test catches it.

Revision ID: 0001
Revises: None
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# The runtime parameter name RLS policies read. MUST match
# platform_core.db.session.TENANT_SETTING exactly.
TENANT_SETTING = "app.current_organization_id"


def upgrade() -> None:
    """Create the tenant table, the first tenant-scoped table, and its policy."""

    # ------------------------------------------------------------------
    # organizations — the tenant table
    # ------------------------------------------------------------------
    # Deliberately has NO row-level security policy. It is the table that
    # defines tenants, so it cannot be scoped by tenant without a chicken-and-egg
    # problem. Access to it is controlled at the application layer instead, and
    # reads go through get_system_session().
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("legal_entity_name", sa.String(length=255), nullable=True),
        # Asia/Kolkata by default; drives business-day SLA calculation (SDD §4.4).
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="Asia/Kolkata",
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
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
    )

    # ------------------------------------------------------------------
    # feature_flags — first tenant-scoped table (SDD §A4)
    # ------------------------------------------------------------------
    op.create_table(
        "feature_flags",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Flag keys from Spec V3.3 §Feature Flags. Stored as text with a check
        # constraint rather than a native enum: adding a value to a PostgreSQL
        # enum requires a migration and locks, whereas a check constraint is
        # cheap to amend, and audit exports stay readable either way (SDD §0).
        sa.Column("flag_key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        # Who toggled it and why. Flags gate compliance-relevant behaviour
        # (AI Copilot), so attribution matters — SDD §A4.
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_feature_flags"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_feature_flags_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        # One row per flag per organisation.
        sa.UniqueConstraint("organization_id", "flag_key", name="uq_feature_flags_organization_id"),
        sa.CheckConstraint(
            "flag_key IN ('TalentPool', 'AICopilot', 'ConfigurablePipelines', "
            "'InternalNotes', 'CrossRoundFeedbackVisibility', 'AIScreening', "
            "'BackgroundVerification', 'KitDispatch')",
            name="ck_feature_flags_flag_key",
        ),
    )
    op.create_index("ix_feature_flags_organization_id", "feature_flags", ["organization_id"])

    # ------------------------------------------------------------------
    # Row-level security — the three-step pattern
    # ------------------------------------------------------------------
    # Step 1: turn policies on for this table.
    op.execute("ALTER TABLE feature_flags ENABLE ROW LEVEL SECURITY")

    # Step 2: apply them to the table owner as well. Without this, the owning
    # role bypasses every policy — and migrations run as the owner, so a test
    # connecting with those credentials would see all rows and pass a check that
    # proves nothing.
    op.execute("ALTER TABLE feature_flags FORCE ROW LEVEL SECURITY")

    # Step 3: the policy itself.
    #
    #   current_setting(name, true)  -> the 'true' means "missing is OK, return
    #                                   NULL" rather than raising. Essential:
    #                                   an unset tenant must yield zero rows,
    #                                   not a 500.
    #   NULLIF(..., '')              -> the session layer writes empty string for
    #                                   "no tenant"; convert it to NULL so the
    #                                   cast to uuid does not fail.
    #   organization_id = NULL       -> never true, so no rows. Fails closed.
    #
    # USING controls which rows are visible to SELECT/UPDATE/DELETE.
    # WITH CHECK controls which rows may be written by INSERT/UPDATE — without
    # it, a caller could insert a row belonging to another tenant even though
    # they could not read it back.
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON feature_flags
            USING (
                organization_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid
            )
            WITH CHECK (
                organization_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid
            )
        """
    )


def downgrade() -> None:
    """Reverse the migration. Policies drop with their tables."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON feature_flags")
    op.drop_index("ix_feature_flags_organization_id", table_name="feature_flags")
    op.drop_table("feature_flags")
    op.drop_table("organizations")
