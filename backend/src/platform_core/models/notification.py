"""
NotificationTemplate and NotificationLog.

WHY TEMPLATES ARE VERSIONED AND IMMUTABLE
    The same reason CTC rule sets and pipeline templates are (ADR-012): a
    notification that went out six months ago must still be reproducible. For
    SMS there is a harder reason — see below.

THE DLT REQUIREMENT
    Indian regulation requires every commercial SMS to be sent against a
    template registered in advance with the DLT platform, under a registered
    entity. An unregistered message is rejected by the operator, and repeated
    violations put the sender ID at risk.

    So `dlt_template_id` is not metadata. It is the thing that makes the message
    deliverable, and the service refuses to send an SMS without an approved one.
    Recording it per message is what makes a regulatory query answerable.

WHAT THE LOG DOES NOT STORE
    The rendered message body. A notification about a candidate contains their
    name, and often their email or phone. Storing the rendered text would put
    PII in a table that sits outside the retention purge path, for the same
    reason event payloads carry identifiers rather than values (SDD 2.1).

    The log stores which template version was used and who it went to. Anyone
    reconstructing a message has the template and the recipient; nobody has a
    permanent copy of the personal data.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_core.db.base import TenantModel


class NotificationChannel(StrEnum):
    """Delivery channels. Per Build Spec V3.3 Cross-Cutting 2."""

    EMAIL = "Email"
    SLACK = "Slack"
    SMS = "SMS"


class DltApprovalStatus(StrEnum):
    """
    Registration state of an SMS template with the DLT platform.

    Only APPROVED templates may be used. A template in any other state produces
    a message the operator will reject, so sending is refused before it reaches
    the vendor rather than after.
    """

    NOT_REQUIRED = "NotRequired"  # email and Slack templates
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


class NotificationStatus(StrEnum):
    """Delivery state of one notification."""

    QUEUED = "Queued"
    SENT = "Sent"  # accepted by the provider
    DELIVERED = "Delivered"  # confirmed delivered, where the provider reports it
    BOUNCED = "Bounced"
    FAILED = "Failed"
    SUPPRESSED = "Suppressed"  # deliberately not sent - see the note below


class RecipientType(StrEnum):
    """Who a notification is addressed to."""

    USER = "User"  # an internal user
    CANDIDATE = "Candidate"  # via the portal, addressed by application


class NotificationTemplate(TenantModel):
    """
    One version of one notification template.

    Immutable once active, like every other versioned configuration entity
    (ADR-012). Editing creates a new version; the old one is retained so a past
    notification remains explicable.
    """

    __tablename__ = "notification_templates"

    # Stable identifier across versions, e.g. "approval.requested".
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    channel: Mapped[str] = mapped_column(String(16), nullable=False)

    # --- DLT registration, SMS only -----------------------------------------
    # Null for email and Slack. Mandatory and APPROVED for SMS, enforced by the
    # service before dispatch.
    dlt_template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dlt_entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dlt_registered_at: Mapped[datetime | None] = mapped_column(Date(), nullable=True)
    dlt_approval_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=DltApprovalStatus.NOT_REQUIRED.value,
    )

    # --- Content -------------------------------------------------------------
    # Subject is email-only; Slack and SMS have no concept of one.
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # Variable names the body expects, e.g. ["approver_name", "job_title"].
    # Declared rather than inferred so a missing value fails at send time with a
    # clear message, instead of rendering a message containing "{job_title}".
    variables: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), nullable=False, server_default="{}"
    )

    # Regional language support. The DLT registration is per language too.
    locale: Mapped[str] = mapped_column(String(16), nullable=False, server_default="en-IN")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    def __repr__(self) -> str:
        return f"<NotificationTemplate {self.template_key} v{self.version} {self.channel}>"


class NotificationLog(TenantModel):
    """
    One record per notification attempt.

    Carries no rendered body - see the module docstring.
    """

    __tablename__ = "notification_logs"

    recipient_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # A user ID, or an application ID for a candidate. Not an email address or
    # phone number: those are PII and live on the profile, not in this log.
    recipient_ref: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    channel: Mapped[str] = mapped_column(String(16), nullable=False)

    # Which template version produced this message. For SMS this is what makes
    # the DLT registration traceable per message.
    notification_template_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("notification_templates.id", ondelete="RESTRICT"),
        nullable=True,
    )

    # The domain event that caused this notification, where there was one.
    triggering_event_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)

    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # The provider's own identifier, needed to reconcile a delivery webhook back
    # to the row that sent it.
    provider_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=NotificationStatus.QUEUED.value
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Which portal link was embedded, if any. Lets a leaked link be traced back
    # to the message that delivered it (ADR-010).
    portal_token_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # Non-PII context for debugging: template key, event type. Never the
    # rendered body and never variable values.
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at_ts: Mapped[datetime] = mapped_column(
        "queued_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<NotificationLog {self.channel} {self.status} to {self.recipient_type}>"
