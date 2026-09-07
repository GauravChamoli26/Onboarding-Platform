"""
SLA policy and the working calendar.

WHAT LIVES HERE
    SLAPolicy   how long a given kind of task may sit before it escalates
    Holiday     dates an organisation does not work

WHY SLAs ARE DATA RATHER THAN CONSTANTS
    The spec gives defaults — job approval 2 business days, interview feedback
    3, document reminders at 2/5/8 — and then says every one is configurable.
    Customers hire at different speeds and a two-day approval window that suits
    a twenty-person company is unworkable for one with three approval layers.

WHY HOLIDAYS ARE PER ORGANISATION
    India's public holiday list is long and substantially regional. Two
    customers in different states observe different days, and a shared national
    list would be wrong for both.

    An organisation with no holidays loaded still works — it simply treats every
    weekday as a working day, which escalates approvals through the festival
    season. That is a data problem rather than a code one, and the seeding is a
    customer-onboarding step.
"""

from datetime import date
from enum import StrEnum

from sqlalchemy import ARRAY, Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from platform_core.db.base import TenantModel


class SLAType(StrEnum):
    """The kinds of deadline the platform tracks."""

    JOB_APPROVAL = "JobApproval"  # default 2 business days
    INTERVIEW_FEEDBACK = "InterviewFeedback"  # default 3 business days
    OFFER_APPROVAL = "OfferApproval"
    CTC_APPROVAL = "CTCApproval"
    DOCUMENT_SUBMISSION = "DocumentSubmission"  # reminders at 2/5/8
    BGV_TURNAROUND = "BGVTurnaround"


class EscalationTarget(StrEnum):
    """Where an overdue item goes when it escalates."""

    # Anyone holding the capability the original request required.
    ROLE_CAPABILITY = "RoleCapability"
    # A specific person, named on the policy.
    NAMED_USER = "NamedUser"
    # The general HR queue, for cases with no obvious individual owner.
    HR_QUEUE = "HRQueue"


class SLAPolicy(TenantModel):
    """One configurable deadline rule for one organisation."""

    __tablename__ = "sla_policies"

    sla_type: Mapped[str] = mapped_column(String(32), nullable=False)

    duration_business_days: Mapped[int] = mapped_column(Integer, nullable=False)

    # Days before the deadline at which to send a reminder. For document
    # submission the spec gives 2, 5 and 8 — measured from request rather than
    # from deadline, which is why this is an array rather than a single value.
    reminder_offsets: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default="{}"
    )

    escalation_target: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=EscalationTarget.HR_QUEUE.value
    )
    escalation_target_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # How many missed deadlines before escalating. The spec's feedback SLA
    # sends a reminder on the first miss and escalates on the second.
    escalation_after_misses: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )

    def __repr__(self) -> str:
        return f"<SLAPolicy {self.sla_type} {self.duration_business_days}bd>"


class Holiday(TenantModel):
    """One non-working date for one organisation."""

    __tablename__ = "holidays"

    holiday_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    # Regional holidays apply to some offices and not others. Null means the
    # whole organisation. Not yet used by the deadline calculation — recorded
    # now so the data does not have to be re-collected when it is.
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        return f"<Holiday {self.holiday_date} {self.name!r}>"
