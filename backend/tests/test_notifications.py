"""
Notification service tests.

WHAT MATTERS MOST HERE
    Two hard gates, both of which refuse rather than warn:

    1. An SMS without approved DLT registration is not sent. Indian regulation
       requires every commercial SMS to go against a pre-registered template;
       the operator rejects unregistered messages and repeated violations put
       the sender ID at risk.
    2. A template whose declared variables are not all supplied is not rendered.
       A candidate receiving "Dear {full_name}" is worse than receiving nothing.

    Everything else here is plumbing. Those two are compliance controls.

AND ONE THING THE LOG MUST NOT CONTAIN
    The rendered message body. `test_log_does_not_store_the_rendered_body` is
    the guard against a well-meaning change putting candidate PII into a table
    that sits outside the retention purge path.
"""

from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
    FailingChannelAdapter,
    RecordingChannelAdapter,
)
from platform_core.notifications.service import (
    NotificationError,
    assert_sendable,
    render,
    send_notification,
)
from platform_core.observability.context import correlation_scope
from platform_core.tenancy.context import organization_context

pytestmark = pytest.mark.integration


async def _seed_template(
    factory: async_sessionmaker[AsyncSession],
    org_id: UUID,
    *,
    template_key: str = "approval.requested",
    channel: NotificationChannel = NotificationChannel.EMAIL,
    body: str = "Hello {recipient_name}, an approval awaits you.",
    subject: str | None = "Approval required",
    variables: list[str] | None = None,
    dlt_status: DltApprovalStatus = DltApprovalStatus.NOT_REQUIRED,
    dlt_template_id: str | None = None,
    version: int = 1,
) -> UUID:
    """Insert one template version."""
    template_id = uuid7()
    async with factory() as s, s.begin():
        await s.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_id)},
        )
        await s.execute(
            text("""
                INSERT INTO notification_templates
                    (id, organization_id, template_key, version, channel,
                     subject, body, variables, dlt_approval_status,
                     dlt_template_id, locale, is_active)
                VALUES (:id, :org, :key, :ver, :chan, :subj, :body, :vars,
                        :dlt_status, :dlt_id, 'en-IN', true)
            """),
            {
                "id": template_id,
                "org": org_id,
                "key": template_key,
                "ver": version,
                "chan": channel.value,
                "subj": subject,
                "body": body,
                "vars": variables if variables is not None else ["recipient_name"],
                "dlt_status": dlt_status.value,
                "dlt_id": dlt_template_id,
            },
        )
    return template_id


def _registry_with_recording() -> tuple[ChannelRegistry, RecordingChannelAdapter]:
    """A registry with a recording adapter on every channel."""
    adapter = RecordingChannelAdapter()
    reg = ChannelRegistry()
    for channel in NotificationChannel:
        reg.register(channel, adapter)
    return reg, adapter


async def _send(
    factory: async_sessionmaker[AsyncSession],
    org_id: UUID,
    reg: ChannelRegistry,
    **kwargs,
) -> NotificationLog:
    """Send one notification inside a tenant-scoped transaction."""
    with organization_context(org_id), correlation_scope("notification-test"):
        async with factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.current_organization_id', :v, true)"),
                {"v": str(org_id)},
            )
            return await send_notification(session, reg, **kwargs)


# ===========================================================================
# The DLT gate
# ===========================================================================


def test_email_template_needs_no_dlt_registration() -> None:
    """Only SMS carries the DLT requirement."""
    template = NotificationTemplate(
        template_key="x",
        version=1,
        channel=NotificationChannel.EMAIL.value,
        body="hi",
        dlt_approval_status=DltApprovalStatus.NOT_REQUIRED.value,
    )
    assert_sendable(template)  # does not raise


def test_sms_without_approved_dlt_registration_is_refused() -> None:
    """
    An SMS on a pending or rejected DLT template is not sent.

    The operator would reject it, and repeated violations put the sender ID at
    risk. Refusing before dispatch turns a regulatory problem into a
    configuration error with a clear message.
    """
    for status in (
        DltApprovalStatus.NOT_REQUIRED,
        DltApprovalStatus.PENDING,
        DltApprovalStatus.REJECTED,
    ):
        template = NotificationTemplate(
            template_key="x",
            version=1,
            channel=NotificationChannel.SMS.value,
            body="hi",
            dlt_approval_status=status.value,
            dlt_template_id="1234567890",
        )
        with pytest.raises(NotificationError, match="DLT"):
            assert_sendable(template)


def test_approved_sms_template_without_a_dlt_id_is_refused() -> None:
    """
    Marked approved but carrying no template ID is still unusable.

    The provider has nothing to match against the registry. A database check
    constraint also refuses this, but the service checks too - configuration is
    edited by people, and two independent guards is right for a regulatory one.
    """
    template = NotificationTemplate(
        template_key="x",
        version=1,
        channel=NotificationChannel.SMS.value,
        body="hi",
        dlt_approval_status=DltApprovalStatus.APPROVED.value,
        dlt_template_id=None,
    )
    with pytest.raises(NotificationError, match="dlt_template_id"):
        assert_sendable(template)


