"""
Notification consumer - turns domain events into notifications.

WHY THIS IS AN EVENT CONSUMER
    Build Spec V3.3 Cross-Cutting 2: "centralised service driven by the event
    stream". Modules do not send notifications; they emit events, and this
    subscribes.

    That separation is what stops notification logic accreting into every
    module, and it means a change to who gets told about an escalation is one
    edit here rather than a search through eleven modules.

WHY SUBSCRIPTIONS ARE EXPLICIT
    Unlike the audit writer, which subscribes to everything, this declares the
    events it acts on. Notifying on every event would mean notifying on
    ApplicationParsed, which nobody wants, and the resulting noise would train
    people to filter the whole channel.

RECIPIENT RESOLUTION
    Deliberately per event type rather than generic. Who should be told about an
    escalated approval is a product decision, not something derivable from the
    event envelope, and pretending otherwise produces a generic mechanism that
    is wrong in every specific case.
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.events.catalog import EventType
from platform_core.events.consumer import EventConsumer
from platform_core.events.envelope import EventEnvelope
from platform_core.models.approval import ApprovalRequest
from platform_core.models.notification import NotificationChannel, RecipientType
from platform_core.models.user import User
from platform_core.notifications.channels import ChannelRegistry
from platform_core.notifications.service import NotificationError, send_notification

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationRule:
    """
    Which template and channel an event maps to.

    A table rather than a chain of conditionals, so the full set of "what gets
    a notification" is readable in one place - including by someone from
    product who does not read Python.
    """

    template_key: str
    channel: NotificationChannel


# The routing table. Adding an event here is how a notification gets added;
# there is no other path.
APPROVAL_RULES: dict[EventType, NotificationRule] = {
    EventType.APPROVAL_REQUESTED: NotificationRule("approval.requested", NotificationChannel.EMAIL),
    EventType.APPROVAL_REMINDER_SENT: NotificationRule(
        "approval.reminder", NotificationChannel.EMAIL
    ),
    # Escalation goes to Slack as well as email. An escalation that sits unread
    # in an inbox has escalated to nobody.
    EventType.APPROVAL_ESCALATED: NotificationRule("approval.escalated", NotificationChannel.SLACK),
    EventType.APPROVAL_GRANTED: NotificationRule("approval.granted", NotificationChannel.EMAIL),
    EventType.APPROVAL_REJECTED: NotificationRule("approval.rejected", NotificationChannel.EMAIL),
}


class NotificationConsumer(EventConsumer):
    """
    Sends notifications in response to domain events.

    Currently handles approval events, which is what Module 1's publish gate and
    the escalation sweeper need. Candidate-facing notifications arrive with the
    modules that generate them.
    """

    name = "notification_service"
    subscribes_to = frozenset(APPROVAL_RULES.keys())

    def __init__(self, channels: ChannelRegistry) -> None:
        """
        Args:
            channels: registry of channel adapters. Injected rather than taken
                from the module-level default so tests can supply their own.
        """
        self._channels = channels

    async def handle(self, envelope: EventEnvelope, session: AsyncSession) -> None:
        """
        Send the notification this event calls for.

        Args:
            envelope: the event.
            session: tenant-scoped session inside a transaction.

        A missing template or a failed delivery is logged and swallowed. This
        runs inside the consumer's transaction alongside the idempotency marker,
        and raising would roll that back and cause the event to be redelivered -
        retrying a notification whose template does not exist, forever.
        """
        rule = APPROVAL_RULES.get(envelope.event_type)
        if rule is None:
            return

        recipient = await self._resolve_approval_recipient(envelope, session)
        if recipient is None:
            logger.warning(
                "No recipient resolved for notification",
                extra={"event_type": envelope.event_type.value},
            )
            return

        user_id, destination, full_name = recipient

        try:
            await send_notification(
                session,
                self._channels,
                template_key=rule.template_key,
                channel=rule.channel,
                recipient_type=RecipientType.USER,
                recipient_ref=user_id,
                destination=destination,
                variables={
                    "recipient_name": full_name,
                    "approval_type": str(envelope.payload.get("approval_type", "")),
                    "entity_type": envelope.entity_type,
                },
                triggering_event_id=envelope.event_id,
            )
        except NotificationError:
            # Configuration problem - a template that does not exist, or an SMS
            # template without DLT approval. Logged loudly, but not raised: an
            # undeliverable notification must not cause the event to be
            # redelivered indefinitely.
            logger.exception(
                "Notification could not be prepared",
                extra={
                    "event_type": envelope.event_type.value,
                    "template_key": rule.template_key,
                },
            )

    async def _resolve_approval_recipient(
        self, envelope: EventEnvelope, session: AsyncSession
    ) -> tuple[UUID, str, str] | None:
        """
        Find who to tell about an approval event.

        Args:
            envelope: the event. Its entity_id is the approval request.
            session: tenant-scoped session.

        Returns:
            tuple of (user id, destination, full name), or None if the approval
            or user is not visible - which under row-level security also covers
            an event that somehow arrived for another tenant.

        For an escalation the recipient is whoever it escalated TO; for
        everything else it is the current assignee. Notifying the original
        assignee that their overdue approval has been escalated away from them
        is not the useful message.
        """
        request = await session.get(ApprovalRequest, envelope.entity_id)
        if request is None:
            return None

        if envelope.event_type == EventType.APPROVAL_ESCALATED:
            target_user_id = request.escalated_to_user_id or request.assigned_to_user_id
        else:
            target_user_id = request.assigned_to_user_id

        result = await session.execute(
            select(User.id, User.email, User.full_name).where(User.id == target_user_id)
        )
        row = result.first()
        if row is None:
            return None
        return row.id, row.email, row.full_name
