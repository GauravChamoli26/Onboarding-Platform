"""
Notification service - template resolution, rendering, dispatch and logging.

THE FLOW
    resolve template -> check it may be sent -> render -> dispatch -> log

    Every step can refuse, and refusing is recorded. A notification that could
    not be sent is more useful in the log than absent from it.

TWO HARD GATES
    1. SMS without an APPROVED DLT template is refused before it reaches the
       provider. The operator would reject it anyway, and repeated violations
       put the sender ID at risk.
    2. A template whose declared variables are not all supplied is refused
       rather than rendered with a literal "{job_title}" in the text.

    Both raise rather than warn. A notification is a message to a human; sending
    a broken one is worse than sending nothing and alerting.
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.db.types import uuid7
from platform_core.models.notification import (
    DltApprovalStatus,
    NotificationChannel,
    NotificationLog,
    NotificationStatus,
    NotificationTemplate,
    RecipientType,
)
from platform_core.notifications.channels import (
    ChannelRegistry,
    OutboundMessage,
)
from platform_core.observability.context import get_correlation_id
from platform_core.tenancy.context import get_organization

logger = logging.getLogger(__name__)


class NotificationError(RuntimeError):
    """Raised when a notification cannot be prepared or sent."""


async def resolve_template(
    session: AsyncSession,
    template_key: str,
    channel: NotificationChannel,
    locale: str = "en-IN",
) -> NotificationTemplate | None:
    """
    Find the active template for a key, channel and locale.

    Args:
        session: tenant-scoped session.
        template_key: stable key across versions, e.g. "approval.requested".
        channel: which channel the template is for.
        locale: language variant. DLT registration is per language, so this is
            part of the identity of a template rather than a formatting detail.

    Returns:
        NotificationTemplate | None: the highest active version, or None.
    """
    result = await session.execute(
        select(NotificationTemplate)
        .where(NotificationTemplate.template_key == template_key)
        .where(NotificationTemplate.channel == channel.value)
        .where(NotificationTemplate.locale == locale)
        .where(NotificationTemplate.is_active.is_(True))
        .order_by(NotificationTemplate.version.desc())
        .limit(1)
    )
    return result.scalars().first()


def render(template: NotificationTemplate, variables: dict[str, Any]) -> tuple[str, str | None]:
    """
    Render a template's body and subject.

    Args:
        template: the template to render.
        variables: values for the template's declared variables.

    Returns:
        tuple[str, str | None]: rendered body, and subject where the channel
        has one.

    Raises:
        NotificationError: if any declared variable is missing.

    Missing variables raise rather than rendering a placeholder. A candidate
    receiving "Dear {full_name}" is worse than a candidate receiving nothing
    and an alert firing - and for SMS it would also break the DLT template
    match, causing the operator to reject the message.
    """
    missing = [name for name in template.variables if name not in variables]
    if missing:
        raise NotificationError(
            f"Template {template.template_key!r} v{template.version} requires "
            f"variables {missing} which were not supplied. Rendering would "
            f"produce a message containing literal placeholders."
        )

    try:
        body = template.body.format(**variables)
        subject = template.subject.format(**variables) if template.subject else None
    except (KeyError, IndexError) as exc:
        # A placeholder in the body that is not in `variables`. The declaration
        # and the body have drifted apart.
        raise NotificationError(
            f"Template {template.template_key!r} v{template.version} contains a "
            f"placeholder not listed in its declared variables: {exc}"
        ) from exc

    return body, subject


def assert_sendable(template: NotificationTemplate) -> None:
    """
    Refuse to send a template that regulation or configuration forbids.

    Args:
        template: the template about to be sent.

    Raises:
        NotificationError: if an SMS template lacks approved DLT registration.

    Indian regulation requires every commercial SMS to be sent against a
    template registered in advance under a registered entity. An unregistered
    message is rejected by the operator, and repeated violations put the sender
    ID at risk - so this is checked before dispatch rather than discovered from
    a delivery failure.
    """
    if template.channel != NotificationChannel.SMS.value:
        return

    if template.dlt_approval_status != DltApprovalStatus.APPROVED.value:
        raise NotificationError(
            f"SMS template {template.template_key!r} v{template.version} has DLT "
            f"status {template.dlt_approval_status!r}, not Approved. Indian "
            f"regulation requires an approved DLT registration before an SMS "
            f"may be sent; the operator would reject this message."
        )
    if not template.dlt_template_id:
        raise NotificationError(
            f"SMS template {template.template_key!r} v{template.version} is "
            f"marked Approved but carries no dlt_template_id. The provider "
            f"cannot match it to a registered template."
        )


async def send_notification(
    session: AsyncSession,
    channels: ChannelRegistry,
    *,
    template_key: str,
    channel: NotificationChannel,
    recipient_type: RecipientType,
    recipient_ref: UUID,
    destination: str,
    variables: dict[str, Any] | None = None,
    locale: str = "en-IN",
    triggering_event_id: UUID | None = None,
    portal_token_id: UUID | None = None,
) -> NotificationLog:
    """
    Prepare, dispatch and log one notification.

    Args:
        session: the caller's tenant-scoped session, inside a transaction.
        channels: registry of channel adapters.
        template_key: which template.
        channel: which channel.
        recipient_type: User or Candidate.
        recipient_ref: user ID, or application ID for a candidate.
        destination: email address, phone number or Slack channel. Transient -
            never stored.
        variables: values for the template's declared variables.
        locale: language variant.
        triggering_event_id: the domain event that caused this, if any.
        portal_token_id: which portal link was embedded, if any.

    Returns:
        NotificationLog: the log row, whatever the outcome. A failed send is
        recorded with status Failed rather than raising, because the caller is
        usually an event consumer and one undeliverable notification should not
        roll back the state change that produced it.

    Raises:
        NotificationError: only for preparation failures - missing template,
            missing variables, unapproved DLT registration. Those are
            configuration errors that should surface loudly, not be logged and
            forgotten.
    """
    organization_id = get_organization()
    correlation_id = get_correlation_id()
    variables = variables or {}

    template = await resolve_template(session, template_key, channel, locale)
    if template is None:
        raise NotificationError(
            f"No active {channel.value} template for {template_key!r} in locale "
            f"{locale!r}. Templates are seeded per organisation during setup."
        )

    assert_sendable(template)
    body, subject = render(template, variables)

    log = NotificationLog(
        id=uuid7(),
        organization_id=organization_id,
        recipient_type=recipient_type.value,
        recipient_ref=recipient_ref,
        channel=channel.value,
        notification_template_id=template.id,
        triggering_event_id=triggering_event_id,
        correlation_id=correlation_id,
        portal_token_id=portal_token_id,
        # Non-PII only. The rendered body is deliberately absent.
        context={"template_key": template_key, "template_version": template.version},
        status=NotificationStatus.QUEUED.value,
    )

    adapter = channels.get(channel)
    if adapter is None:
        # No adapter configured for this channel. Suppressed rather than failed:
        # nothing went wrong, the channel simply is not wired up yet. Distinct
        # from Failed so a dashboard does not report an outage during a phase
        # when SMS has deliberately not been contracted.
        log.status = NotificationStatus.SUPPRESSED.value
        log.failure_reason = f"No adapter registered for channel {channel.value}"
        session.add(log)
        logger.info(
            "Notification suppressed - no adapter",
            extra={"channel": channel.value, "template_key": template_key},
        )
        return log

    try:
        provider_message_id = await adapter.send(
            OutboundMessage(
                channel=channel,
                destination=destination,
                body=body,
                subject=subject,
                dlt_template_id=template.dlt_template_id,
            )
        )
        log.status = NotificationStatus.SENT.value
        log.provider = adapter.provider_name
        log.provider_message_id = provider_message_id
        log.sent_at = datetime.now(UTC)
    except Exception as exc:  # noqa: BLE001 - a failed notification must not
        # roll back the state change that triggered it.
        log.status = NotificationStatus.FAILED.value
        log.provider = adapter.provider_name
        log.failure_reason = str(exc)[:2000]
        logger.exception(
            "Notification delivery failed",
            extra={"channel": channel.value, "template_key": template_key},
        )

    session.add(log)
    return log