def test_approved_sms_template_with_a_dlt_id_is_sendable() -> None:
    """A properly registered SMS template passes."""
    template = NotificationTemplate(
        template_key="x",
        version=1,
        channel=NotificationChannel.SMS.value,
        body="hi",
        dlt_approval_status=DltApprovalStatus.APPROVED.value,
        dlt_template_id="1707123456789012345",
    )
    assert_sendable(template)


# ===========================================================================
# Rendering
# ===========================================================================


def test_missing_variable_is_refused_rather_than_rendered() -> None:
    """
    A template with an unsupplied variable is not sent.

    Rendering it would produce a message containing a literal placeholder. For
    SMS it would also break the DLT template match and be rejected downstream.
    """
    template = NotificationTemplate(
        template_key="x",
        version=1,
        channel=NotificationChannel.EMAIL.value,
        body="Dear {full_name}, your interview is on {date}.",
        variables=["full_name", "date"],
    )
    with pytest.raises(NotificationError, match="date"):
        render(template, {"full_name": "Priya"})


def test_rendering_substitutes_declared_variables() -> None:
    """Body and subject are both rendered."""
    template = NotificationTemplate(
        template_key="x",
        version=1,
        channel=NotificationChannel.EMAIL.value,
        subject="Approval for {job_title}",
        body="Hello {recipient_name}.",
        variables=["recipient_name", "job_title"],
    )
    body, subject = render(template, {"recipient_name": "Priya", "job_title": "Backend Engineer"})
    assert body == "Hello Priya."
    assert subject == "Approval for Backend Engineer"


def test_placeholder_not_in_declared_variables_is_an_error() -> None:
    """
    A body referencing something its declaration omits is a drift error.

    Caught explicitly rather than surfacing as a bare KeyError, so the message
    names the template rather than the failing format call.
    """
    template = NotificationTemplate(
        template_key="x",
        version=1,
        channel=NotificationChannel.EMAIL.value,
        body="Hello {recipient_name}, re {undeclared}.",
        variables=["recipient_name"],
    )
    with pytest.raises(NotificationError, match="placeholder"):
        render(template, {"recipient_name": "Priya"})


# ===========================================================================
# Sending and logging
# ===========================================================================


