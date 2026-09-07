"""
ApprovalRequest and ApprovalAction — the shared approval engine's records.

WHY THIS EXISTS AT ALL
    An earlier design expressed approvals as nullable `approver_id` and
    `approved_at` columns on Job Posting, Negotiation Log and Offer. That shape
    cannot support any of what the spec requires:

    - Delegation to a named alternate for a date range. A column holds one
      person, with nowhere to record that they were acting for someone else.
    - Escalation after a configurable window. There is no deadline to escalate
      against and no place to record that escalation happened.
    - A unified pending-approvals view. Three unrelated columns on three tables
      cannot be queried as one queue.
    - An audit trail of a request that escalated twice before resolution. A
      column holds the final state and forgets the path.

    So approvals became a first-class entity. This is the largest single
    structural change in the design (Decision Log G1), and three modules depend
    on it: job publish, above-band CTC, and offer letter approval.

TWO TABLES, DELIBERATELY
    ApprovalRequest holds current state — who owns it, when it is due, how it
    resolved. ApprovalAction records every event along the way. Collapsing them
    into one row would lose the history, which is precisely the thing an
    approval trail exists to keep.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_core.db.base import TenantModel


class ApprovalType(StrEnum):
    """
    What is being approved.

    Extensible: adding a type means adding a value here and a check-constraint
    migration, not a new table.
    """

    JOB_PUBLISH = "JobPublish"  # Module 1
    CTC_ABOVE_BAND = "CTCAboveBand"  # Module 5
    OFFER_LETTER = "OfferLetter"  # Module 7


class ApprovalStatus(StrEnum):
    """Lifecycle of a request."""

    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    # Overdue and escalated, but still awaiting a decision. Deliberately not
    # terminal: escalation changes who is being asked, not whether an answer is
    # still needed.
    ESCALATED = "Escalated"
    # The underlying thing no longer needs approving — the job was cancelled,
    # the offer superseded.
    WITHDRAWN = "Withdrawn"
    EXPIRED = "Expired"


class ApprovalActionType(StrEnum):
    """What happened to a request."""

    APPROVED = "Approved"
    REJECTED = "Rejected"
    REASSIGNED = "Reassigned"
    ESCALATED = "Escalated"
    COMMENT_ADDED = "CommentAdded"
    REMINDED = "Reminded"


class ApprovalRequest(TenantModel):
    """One pending or resolved approval."""

    __tablename__ = "approval_requests"

    approval_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # Polymorphic target: Job Posting, Negotiation Log or Offer. Not a foreign
    # key, because it points at three different tables — the trade is that
    # referential integrity here is the engine's responsibility rather than the
    # database's.
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    # Denormalised so the approvals queue can show candidate context without
    # joining through three different entity types. Null for approvals that
    # concern no application, such as publishing a job.
    application_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, index=True
    )

    # The capability the approver must hold. Stored rather than derived, so a
    # later change to what an approval type requires does not retroactively
    # alter who was allowed to approve a historical request.
    required_capability: Mapped[str] = mapped_column(String(64), nullable=False)

    # Who is being asked. Resolved through active delegations at assignment
    # time, so this may be the delegate rather than the original approver.
    assigned_to_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Set when the assignment came via a delegation. Without this the trail
    # shows the delegate approving in their own right, which misrepresents what
    # happened and who was accountable.
    resolved_via_delegation_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("approval_delegations.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=ApprovalStatus.PENDING.value
    )

    # --- Deadline -----------------------------------------------------------
    sla_policy_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("sla_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Computed in business days against the organisation's calendar and stored,
    # not recomputed on read. A holiday added later must not silently move a
    # deadline that has already been communicated.
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_to_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # How many reminders have been sent. Drives the "reminder on first miss,
    # escalate on second" rule the spec sets for interview feedback.
    reminder_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # --- Context ------------------------------------------------------------
    # What the approver was shown at request time — the CTC figure, the band
    # that was breached, the job title. Snapshotted because the underlying
    # record changes, and an approval is only meaningful alongside what was
    # actually presented.
    context_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    requested_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ApprovalRequest {self.approval_type} {self.status} "
            f"{self.entity_type}:{self.entity_id}>"
        )


class ApprovalAction(TenantModel):
    """One event in a request's history."""

    __tablename__ = "approval_actions"

    approval_request_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("approval_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    action: Mapped[str] = mapped_column(String(16), nullable=False)

    # Null when the system acted — an escalation or an automated reminder.
    actor_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    acted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<ApprovalAction {self.action} on {self.approval_request_id}>"
