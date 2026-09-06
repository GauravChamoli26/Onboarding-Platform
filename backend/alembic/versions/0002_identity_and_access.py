"""
Migration 0002 — identity and access.

CREATES
    identity_provider_configs   per-organisation SSO settings
    roles                       named capability bundles
    users                       internal accounts
    role_assignments            grants of roles to users

ORDER MATTERS
    users references identity_provider_configs, which references roles, so
    roles and IdP configs are created first. Alembic will not work this out for
    you when tables are created in one revision.

EVERY TABLE IS TENANT-SCOPED
    All four follow the three-step RLS pattern established in 0001: ENABLE,
    FORCE, then a policy with both USING and WITH CHECK. The users table
    especially — a directory of who works at each customer is exactly the kind
    of thing that must not cross tenants.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TENANT_SETTING = "app.current_organization_id"

# Every table created here is tenant-scoped, so every one gets the full pattern.
TENANT_TABLES = (
    "identity_provider_configs",
    "roles",
    "users",
    "role_assignments",
)


def _timestamps() -> list[sa.Column]:
    """Standard created_at / updated_at columns (SDD §0 conventions)."""
    return [
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
    ]


def upgrade() -> None:
    """Create the identity tables and their isolation policies."""

    # ------------------------------------------------------------------
    # roles — created first; users and IdP configs both reference it
    # ------------------------------------------------------------------
    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_key", sa.String(length=64), nullable=False),
        # Text array rather than JSON: queryable with ANY(), and readable in an
        # audit export years from now.
        sa.Column(
            "capabilities",
            postgresql.ARRAY(sa.String(length=64)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_roles_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        # One role per name per organisation.
        sa.UniqueConstraint("organization_id", "role_key", name="uq_roles_organization_id"),
    )
    op.create_index("ix_roles_organization_id", "roles", ["organization_id"])

    # ------------------------------------------------------------------
    # identity_provider_configs
    # ------------------------------------------------------------------
    op.create_table(
        "identity_provider_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("protocol", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("metadata_url", sa.Text(), nullable=True),
        sa.Column("client_id", sa.String(length=255), nullable=True),
        # Pointers into Secrets Manager, never the secret itself — a secret in a
        # column ends up in every backup and every replica.
        sa.Column("client_secret_ref", sa.String(length=255), nullable=True),
        sa.Column("certificate_ref", sa.String(length=255), nullable=True),
        sa.Column(
            "attribute_mapping",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "jit_provisioning_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("default_role_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_identity_provider_configs"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_identity_provider_configs_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["default_role_id"],
            ["roles.id"],
            name="fk_identity_provider_configs_default_role_id_roles",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_identity_provider_configs_organization_id",
        "identity_provider_configs",
        ["organization_id"],
    )

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("employee_code", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="Active"),
        # The durable link to the external identity. Email changes; this does not.
        sa.Column("external_idp_subject", sa.String(length=255), nullable=True),
        sa.Column("idp_config_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_users_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["idp_config_id"],
            ["identity_provider_configs.id"],
            name="fk_users_idp_config_id_identity_provider_configs",
            ondelete="SET NULL",
        ),
        # Email is unique per organisation, not globally: the same person may
        # legitimately hold an account in two customer organisations.
        sa.UniqueConstraint("organization_id", "email", name="uq_users_organization_id"),
        sa.CheckConstraint(
            "status IN ('Active', 'Suspended', 'Offboarded')",
            name="ck_users_status",
        ),
    )
    op.create_index("ix_users_organization_id", "users", ["organization_id"])
    # Login looks users up by IdP subject, so it needs its own index.
    op.create_index("ix_users_external_idp_subject", "users", ["external_idp_subject"])

    # ------------------------------------------------------------------
    # role_assignments
    # ------------------------------------------------------------------
    op.create_table(
        "role_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "scope_type",
            sa.String(length=32),
            nullable=False,
            server_default="Organization",
        ),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Null means indefinite. Checked at resolution time, not by a cleanup
        # job, so a failed job cannot leave access alive.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_role_assignments"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_role_assignments_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_role_assignments_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name="fk_role_assignments_role_id_roles",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            name="fk_role_assignments_granted_by_users",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "scope_type IN ('Organization', 'Department', 'JobPosting')",
            name="ck_role_assignments_scope_type",
        ),
        # A scoped assignment must name what it is scoped to; an organisation
        # -wide one must not. Without this, a DEPARTMENT assignment with a null
        # scope_id would silently behave as unrestricted.
        sa.CheckConstraint(
            "(scope_type = 'Organization' AND scope_id IS NULL) "
            "OR (scope_type <> 'Organization' AND scope_id IS NOT NULL)",
            name="ck_role_assignments_scope_consistency",
        ),
    )
    op.create_index("ix_role_assignments_organization_id", "role_assignments", ["organization_id"])
    # Capability resolution filters by user on every authorised request.
    op.create_index("ix_role_assignments_user_id", "role_assignments", ["user_id"])

    # ------------------------------------------------------------------
    # Row-level security — the same three steps as 0001, for every table
    # ------------------------------------------------------------------
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE is the step people miss, and missing it is invisible: the policy
        # exists, the migration succeeds, and the table owner sees every row.
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
    """Reverse the migration. Drop order is the inverse of creation."""
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_index("ix_role_assignments_user_id", table_name="role_assignments")
    op.drop_index("ix_role_assignments_organization_id", table_name="role_assignments")
    op.drop_table("role_assignments")

    op.drop_index("ix_users_external_idp_subject", table_name="users")
    op.drop_index("ix_users_organization_id", table_name="users")
    op.drop_table("users")

    op.drop_index(
        "ix_identity_provider_configs_organization_id",
        table_name="identity_provider_configs",
    )
    op.drop_table("identity_provider_configs")

    op.drop_index("ix_roles_organization_id", table_name="roles")
    op.drop_table("roles")