async def test_successful_send_is_logged_as_sent(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """A delivered notification records the provider and its message ID."""
    org_a, _ = two_organizations
    await _seed_template(session_factory, org_a)
    reg, adapter = _registry_with_recording()

    log = await _send(
        session_factory,
        org_a,
        reg,
        template_key="approval.requested",
        channel=NotificationChannel.EMAIL,
        recipient_type=RecipientType.USER,
        recipient_ref=uuid7(),
        destination="hr@example.com",
        variables={"recipient_name": "Priya"},
    )

    assert log.status == NotificationStatus.SENT.value
    assert log.provider == "recording"
    assert log.provider_message_id
    assert len(adapter.sent) == 1
    assert adapter.sent[0].body == "Hello Priya, an approval awaits you."


async def test_log_does_not_store_the_rendered_body(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    The rendered message is not persisted anywhere.

    A notification about a candidate contains their name and often their contact
    details. The log sits outside the retention purge path, so storing the text
    would mean PII that no purge removes. The log records which template version
    was used; that plus the recipient is enough to reconstruct, and nothing is
    kept permanently.
    """
    org_a, _ = two_organizations
    await _seed_template(
        session_factory,
        org_a,
        body="Candidate {recipient_name} at 9876543210 awaits approval.",
    )
    reg, _ = _registry_with_recording()

    await _send(
        session_factory,
        org_a,
        reg,
        template_key="approval.requested",
        channel=NotificationChannel.EMAIL,
        recipient_type=RecipientType.USER,
        recipient_ref=uuid7(),
        destination="hr@example.com",
        variables={"recipient_name": "Priya Sharma"},
    )

    async with session_factory() as s, s.begin():
        await s.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_a)},
        )
        row = (await s.execute(select(NotificationLog))).scalar_one()

    serialised = f"{row.context} {row.failure_reason}"
    assert "Priya Sharma" not in serialised
    assert "9876543210" not in serialised
    # The context keeps only what is needed to identify the template.
    assert row.context["template_key"] == "approval.requested"
    assert row.context["template_version"] == 1


async def test_delivery_failure_is_recorded_not_raised(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    A provider failure produces a Failed log row rather than an exception.

    The caller is usually an event consumer. Raising would roll back the
    consumer's transaction and its idempotency marker, causing the event to be
    redelivered - retrying an undeliverable notification indefinitely.
    """
    org_a, _ = two_organizations
    await _seed_template(session_factory, org_a)

    reg = ChannelRegistry()
    reg.register(NotificationChannel.EMAIL, FailingChannelAdapter())

    log = await _send(
        session_factory,
        org_a,
        reg,
        template_key="approval.requested",
        channel=NotificationChannel.EMAIL,
        recipient_type=RecipientType.USER,
        recipient_ref=uuid7(),
        destination="hr@example.com",
        variables={"recipient_name": "Priya"},
    )

    assert log.status == NotificationStatus.FAILED.value
    assert "provider unavailable" in (log.failure_reason or "")


async def test_unconfigured_channel_is_suppressed_not_failed(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    No adapter for a channel produces Suppressed, not Failed.

    Nothing went wrong - SMS simply is not contracted yet. Distinguishing the
    two means a dashboard does not report an outage during a phase where a
    channel is deliberately absent.
    """
    org_a, _ = two_organizations
    await _seed_template(
        session_factory,
        org_a,
        channel=NotificationChannel.SMS,
        subject=None,
        dlt_status=DltApprovalStatus.APPROVED,
        dlt_template_id="1707123456789012345",
    )

    log = await _send(
        session_factory,
        org_a,
        ChannelRegistry(),
        template_key="approval.requested",
        channel=NotificationChannel.SMS,
        recipient_type=RecipientType.USER,
        recipient_ref=uuid7(),
        destination="+919876543210",
        variables={"recipient_name": "Priya"},
    )

    assert log.status == NotificationStatus.SUPPRESSED.value


async def test_missing_template_raises(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    A template that does not exist is a configuration error, raised loudly.

    Unlike a delivery failure, this cannot be retried into success. Templates
    are seeded per organisation during setup, and a missing one means that
    setup is incomplete.
    """
    org_a, _ = two_organizations
    reg, _ = _registry_with_recording()

    with pytest.raises(NotificationError, match="No active"):
        await _send(
            session_factory,
            org_a,
            reg,
            template_key="does.not.exist",
            channel=NotificationChannel.EMAIL,
            recipient_type=RecipientType.USER,
            recipient_ref=uuid7(),
            destination="hr@example.com",
        )


async def test_highest_active_version_is_used(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Resolution picks the latest active version.

    Templates are immutable and versioned (ADR-012), so an edit creates a new
    row. Sending must use the newest without the old ones being deleted - they
    are what make a past notification explicable.
    """
    org_a, _ = two_organizations
    await _seed_template(session_factory, org_a, version=1, body="Old: {recipient_name}")
    await _seed_template(session_factory, org_a, version=2, body="New: {recipient_name}")
    reg, adapter = _registry_with_recording()

    await _send(
        session_factory,
        org_a,
        reg,
        template_key="approval.requested",
        channel=NotificationChannel.EMAIL,
        recipient_type=RecipientType.USER,
        recipient_ref=uuid7(),
        destination="hr@example.com",
        variables={"recipient_name": "Priya"},
    )

    assert adapter.sent[0].body == "New: Priya"


async def test_notification_logs_are_tenant_isolated(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """One organisation cannot read another's notification history."""
    org_a, org_b = two_organizations
    reg, _ = _registry_with_recording()

    for org_id in (org_a, org_b):
        await _seed_template(session_factory, org_id)
        await _send(
            session_factory,
            org_id,
            reg,
            template_key="approval.requested",
            channel=NotificationChannel.EMAIL,
            recipient_type=RecipientType.USER,
            recipient_ref=uuid7(),
            destination="hr@example.com",
            variables={"recipient_name": "Priya"},
        )

    async with session_factory() as s, s.begin():
        await s.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_a)},
        )
        count = await s.execute(text("SELECT count(*) FROM notification_logs"))
        assert int(count.scalar_one()) == 1


# ===========================================================================
# The event consumer
# ===========================================================================


def test_consumer_subscribes_to_approval_events_only() -> None:
    """
    Subscriptions are explicit, unlike the audit writer's catch-all.

    Notifying on every event would mean notifying on ApplicationParsed, and the
    resulting noise trains people to filter the whole channel.
    """
    from platform_core.events.catalog import EventType
    from platform_core.notifications.consumer import NotificationConsumer

    consumer = NotificationConsumer(ChannelRegistry())
    assert EventType.APPROVAL_ESCALATED in consumer.subscribes_to
    assert EventType.APPROVAL_REQUESTED in consumer.subscribes_to
    assert EventType.APPLICATION_PARSED not in consumer.subscribes_to
    assert EventType.SHORTLISTED not in consumer.subscribes_to


def test_escalation_is_routed_to_slack() -> None:
    """
    Escalations go to Slack, not only email.

    An escalation sitting unread in an inbox has escalated to nobody.
    """
    from platform_core.events.catalog import EventType
    from platform_core.notifications.consumer import APPROVAL_RULES

    assert APPROVAL_RULES[EventType.APPROVAL_ESCALATED].channel == (NotificationChannel.SLACK)
