"""
Migration 0005 - approval engine.

CREATES
    sla_policies          deadline and escalation configuration per SLA type
    holidays              non-working dates, per organisation
    approval_delegations  per-capability, date-bounded delegation
    approval_requests     the approval itself
    approval_actions      one row per decision, escalation, reminder or comment

WHY THIS EXISTS
    Approvals were previously three nullable `approver_id` columns on Job
    Posting, Negotiation Log and Offer (Decision Log G1). Delegation across a
    date range, escalation after a configurable window, and a unified pending
    -approvals queue are all unbuildable against that shape - there is nothing
    to hang a deadline or a trail on.

ORDER MATTERS
    approval_requests references approval_delegations and sla_policies, so both
    are created first. Alembic does not work this out when tables are created in
    one revision.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TENANT_SETTING = "app.current_organization_id"

TENANT_TABLES = (
    "sla_policies",
    "holidays",
    "approval_delegations",
    "approval_requests",
    "approval_actions",
)


def _timestamps() -> list[sa.Column]:
    """Standard created_at / updated_at columns (SDD section 0 conventions)."""
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


def _org_fk(table: str) -> sa.ForeignKeyConstraint:
    """The organization foreign key every tenant-scoped table carries."""
    return sa.ForeignKeyConstraint(
        ["organization_id"],
        ["organizations.id"],
        name=f"fk_{table}_organization_id_organizations",
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    """Create the approval engine tables and their isolation policies."""

    # ------------------------------------------------------------------
    # sla_policies - deadline configuration, one row per SLA type
    # ------------------------------------------------------------------
    op.create_table(
        "sla_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sla_type", sa.String(length=32), nullable=False),
        sa.Column("duration_business_days", sa.Integer(), nullable=False),
        # Days BEFORE the deadline at which to remind, e.g. {3,1}. An array
        # rather than a single value because reminders escalate in urgency.
        sa.Column(
            "reminder_offsets",
            postgresql.ARRAY(sa.Integer()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "escalation_target",
            sa.String(length=32),
            nullable=False,
            server_default="HRQueue",
        ),
        sa.Column("escalation_target_user_id", sa.String(length=64), nullable=True),
        sa.Column(
            "escalation_after_misses",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_sla_policies"),
        _org_fk("sla_policies"),
        # One policy per type per organisation. Two policies for the same type
        # would make the deadline depend on which row was read first.
        sa.UniqueConstraint("organization_id", "sla_type", name="uq_sla_policies_organization_id"),
        sa.CheckConstraint(
            "duration_business_days >= 0",
            name="ck_sla_policies_duration_business_days",
        ),
    )
    op.create_index("ix_sla_policies_organization_id", "sla_policies", ["organization_id"])

    # ------------------------------------------------------------------
    # holidays - non-working dates
    # ------------------------------------------------------------------
    # Seeding this is part of customer onboarding, not an optional extra. An
    # organisation with an empty calendar treats every weekday as working, which
    # escalates approvals through the festival season while nobody is at work.
    op.create_table(
        "holidays",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        # Regional holidays apply to some offices and not others. Not yet used
        # by the deadline calculation - recorded now so the data does not have
        # to be collected twice.
        sa.Column("region", sa.String(length=64), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_holidays"),
        _org_fk("holidays"),
        sa.UniqueConstraint(
            "organization_id",
            "holiday_date",
            "region",
            name="uq_holidays_organization_id",
        ),
    )
    op.create_index("ix_holidays_organization_id", "holidays", ["organization_id"])
    op.create_index("ix_holidays_holiday_date", "holidays", ["holiday_date"])

    # ------------------------------------------------------------------
    # approval_delegations
    # ------------------------------------------------------------------
    op.create_table(
        "approval_delegations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delegator_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("delegate_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Delegation is per capability, never blanket. Handing over the ability
        # to approve a job posting should not also hand over above-band CTC.
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", postgresql.UUID(as_uuid=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_approval_delegations"),
        _org_fk("approval_delegations"),
        sa.ForeignKeyConstraint(
            ["delegator_user_id"],
            ["users.id"],
            name="fk_approval_delegations_delegator_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["delegate_user_id"],
            ["users.id"],
            name="fk_approval_delegations_delegate_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"],
            ["users.id"],
            name="fk_approval_delegations_revoked_by_users",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "valid_to >= valid_from",
            name="ck_approval_delegations_valid_range",
        ),
        # Delegating to yourself is a no-op that looks like a control.
        sa.CheckConstraint(
            "delegator_user_id <> delegate_user_id",
            name="ck_approval_delegations_not_self",
        ),
    )
    op.create_index(
        "ix_approval_delegations_organization_id",
        "approval_delegations",
        ["organization_id"],
    )
    # Resolution looks up by delegator and capability on every approval created.
    op.create_index(
        "ix_approval_delegations_lookup",
        "approval_delegations",
        ["delegator_user_id", "capability", "valid_from", "valid_to"],
    )

    # ------------------------------------------------------------------
    # approval_requests
    # ------------------------------------------------------------------
    op.create_table(
        "approval_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_type", sa.String(length=32), nullable=False),
        # Polymorphic target: Job Posting, Negotiation Log or Offer. No foreign
        # key, deliberately - a single approval engine cannot reference three
        # tables, and the entity type plus id is sufficient to resolve it.
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Denormalised so the approvals queue can show candidate context without
        # resolving the polymorphic target first.
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("required_capability", sa.String(length=64), nullable=False),
        sa.Column("assigned_to_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Records that this landed with a delegate rather than the designated
        # approver, and which delegation put it there. Without this the audit
        # trail cannot answer "why did she approve it?"
        sa.Column("resolved_via_delegation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="Pending"),
        sa.Column("sla_policy_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Null means no deadline: an approval with no SLA policy configured is
        # still valid, it simply never escalates.
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated_to_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reminder_count", sa.Integer(), nullable=False, server_default="0"),
        # What the approver was shown at request time. An approval is a decision
        # about a specific state of the world; if the underlying record changes
        # afterwards, the decision must still be explicable.
        sa.Column(
            "context_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_approval_requests"),
        _org_fk("approval_requests"),
        sa.ForeignKeyConstraint(
            ["assigned_to_user_id"],
            ["users.id"],
            name="fk_approval_requests_assigned_to_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["escalated_to_user_id"],
            ["users.id"],
            name="fk_approval_requests_escalated_to_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name="fk_approval_requests_requested_by_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_via_delegation_id"],
            ["approval_delegations.id"],
            # Shortened deliberately: the convention-generated name would be
            # 68 characters and PostgreSQL's identifier limit is 63.
            name="fk_approval_requests_delegation_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sla_policy_id"],
            ["sla_policies.id"],
            name="fk_approval_requests_sla_policy_id_sla_policies",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status IN ('Pending', 'Approved', 'Rejected', 'Escalated', 'Withdrawn', 'Expired')",
            name="ck_approval_requests_status",
        ),
    )
    op.create_index(
        "ix_approval_requests_organization_id",
        "approval_requests",
        ["organization_id"],
    )
    op.create_index(
        "ix_approval_requests_application_id",
        "approval_requests",
        ["application_id"],
    )
    # The approvals queue: what is pending for me, soonest deadline first.
    op.create_index(
        "ix_approval_requests_queue",
        "approval_requests",
        ["assigned_to_user_id", "status", "due_at"],
    )
    # The escalation sweeper: pending and overdue. Partial, because resolved
    # rows accumulate and are irrelevant to this scan.
    op.create_index(
        "ix_approval_requests_overdue",
        "approval_requests",
        ["organization_id", "due_at"],
        postgresql_where=sa.text("status = 'Pending'"),
    )
    # Resolving the polymorphic target in the other direction.
    op.create_index(
        "ix_approval_requests_entity",
        "approval_requests",
        ["entity_type", "entity_id"],
    )

    # ------------------------------------------------------------------
    # approval_actions - the trail
    # ------------------------------------------------------------------
    # One row per event on a request, not a final state. A request that
    # escalates twice and is then approved has four rows, and the audit question
    # "who did what, when" is answerable without inference.
    op.create_table(
        "approval_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approval_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "acted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_approval_actions"),
        _org_fk("approval_actions"),
        sa.ForeignKeyConstraint(
            ["approval_request_id"],
            ["approval_requests.id"],
            name="fk_approval_actions_approval_request_id_approval_requests",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name="fk_approval_actions_actor_id_users",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_approval_actions_organization_id",
        "approval_actions",
        ["organization_id"],
    )
    op.create_index(
        "ix_approval_actions_approval_request_id",
        "approval_actions",
        ["approval_request_id"],
    )

    # ------------------------------------------------------------------
    # Row-level security - the same three steps as every other migration
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
    """Reverse the migration. Drop order is the inverse of creation."""
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_index("ix_approval_actions_approval_request_id", table_name="approval_actions")
    op.drop_index("ix_approval_actions_organization_id", table_name="approval_actions")
    op.drop_table("approval_actions")

    op.drop_index("ix_approval_requests_entity", table_name="approval_requests")
    op.drop_index("ix_approval_requests_overdue", table_name="approval_requests")
    op.drop_index("ix_approval_requests_queue", table_name="approval_requests")
    op.drop_index("ix_approval_requests_application_id", table_name="approval_requests")
    op.drop_index("ix_approval_requests_organization_id", table_name="approval_requests")
    op.drop_table("approval_requests")

    op.drop_index("ix_approval_delegations_lookup", table_name="approval_delegations")
    op.drop_index("ix_approval_delegations_organization_id", table_name="approval_delegations")
    op.drop_table("approval_delegations")

    op.drop_index("ix_holidays_holiday_date", table_name="holidays")
    op.drop_index("ix_holidays_organization_id", table_name="holidays")
    op.drop_table("holidays")

    op.drop_index("ix_sla_policies_organization_id", table_name="sla_policies")
    op.drop_table("sla_policies")
