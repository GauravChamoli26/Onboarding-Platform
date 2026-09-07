"""
Approval engine tests.

WHAT THIS PROVES
    That the three things nullable `approver_id` columns could not do actually
    work: delegation across a date range, escalation after a deadline, and a
    complete trail of who did what.

    Decision Log G1. This is the largest structural fix in the design, and these
    tests are what make it more than a schema change.

THE TEST THAT MATTERS MOST
    `test_delegation_to_a_user_without_the_capability_is_refused`. Delegation
    redirects authority; it must not create it. A delegation that silently
    assigned work to someone unauthorised would be privilege escalation dressed
    as an out-of-office setting.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from platform_core.approvals.engine import (
    ApprovalError,
    approve,
    reject,
    request_approval,
    resolve_assignee,
    withdraw,
)
from platform_core.auth.capabilities import Capability
from platform_core.db.types import uuid7
from platform_core.models.approval import (
    ApprovalAction,
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalType,
)
from platform_core.models.outbox_event import OutboxEvent
from platform_core.models.sla_policy import SLAType
from platform_core.observability.context import correlation_scope
from platform_core.tenancy.context import organization_context

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


async def _tenant_exec(
    factory: async_sessionmaker[AsyncSession], org_id: UUID, statement, params=None
):
    """Run one statement inside a tenant-scoped transaction."""
    async with factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.current_organization_id', :v, true)"),
            {"v": str(org_id)},
        )
        return await session.execute(statement, params or {})


async def _make_user(factory: async_sessionmaker[AsyncSession], org_id: UUID, email: str) -> UUID:
    """Create an active user."""
    user_id = uuid7()
    await _tenant_exec(
        factory,
        org_id,
        text("""
            INSERT INTO users (id, organization_id, email, full_name, status)
            VALUES (:id, :org, :email, :name, 'Active')
        """),
        {"id": user_id, "org": org_id, "email": email, "name": email.split("@")[0]},
    )
    return user_id


async def _grant(
    factory: async_sessionmaker[AsyncSession],
    org_id: UUID,
    user_id: UUID,
    capability: Capability,
) -> None:
    """Give a user a role carrying one capability."""
    role_id = uuid7()
    # The suffix comes from the END of the UUID, not the start. UUIDv7 encodes a
    # millisecond timestamp in its leading bits, so two roles created in the same
    # millisecond share their first eight characters — which collided with
    # uq_roles_organization_id (organization_id, role_key). The trailing
    # characters are the random component and are unique.
    await _tenant_exec(
        factory,
        org_id,
        text("""
            INSERT INTO roles (id, organization_id, role_key, capabilities)
            VALUES (:id, :org, :key, :caps)
        """),
        {
            "id": role_id,
            "org": org_id,
            "key": f"role_{capability.value}_{str(role_id)[-12:]}",
            "caps": [capability.value],
        },
    )
    await _tenant_exec(
        factory,
        org_id,
        text("""
            INSERT INTO role_assignments
                (id, organization_id, user_id, role_id, scope_type)
            VALUES (:id, :org, :user, :role, 'Organization')
        """),
        {"id": uuid7(), "org": org_id, "user": user_id, "role": role_id},
    )


async def _delegate(
    factory: async_sessionmaker[AsyncSession],
    org_id: UUID,
    delegator: UUID,
    delegate: UUID,
    capability: Capability,
    valid_from: date,
    valid_to: date,
) -> UUID:
    """Create a delegation covering a date range."""
    delegation_id = uuid7()
    await _tenant_exec(
        factory,
        org_id,
        text("""
            INSERT INTO approval_delegations
                (id, organization_id, delegator_user_id, delegate_user_id,
                 capability, valid_from, valid_to, reason)
            VALUES (:id, :org, :from_u, :to_u, :cap, :vf, :vt, 'annual leave')
        """),
        {
            "id": delegation_id,
            "org": org_id,
            "from_u": delegator,
            "to_u": delegate,
            "cap": capability.value,
            "vf": valid_from,
            "vt": valid_to,
        },
    )
    return delegation_id


async def _sla(
    factory: async_sessionmaker[AsyncSession],
    org_id: UUID,
    sla_type: SLAType,
    days: int,
    misses: int = 1,
) -> None:
    """Configure an SLA policy."""
    await _tenant_exec(
        factory,
        org_id,
        text("""
            INSERT INTO sla_policies
                (id, organization_id, sla_type, duration_business_days,
                 reminder_offsets, escalation_target, escalation_after_misses)
            VALUES (:id, :org, :type, :days, '{}', 'HRQueue', :misses)
        """),
        {
            "id": uuid7(),
            "org": org_id,
            "type": sla_type.value,
            "days": days,
            "misses": misses,
        },
    )


async def _open_session(factory: async_sessionmaker[AsyncSession], org_id: UUID) -> AsyncSession:
    """A tenant-scoped session with an open transaction. Caller closes it."""
    session = factory()
    await session.begin()
    await session.execute(
        text("SELECT set_config('app.current_organization_id', :v, true)"),
        {"v": str(org_id)},
    )
    return session


# ===========================================================================
# Request creation and routing
# ===========================================================================


async def test_request_is_assigned_to_the_intended_approver(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """With no delegation in play, the request goes to the designated approver."""
    org_a, _ = two_organizations
    approver = await _make_user(session_factory, org_a, "hr@example.com")
    await _grant(session_factory, org_a, approver, Capability.APPROVE_JOB)

    with organization_context(org_a), correlation_scope("approval-test"):
        session = await _open_session(session_factory, org_a)
        try:
            request = await request_approval(
                session,
                approval_type=ApprovalType.JOB_PUBLISH,
                entity_type="JobPosting",
                entity_id=uuid7(),
                required_capability=Capability.APPROVE_JOB,
                intended_approver_id=approver,
            )
            await session.commit()
        finally:
            await session.close()

    assert request.assigned_to_user_id == approver
    assert request.resolved_via_delegation_id is None
    assert request.status == ApprovalStatus.PENDING.value


async def test_active_delegation_routes_the_request_to_the_delegate(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    A delegation covering today sends the request to the delegate.

    This is the capability that three nullable columns could not provide. It
    also records WHICH delegation routed it, so the audit trail can answer why
    someone other than the designated approver signed off.
    """
    org_a, _ = two_organizations
    approver = await _make_user(session_factory, org_a, "hrhead@example.com")
    stand_in = await _make_user(session_factory, org_a, "deputy@example.com")
    await _grant(session_factory, org_a, approver, Capability.APPROVE_JOB)
    await _grant(session_factory, org_a, stand_in, Capability.APPROVE_JOB)

    today = datetime.now(UTC).date()
    delegation_id = await _delegate(
        session_factory,
        org_a,
        approver,
        stand_in,
        Capability.APPROVE_JOB,
        today - timedelta(days=1),
        today + timedelta(days=7),
    )

    with organization_context(org_a), correlation_scope("delegation-test"):
        session = await _open_session(session_factory, org_a)
        try:
            request = await request_approval(
                session,
                approval_type=ApprovalType.JOB_PUBLISH,
                entity_type="JobPosting",
                entity_id=uuid7(),
                required_capability=Capability.APPROVE_JOB,
                intended_approver_id=approver,
            )
            await session.commit()
        finally:
            await session.close()

    assert request.assigned_to_user_id == stand_in
    assert request.resolved_via_delegation_id == delegation_id


