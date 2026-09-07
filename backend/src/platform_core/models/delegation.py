"""
ApprovalDelegation — temporarily handing an approval capability to someone else.

WHAT IT IS FOR
    An approver goes on leave, or is travelling, or is covering for a vacancy.
    The spec requires that "the designated approver may delegate to a named
    alternate for a date range" (Module 1) and gives every approving role a
    `delegate_approval` capability.

WHY PER CAPABILITY RATHER THAN BLANKET
    Delegating "my approvals" while on leave sounds convenient and is too
    coarse. An HR head might hand over job publishing for a fortnight without
    handing over above-band CTC approval, which carries a different kind of
    accountability. So a delegation names one capability.

THE RULE THAT MAKES THIS SAFE
    A delegate must independently hold the capability being delegated. Checked
    when the delegation is created, and again when a request is assigned
    through it.

    Without that rule, delegation becomes a privilege-escalation path: anyone
    who can delegate could grant an approval power to someone the organisation
    never authorised. Delegation redirects authority; it does not create it.
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_core.db.base import TenantModel


class ApprovalDelegation(TenantModel):
    """One person's approval capability, handed to another for a date range."""

    __tablename__ = "approval_delegations"

    delegator_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    delegate_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # One capability per delegation. See the module docstring on why this is not
    # a blanket handover.
    capability: Mapped[str] = mapped_column(String(64), nullable=False)

    # Inclusive dates in the organisation's timezone. Dates rather than
    # timestamps because leave is booked in days, and a delegation that expires
    # at 09:00 on its last day would surprise everyone.
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Ended early. Kept rather than deleted, because requests already routed
    # through this delegation reference it, and the trail must still explain why
    # the delegate was acting.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    def is_active_on(self, day: date) -> bool:
        """
        Whether this delegation applies on a given date.

        Args:
            day: the date to test, in the organisation's timezone.

        Returns:
            bool: True if within the date range and not revoked.
        """
        if self.revoked_at is not None:
            return False
        return self.valid_from <= day <= self.valid_to

    def __repr__(self) -> str:
        return (
            f"<ApprovalDelegation {self.capability} "
            f"{self.delegator_user_id} -> {self.delegate_user_id} "
            f"{self.valid_from}..{self.valid_to}>"
        )
