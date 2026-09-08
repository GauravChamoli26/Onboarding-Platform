"""
Migration 0006 - notification service.

CREATES
    notification_templates  versioned templates, with DLT registration for SMS
    notification_logs       one row per notification attempt

THE DLT COLUMNS ARE NOT METADATA
    Indian regulation requires every commercial SMS to be sent against a
    template registered in advance with the DLT platform. `dlt_template_id` is
    what makes a message deliverable, and recording it per message is what makes
    a regulatory query answerable.

WHAT notification_logs DELIBERATELY LACKS
    A rendered body column. A notification about a candidate contains their
    name and often their contact details; storing the text would put PII in a
    table outside the retention purge path. The log records which template
    version was used and who it went to.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TENANT_SETTING = "app.current_organization_id"
TENANT_TABLES = ("notification_templates", "notification_logs")


def upgrade() -> None:
    """Create the notification tables and their isolation policies."""

    op.create_table(
        "notification_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        # --- DLT registration, SMS only ---
        sa.Column("dlt_template_id", sa.String(length=64), nullable=True),
        sa.Column("dlt_entity_id", sa.String(length=64), nullable=True),
        sa.Column("dlt_registered_at", sa.Date(), nullable=True),
        sa.Column(
            "dlt_approval_status",
            sa.String(length=16),
            nullable=False,
            server_default="NotRequired",
        ),
        # --- Content ---
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        # Declared rather than inferred from the body, so a missing value fails
        # at send time with a clear message instead of rendering "{job_title}".
        sa.Column(
            "variables",
            postgresql.ARRAY(sa.String(length=64)),
            nullable=False,
            server_default="{}",
        ),
        # DLT registration is per language, so locale is part of a template's
        # identity rather than a formatting detail.
        sa.Column("locale", sa.String(length=16), nullable=False, server_default="en-IN"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.PrimaryKeyConstraint("id", name="pk_notification_templates"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_notification_templates_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        # One row per key, channel, locale and version. Two rows sharing all
        # four would make template resolution depend on read order.
        sa.UniqueConstraint(
            "organization_id",
            "template_key",
            "channel",
            "locale",
            "version",
            name="uq_notification_templates_key",
        ),
        sa.CheckConstraint(
            "channel IN ('Email', 'Slack', 'SMS')",
            name="ck_notification_templates_channel",
        ),
        sa.CheckConstraint(
            "dlt_approval_status IN ('NotRequired', 'Pending', 'Approved', 'Rejected')",
            name="ck_notification_templates_dlt_status",
        ),
        # An approved SMS template without a DLT template ID is unusable: the
        # provider has nothing to match against the registry. Enforced here as
        # well as in the service, because a template is configuration and
        # configuration is edited by people.
        sa.CheckConstraint(
            "channel <> 'SMS' OR dlt_approval_status <> 'Approved' OR dlt_template_id IS NOT NULL",
            name="ck_notification_templates_sms_needs_dlt_id",
        ),
    )
    op.create_index(
        "ix_notification_templates_organization_id",
        "notification_templates",
        ["organization_id"],
    )
    # Resolution looks up by key, channel and locale on every send.
    op.create_index(
        "ix_notification_templates_lookup",
        "notification_templates",
        ["organization_id", "template_key", "channel", "locale", "is_active"],
    )

    op.create_table(
        "notification_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_type", sa.String(length=16), nullable=False),
        # A user ID, or an application ID for a candidate. Never an email
        # address or phone number - those are PII and live on the profile.
        sa.Column("recipient_ref", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("notification_template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("triggering_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        # Needed to reconcile a delivery webhook back to the row that sent it.
        sa.Column("provider_message_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="Queued"),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        # Which portal link was embedded, so a leaked link can be traced back to
        # the message that delivered it (ADR-010).
        sa.Column("portal_token_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Non-PII debugging context: template key and version. Never the
        # rendered body, never variable values.
        sa.Column("context", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "queued_at",
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
        sa.PrimaryKeyConstraint("id", name="pk_notification_logs"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_notification_logs_organization_id_organizations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["notification_template_id"],
            ["notification_templates.id"],
            name="fk_notification_logs_template_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('Queued', 'Sent', 'Delivered', 'Bounced', 'Failed', 'Suppressed')",
            name="ck_notification_logs_status",
        ),
    )
    op.create_index(
        "ix_notification_logs_organization_id",
        "notification_logs",
        ["organization_id"],
    )
    op.create_index("ix_notification_logs_recipient", "notification_logs", ["recipient_ref"])
    # Reconciling an inbound delivery webhook.
    op.create_index(
        "ix_notification_logs_provider_message_id",
        "notification_logs",
        ["provider_message_id"],
    )

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

    op.drop_index("ix_notification_logs_provider_message_id", table_name="notification_logs")
    op.drop_index("ix_notification_logs_recipient", table_name="notification_logs")
    op.drop_index("ix_notification_logs_organization_id", table_name="notification_logs")
    op.drop_table("notification_logs")

    op.drop_index("ix_notification_templates_lookup", table_name="notification_templates")
    op.drop_index("ix_notification_templates_organization_id", table_name="notification_templates")
    op.drop_table("notification_templates")