async def test_delegation_outside_its_date_range_is_ignored(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    An expired delegation routes nothing.

    Date-bounded delegation is the point: access that has to be remembered to
    be removed is access that stays.
    """
    org_a, _ = two_organizations
    approver = await _make_user(session_factory, org_a, "back@example.com")
    stand_in = await _make_user(session_factory, org_a, "wasdeputy@example.com")
    await _grant(session_factory, org_a, approver, Capability.APPROVE_JOB)
    await _grant(session_factory, org_a, stand_in, Capability.APPROVE_JOB)

    today = datetime.now(UTC).date()
    await _delegate(
        session_factory,
        org_a,
        approver,
        stand_in,
        Capability.APPROVE_JOB,
        today - timedelta(days=30),
        today - timedelta(days=10),
    )

    with organization_context(org_a), correlation_scope("expired-delegation"):
        session = await _open_session(session_factory, org_a)
        try:
            assignee, delegation = await resolve_assignee(session, approver, Capability.APPROVE_JOB)
        finally:
            await session.rollback()
            await session.close()

    assert assignee == approver
    assert delegation is None


async def test_delegation_is_per_capability_not_blanket(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Delegating one capability does not delegate another.

    Handing over the ability to approve a job posting while on leave must not
    also hand over above-band CTC approval.
    """
    org_a, _ = two_organizations
    approver = await _make_user(session_factory, org_a, "head2@example.com")
    stand_in = await _make_user(session_factory, org_a, "deputy2@example.com")
    for user in (approver, stand_in):
        await _grant(session_factory, org_a, user, Capability.APPROVE_JOB)
        await _grant(session_factory, org_a, user, Capability.APPROVE_CTC_ABOVE_BAND)

    today = datetime.now(UTC).date()
    await _delegate(
        session_factory,
        org_a,
        approver,
        stand_in,
        Capability.APPROVE_JOB,
        today,
        today + timedelta(days=7),
    )

    with organization_context(org_a), correlation_scope("scoped-delegation"):
        session = await _open_session(session_factory, org_a)
        try:
            job_assignee, _ = await resolve_assignee(session, approver, Capability.APPROVE_JOB)
            ctc_assignee, ctc_delegation = await resolve_assignee(
                session, approver, Capability.APPROVE_CTC_ABOVE_BAND
            )
        finally:
            await session.rollback()
            await session.close()

    assert job_assignee == stand_in, "job approval should follow the delegation"
    assert ctc_assignee == approver, "CTC approval should not"
    assert ctc_delegation is None


async def test_delegation_to_a_user_without_the_capability_is_refused(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Delegation redirects authority; it cannot create it.

    The most important test in this file. If a delegate who lacks the capability
    were silently assigned anyway, an out-of-office setting would become a
    privilege escalation path. Falling back to the delegator silently would be
    just as wrong — the work would sit with someone on leave.

    So it raises, and the message says how to fix it.
    """
    org_a, _ = two_organizations
    approver = await _make_user(session_factory, org_a, "head3@example.com")
    unqualified = await _make_user(session_factory, org_a, "nocap@example.com")
    await _grant(session_factory, org_a, approver, Capability.APPROVE_JOB)
    # Deliberately no grant for `unqualified`.

    today = datetime.now(UTC).date()
    await _delegate(
        session_factory,
        org_a,
        approver,
        unqualified,
        Capability.APPROVE_JOB,
        today,
        today + timedelta(days=7),
    )

    with organization_context(org_a), correlation_scope("bad-delegation"):
        session = await _open_session(session_factory, org_a)
        try:
            with pytest.raises(ApprovalError, match="cannot create it"):
                await resolve_assignee(session, approver, Capability.APPROVE_JOB)
        finally:
            await session.rollback()
            await session.close()


async def test_revoked_delegation_is_ignored(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """A revoked delegation stops routing immediately, without waiting for its end date."""
    org_a, _ = two_organizations
    approver = await _make_user(session_factory, org_a, "head4@example.com")
    stand_in = await _make_user(session_factory, org_a, "deputy4@example.com")
    await _grant(session_factory, org_a, approver, Capability.APPROVE_JOB)
    await _grant(session_factory, org_a, stand_in, Capability.APPROVE_JOB)

    today = datetime.now(UTC).date()
    delegation_id = await _delegate(
        session_factory,
        org_a,
        approver,
        stand_in,
        Capability.APPROVE_JOB,
        today,
        today + timedelta(days=7),
    )
    await _tenant_exec(
        session_factory,
        org_a,
        text("UPDATE approval_delegations SET revoked_at = now() WHERE id = :id"),
        {"id": delegation_id},
    )

    with organization_context(org_a), correlation_scope("revoked-delegation"):
        session = await _open_session(session_factory, org_a)
        try:
            assignee, delegation = await resolve_assignee(session, approver, Capability.APPROVE_JOB)
        finally:
            await session.rollback()
            await session.close()

    assert assignee == approver
    assert delegation is None


# ===========================================================================
# Deadlines
# ===========================================================================


async def test_request_without_an_sla_policy_has_no_deadline(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    An unconfigured SLA type produces a request with no due date.

    An approval with no deadline is still a valid approval; it simply never
    escalates. Refusing to create it would make SLA configuration a hard
    prerequisite for using the platform at all.
    """
    org_a, _ = two_organizations
    approver = await _make_user(session_factory, org_a, "nosla@example.com")
    await _grant(session_factory, org_a, approver, Capability.APPROVE_JOB)

    with organization_context(org_a), correlation_scope("no-sla"):
        session = await _open_session(session_factory, org_a)
        try:
            request = await request_approval(
                session,
                approval_type=ApprovalType.JOB_PUBLISH,
                entity_type="JobPosting",
                entity_id=uuid7(),
                required_capability=Capability.APPROVE_JOB,
                intended_approver_id=approver,
                sla_type=SLAType.JOB_APPROVAL,
            )
            await session.commit()
        finally:
            await session.close()

    assert request.due_at is None
    assert request.sla_policy_id is None


async def test_configured_sla_produces_a_future_deadline(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """A configured policy gives the request a deadline in the future."""
    org_a, _ = two_organizations
    approver = await _make_user(session_factory, org_a, "withsla@example.com")
    await _grant(session_factory, org_a, approver, Capability.APPROVE_JOB)
    await _sla(session_factory, org_a, SLAType.JOB_APPROVAL, days=2)

    with organization_context(org_a), correlation_scope("with-sla"):
        session = await _open_session(session_factory, org_a)
        try:
            request = await request_approval(
                session,
                approval_type=ApprovalType.JOB_PUBLISH,
                entity_type="JobPosting",
                entity_id=uuid7(),
                required_capability=Capability.APPROVE_JOB,
                intended_approver_id=approver,
                sla_type=SLAType.JOB_APPROVAL,
            )
            await session.commit()
        finally:
            await session.close()

    assert request.due_at is not None
    assert request.due_at > datetime.now(UTC)
    assert request.sla_policy_id is not None


# ===========================================================================
# Resolving a request
# ===========================================================================


async def test_approving_records_status_action_and_event(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """Approval sets the status, appends an action, and emits an event."""
    org_a, _ = two_organizations
    approver = await _make_user(session_factory, org_a, "approver@example.com")
    await _grant(session_factory, org_a, approver, Capability.APPROVE_JOB)

    with organization_context(org_a), correlation_scope("approve-test"):
        session = await _open_session(session_factory, org_a)
        try:
            request = await request_approval(
                session,
                approval_type=ApprovalType.JOB_PUBLISH,
                entity_type="JobPosting",
                entity_id=uuid7(),
                required_capability=Capability.APPROVE_JOB,
                intended_approver_id=approver,
            )
            await approve(session, request, approver, comment="looks fine")
            await session.commit()
        finally:
            await session.close()

    assert request.status == ApprovalStatus.APPROVED.value
    assert request.resolved_at is not None

    result = await _tenant_exec(
        session_factory,
        org_a,
        select(ApprovalAction).where(ApprovalAction.approval_request_id == request.id),
    )
    actions = list(result.scalars().all())
    assert len(actions) == 1
    assert actions[0].action == ApprovalActionType.APPROVED.value
    assert actions[0].comment == "looks fine"

    result = await _tenant_exec(
        session_factory,
        org_a,
        select(OutboxEvent.event_type).where(OutboxEvent.entity_id == request.id),
    )
    emitted = {row[0] for row in result}
    assert "ApprovalRequested" in emitted
    assert "ApprovalGranted" in emitted


async def test_a_user_without_the_capability_cannot_approve(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Being assigned a request is not the same as being allowed to resolve it.

    Capability is re-checked at the moment of approval, not only at assignment.
    A role removed between the two must take effect immediately.
    """
    org_a, _ = two_organizations
    approver = await _make_user(session_factory, org_a, "real@example.com")
    outsider = await _make_user(session_factory, org_a, "outsider@example.com")
    await _grant(session_factory, org_a, approver, Capability.APPROVE_JOB)

    with organization_context(org_a), correlation_scope("wrong-approver"):
        session = await _open_session(session_factory, org_a)
        try:
            request = await request_approval(
                session,
                approval_type=ApprovalType.JOB_PUBLISH,
                entity_type="JobPosting",
                entity_id=uuid7(),
                required_capability=Capability.APPROVE_JOB,
                intended_approver_id=approver,
            )
            with pytest.raises(ApprovalError):
                await approve(session, request, outsider)
        finally:
            await session.rollback()
            await session.close()


async def test_a_resolved_request_cannot_be_resolved_again(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    Double-approval is refused.

    Without this, a retried request or a double-clicked button would append a
    second action and re-emit the event, and every downstream consumer would
    act on the approval twice.
    """
    org_a, _ = two_organizations
    approver = await _make_user(session_factory, org_a, "once@example.com")
    await _grant(session_factory, org_a, approver, Capability.APPROVE_JOB)

    with organization_context(org_a), correlation_scope("double-approve"):
        session = await _open_session(session_factory, org_a)
        try:
            request = await request_approval(
                session,
                approval_type=ApprovalType.JOB_PUBLISH,
                entity_type="JobPosting",
                entity_id=uuid7(),
                required_capability=Capability.APPROVE_JOB,
                intended_approver_id=approver,
            )
            await approve(session, request, approver)
            with pytest.raises(ApprovalError):
                await approve(session, request, approver)
        finally:
            await session.rollback()
            await session.close()


async def test_rejecting_records_the_reason(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """Rejection sets the status and keeps the comment for the trail."""
    org_a, _ = two_organizations
    approver = await _make_user(session_factory, org_a, "rejecter@example.com")
    await _grant(session_factory, org_a, approver, Capability.APPROVE_JOB)

    with organization_context(org_a), correlation_scope("reject-test"):
        session = await _open_session(session_factory, org_a)
        try:
            request = await request_approval(
                session,
                approval_type=ApprovalType.JOB_PUBLISH,
                entity_type="JobPosting",
                entity_id=uuid7(),
                required_capability=Capability.APPROVE_JOB,
                intended_approver_id=approver,
            )
            await reject(session, request, approver, comment="salary band unclear")
            await session.commit()
        finally:
            await session.close()

    assert request.status == ApprovalStatus.REJECTED.value

    result = await _tenant_exec(
        session_factory,
        org_a,
        select(ApprovalAction.comment).where(ApprovalAction.approval_request_id == request.id),
    )
    assert "salary band unclear" in [row[0] for row in result]


async def test_withdrawing_closes_the_request(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    A request can be withdrawn by the requester.

    Used when the underlying record changes enough that the pending approval no
    longer describes what is being approved — an offer revised while awaiting
    sign-off, for instance.
    """
    org_a, _ = two_organizations
    approver = await _make_user(session_factory, org_a, "withdrawn@example.com")
    await _grant(session_factory, org_a, approver, Capability.APPROVE_JOB)

    with organization_context(org_a), correlation_scope("withdraw-test"):
        session = await _open_session(session_factory, org_a)
        try:
            request = await request_approval(
                session,
                approval_type=ApprovalType.JOB_PUBLISH,
                entity_type="JobPosting",
                entity_id=uuid7(),
                required_capability=Capability.APPROVE_JOB,
                intended_approver_id=approver,
            )
            await withdraw(session, request, approver)
            await session.commit()
        finally:
            await session.close()

    assert request.status == ApprovalStatus.WITHDRAWN.value


# ===========================================================================
# Escalation
# ===========================================================================


async def test_sweeper_escalates_an_overdue_request(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    A request past its deadline escalates and emits ApprovalEscalated.

    V3.2 promised escalation across three modules and provided only
    FeedbackSLABreached — the escalation service had nothing to emit and nothing
    to subscribe to. This is that gap closed.
    """
    from platform_core.approvals.escalation import sweep_organization

    org_a, _ = two_organizations
    approver = await _make_user(session_factory, org_a, "overdue@example.com")
    await _grant(session_factory, org_a, approver, Capability.APPROVE_JOB)
    # misses=0 so the first sweep escalates rather than reminding.
    await _sla(session_factory, org_a, SLAType.JOB_APPROVAL, days=1, misses=0)

    with organization_context(org_a), correlation_scope("escalation-test"):
        session = await _open_session(session_factory, org_a)
        try:
            request = await request_approval(
                session,
                approval_type=ApprovalType.JOB_PUBLISH,
                entity_type="JobPosting",
                entity_id=uuid7(),
                required_capability=Capability.APPROVE_JOB,
                intended_approver_id=approver,
                sla_type=SLAType.JOB_APPROVAL,
            )
            await session.commit()
        finally:
            await session.close()

        # Rewind the deadline using the DATABASE clock. Computing it in Python
        # would compare against a different clock than the sweeper's query uses
        # — the same skew that made the outbox relay flaky.
        await _tenant_exec(
            session_factory,
            org_a,
            text("UPDATE approval_requests SET due_at = now() - interval '1 hour' WHERE id = :id"),
            {"id": request.id},
        )

        result = await sweep_organization()

    assert result.escalations == 1

    refreshed = await _tenant_exec(
        session_factory,
        org_a,
        select(ApprovalRequest).where(ApprovalRequest.id == request.id),
    )
    row = refreshed.scalar_one()
    assert row.status == ApprovalStatus.ESCALATED.value
    assert row.escalated_at is not None

    events = await _tenant_exec(
        session_factory,
        org_a,
        select(OutboxEvent.event_type).where(OutboxEvent.entity_id == request.id),
    )
    assert "ApprovalEscalated" in {r[0] for r in events}


async def test_sweeper_leaves_requests_inside_their_deadline_alone(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """A request still within its window is untouched."""
    from platform_core.approvals.escalation import sweep_organization

    org_a, _ = two_organizations
    approver = await _make_user(session_factory, org_a, "intime@example.com")
    await _grant(session_factory, org_a, approver, Capability.APPROVE_JOB)
    await _sla(session_factory, org_a, SLAType.JOB_APPROVAL, days=5, misses=0)

    with organization_context(org_a), correlation_scope("not-overdue"):
        session = await _open_session(session_factory, org_a)
        try:
            await request_approval(
                session,
                approval_type=ApprovalType.JOB_PUBLISH,
                entity_type="JobPosting",
                entity_id=uuid7(),
                required_capability=Capability.APPROVE_JOB,
                intended_approver_id=approver,
                sla_type=SLAType.JOB_APPROVAL,
            )
            await session.commit()
        finally:
            await session.close()

        result = await sweep_organization()

    assert result.escalations == 0
    assert result.reminders_sent == 0


async def test_sweeper_reminds_before_escalating(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """
    With misses configured above zero, the first sweep reminds rather than escalates.

    Escalating on the first overdue sweep would surface every approval that ran
    a few minutes late to a senior person, and an escalation channel that cries
    wolf is one nobody reads.
    """
    from platform_core.approvals.escalation import sweep_organization

    org_a, _ = two_organizations
    approver = await _make_user(session_factory, org_a, "remindme@example.com")
    await _grant(session_factory, org_a, approver, Capability.APPROVE_JOB)
    await _sla(session_factory, org_a, SLAType.JOB_APPROVAL, days=1, misses=1)

    with organization_context(org_a), correlation_scope("reminder-test"):
        session = await _open_session(session_factory, org_a)
        try:
            request = await request_approval(
                session,
                approval_type=ApprovalType.JOB_PUBLISH,
                entity_type="JobPosting",
                entity_id=uuid7(),
                required_capability=Capability.APPROVE_JOB,
                intended_approver_id=approver,
                sla_type=SLAType.JOB_APPROVAL,
            )
            await session.commit()
        finally:
            await session.close()

        await _tenant_exec(
            session_factory,
            org_a,
            text("UPDATE approval_requests SET due_at = now() - interval '1 hour' WHERE id = :id"),
            {"id": request.id},
        )

        first = await sweep_organization()
        second = await sweep_organization()

    assert first.reminders_sent == 1
    assert first.escalations == 0
    assert second.escalations == 1, "second sweep should escalate after the reminder"


# ===========================================================================
# Tenant isolation
# ===========================================================================


async def test_approval_requests_are_tenant_isolated(
    session_factory: async_sessionmaker[AsyncSession],
    two_organizations: tuple[UUID, UUID],
) -> None:
    """One organisation cannot see another's approvals queue."""
    org_a, org_b = two_organizations

    for org_id, email in ((org_a, "a@example.com"), (org_b, "b@example.com")):
        approver = await _make_user(session_factory, org_id, email)
        await _grant(session_factory, org_id, approver, Capability.APPROVE_JOB)
        with organization_context(org_id), correlation_scope("iso-approvals"):
            session = await _open_session(session_factory, org_id)
            try:
                await request_approval(
                    session,
                    approval_type=ApprovalType.JOB_PUBLISH,
                    entity_type="JobPosting",
                    entity_id=uuid7(),
                    required_capability=Capability.APPROVE_JOB,
                    intended_approver_id=approver,
                )
                await session.commit()
            finally:
                await session.close()

    result = await _tenant_exec(
        session_factory, org_a, text("SELECT count(*) FROM approval_requests")
    )
    assert int(result.scalar_one()) == 1
