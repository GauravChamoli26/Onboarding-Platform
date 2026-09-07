"""
The approval engine — requesting, routing and resolving approvals.

WHAT THIS REPLACES
    Three nullable `approver_id` columns on three unrelated tables. Everything
    here — delegation, deadlines, escalation, a single queue — was unbuildable
    against that shape (Decision Log G1).

THE ROUTING RULE
    A request names an intended approver and a required capability. Before
    assignment, active delegations are consulted: if the intended approver has
    delegated that capability for today, the request goes to the delegate and
    records which delegation sent it there.

    Delegation is checked at ASSIGNMENT time, not at approval time. A request
    raised while someone was on leave stays with the cover even after they
    return — reassigning mid-flight would move work someone has already started
    reviewing, and would make the trail harder to follow rather than easier.

EVERY TRANSITION EMITS AN EVENT
    ApprovalRequested, ApprovalGranted, ApprovalRejected, ApprovalDelegated,
    ApprovalEscalated, ApprovalReminderSent, ApprovalExpired. These are the
    events the earlier catalogue promised escalation for but never provided.
"""

import logging
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.approvals.business_days import (
    DEFAULT_TIMEZONE,
    DEFAULT_WEEKEND_DAYS,
    add_business_days,
)
from platform_core.auth.authorization import resolve_capabilities
from platform_core.auth.capabilities import Capability
from platform_core.db.types import uuid7
from platform_core.events.catalog import EventType
from platform_core.events.emitter import emit_event
from platform_core.models.approval import (
    ApprovalAction,
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalType,
)
from platform_core.models.delegation import ApprovalDelegation
from platform_core.models.organization import Organization
from platform_core.models.sla_policy import Holiday, SLAPolicy, SLAType
from platform_core.tenancy.context import get_organization

logger = logging.getLogger(__name__)


class ApprovalError(RuntimeError):
    """Raised when an approval operation is not permitted."""


# ---------------------------------------------------------------------------
# Deadline calculation
# ---------------------------------------------------------------------------


async def _organization_calendar(
    session: AsyncSession, organization_id: UUID
) -> tuple[str, frozenset[int], frozenset[date]]:
    """
    Load the timezone, weekend days and holidays for an organisation.

    Returns:
        tuple: (timezone name, weekend ISO weekday numbers, holiday dates).

    An organisation with no holidays loaded gets an empty set, which means every
    weekday counts as working. That is a data gap rather than an error — but it
    will escalate approvals through the festival season, so seeding the calendar
    is part of customer onboarding.
    """
    organization = await session.get(Organization, organization_id)
    timezone = organization.timezone if organization else DEFAULT_TIMEZONE

    result = await session.execute(select(Holiday.holiday_date))
    # Annotated rather than inferred: the rows come back as Any, and an
    # unannotated frozenset would silently accept whatever the query returned.
    holidays: frozenset[date] = frozenset(row[0] for row in result)

    # Weekend days are not yet configurable per organisation; six-day weeks are
    # supported by business_days.add_business_days and will be wired to
    # organisation config when a customer needs it.
    return timezone, DEFAULT_WEEKEND_DAYS, holidays


async def compute_due_at(
    session: AsyncSession, sla_type: SLAType, start: datetime | None = None
) -> tuple[datetime | None, SLAPolicy | None]:
    """
    Compute a deadline from the organisation's SLA policy and calendar.

    Args:
        session: tenant-scoped session.
        sla_type: which policy to apply.
        start: when the clock starts. Defaults to now.

    Returns:
        tuple: (deadline, the policy used). Both None if no policy is
        configured for this type — an approval with no deadline is still a valid
        approval, it simply never escalates.
    """
    result = await session.execute(
        select(SLAPolicy).where(SLAPolicy.sla_type == sla_type.value).limit(1)
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        logger.info(
            "No SLA policy configured; approval will not escalate",
            extra={"sla_type": sla_type.value},
        )
        return None, None

    organization_id = get_organization()
    timezone, weekend_days, holidays = await _organization_calendar(session, organization_id)

    due_at = add_business_days(
        start or datetime.now(UTC),
        policy.duration_business_days,
        timezone=timezone,
        weekend_days=weekend_days,
        holidays=holidays,
    )
    return due_at, policy


# ---------------------------------------------------------------------------
# Delegation resolution
# ---------------------------------------------------------------------------


async def resolve_assignee(
    session: AsyncSession,
    intended_approver_id: UUID,
    capability: Capability,
    on_date: date | None = None,
) -> tuple[UUID, ApprovalDelegation | None]:
    """
    Decide who actually receives a request, following any active delegation.

    Args:
        session: tenant-scoped session.
        intended_approver_id: who would normally approve this.
        capability: the capability required.
        on_date: the date to evaluate delegations against. Defaults to today.

    Returns:
        tuple: (assignee user ID, the delegation used or None).

    Raises:
        ApprovalError: if a delegation exists but the delegate no longer holds
            the capability. Failing loudly is correct — silently falling back to
            the delegator would route work to someone who is on leave, and
            silently assigning anyway would grant authority the delegate does
            not have.

    Only one level of delegation is followed. A delegate who has themselves
    delegated does not chain: the request stays with them. Chained delegation
    makes accountability genuinely hard to reason about, and nothing in the spec
    asks for it.
    """
    today = on_date or datetime.now(UTC).date()

    result = await session.execute(
        select(ApprovalDelegation)
        .where(ApprovalDelegation.delegator_user_id == intended_approver_id)
        .where(ApprovalDelegation.capability == capability.value)
        .where(ApprovalDelegation.revoked_at.is_(None))
        .where(ApprovalDelegation.valid_from <= today)
        .where(ApprovalDelegation.valid_to >= today)
        .limit(1)
    )
    delegation = result.scalar_one_or_none()

    if delegation is None:
        return intended_approver_id, None

    # Re-check at assignment time, not only at creation. A delegate may have
    # been offboarded or had the role removed since the delegation was made.
    delegate_capabilities = await resolve_capabilities(session, delegation.delegate_user_id)
    if capability not in delegate_capabilities:
        raise ApprovalError(
            f"Delegation {delegation.id} routes {capability.value} to a user "
            f"who does not hold that capability. Delegation redirects "
            f"authority; it cannot create it. Revoke the delegation or grant "
            f"the delegate the capability."
        )

    return delegation.delegate_user_id, delegation


# ---------------------------------------------------------------------------
# Public operations
# ---------------------------------------------------------------------------


async def request_approval(
    session: AsyncSession,
    *,
    approval_type: ApprovalType,
    entity_type: str,
    entity_id: UUID,
    required_capability: Capability,
    intended_approver_id: UUID,
    sla_type: SLAType | None = None,
    application_id: UUID | None = None,
    context_snapshot: dict[str, Any] | None = None,
    requested_by: UUID | None = None,
) -> ApprovalRequest:
    """
    Raise an approval request, routed through any active delegation.

    Uses the caller's session and transaction, so the request and whatever
    triggered it commit together.

    Args:
        session: the caller's session, inside a transaction.
        approval_type: what is being approved.
        entity_type: the entity's type — "JobPosting", "Offer", "NegotiationLog".
        entity_id: that entity's ID.
        required_capability: what the approver must hold.
        intended_approver_id: who would normally approve.
        sla_type: which deadline policy applies. None means no deadline.
        application_id: denormalised for the approvals queue.
        context_snapshot: what the approver is being shown. Identifiers and
            figures only — never PII.
        requested_by: who raised it. Defaults to the current principal.

    Returns:
        ApprovalRequest: the created request.

    Raises:
        ApprovalError: if delegation routing fails.
    """
    organization_id = get_organization()

    assignee_id, delegation = await resolve_assignee(
        session, intended_approver_id, required_capability
    )

    due_at, policy = (None, None)
    if sla_type is not None:
        due_at, policy = await compute_due_at(session, sla_type)

    request = ApprovalRequest(
        id=uuid7(),
        organization_id=organization_id,
        approval_type=approval_type.value,
        entity_type=entity_type,
        entity_id=entity_id,
        application_id=application_id,
        required_capability=required_capability.value,
        assigned_to_user_id=assignee_id,
        resolved_via_delegation_id=delegation.id if delegation else None,
        status=ApprovalStatus.PENDING.value,
        sla_policy_id=policy.id if policy else None,
        due_at=due_at,
        context_snapshot=context_snapshot or {},
        requested_by=requested_by,
    )
    session.add(request)
    # Flush before anything can reference this row. ApprovalAction stores
    # approval_request_id as a plain column rather than a relationship, so
    # SQLAlchemy's unit of work does not know the insert order matters and may
    # write the action first — a foreign key violation for any caller that
    # requests and resolves an approval in one transaction.
    await session.flush()

    await emit_event(
        session,
        event_type=EventType.APPROVAL_REQUESTED,
        entity_type="ApprovalRequest",
        entity_id=request.id,
        application_id=application_id,
        payload={
            "approval_type": approval_type.value,
            "target_entity_type": entity_type,
            "target_entity_id": str(entity_id),
            "assigned_to": str(assignee_id),
            "via_delegation": delegation is not None,
            "due_at": due_at.isoformat() if due_at else None,
        },
    )

    if delegation is not None:
        await emit_event(
            session,
            event_type=EventType.APPROVAL_DELEGATED,
            entity_type="ApprovalRequest",
            entity_id=request.id,
            payload={
                "delegation_id": str(delegation.id),
                "delegator": str(intended_approver_id),
                "delegate": str(assignee_id),
                "capability": required_capability.value,
            },
        )

    return request


async def _record_action(
    session: AsyncSession,
    request: ApprovalRequest,
    action: ApprovalActionType,
    actor_id: UUID | None,
    comment: str | None = None,
) -> None:
    """Append an action to a request's history."""
    session.add(
        ApprovalAction(
            id=uuid7(),
            organization_id=request.organization_id,
            approval_request_id=request.id,
            action=action.value,
            actor_id=actor_id,
            comment=comment,
        )
    )


async def approve(
    session: AsyncSession,
    request: ApprovalRequest,
    actor_id: UUID,
    comment: str | None = None,
) -> ApprovalRequest:
    """
    Approve a request.

    Args:
        session: tenant-scoped session inside a transaction.
        request: the request to approve.
        actor_id: who is approving. Must be the assignee.
        comment: optional note.

    Returns:
        ApprovalRequest: the updated request.

    Raises:
        ApprovalError: if the request is already resolved, or the actor is not
            the assignee.

    An ESCALATED request can still be approved — escalation changes who is being
    asked, not whether an answer is needed.
    """
    if request.status not in (
        ApprovalStatus.PENDING.value,
        ApprovalStatus.ESCALATED.value,
    ):
        raise ApprovalError(
            f"Cannot approve a request in status {request.status}. Only Pending "
            f"and Escalated requests await a decision."
        )

    # The assignee, or whoever it escalated to. Checking here rather than
    # relying on the capability alone: holding the capability makes someone
    # eligible to be assigned, not entitled to answer another person's request.
    permitted = {request.assigned_to_user_id}
    if request.escalated_to_user_id is not None:
        permitted.add(request.escalated_to_user_id)
    if actor_id not in permitted:
        raise ApprovalError(
            "Only the assigned approver, or the person it escalated to, may resolve this request."
        )

    request.status = ApprovalStatus.APPROVED.value
    request.resolved_at = datetime.now(UTC)
    session.add(request)

    await _record_action(session, request, ApprovalActionType.APPROVED, actor_id, comment)
    await emit_event(
        session,
        event_type=EventType.APPROVAL_GRANTED,
        entity_type="ApprovalRequest",
        entity_id=request.id,
        application_id=request.application_id,
        payload={
            "approval_type": request.approval_type,
            "target_entity_type": request.entity_type,
            "target_entity_id": str(request.entity_id),
            "was_escalated": request.escalated_at is not None,
        },
    )
    return request


async def reject(
    session: AsyncSession,
    request: ApprovalRequest,
    actor_id: UUID,
    comment: str | None = None,
) -> ApprovalRequest:
    """
    Reject a request.

    Args:
        session: tenant-scoped session inside a transaction.
        request: the request to reject.
        actor_id: who is rejecting. Must be the assignee.
        comment: reason. Not enforced here, but a rejection without one is
            unhelpful to whoever raised it.

    Returns:
        ApprovalRequest: the updated request.

    Raises:
        ApprovalError: if already resolved, or the actor is not the assignee.
    """
    if request.status not in (
        ApprovalStatus.PENDING.value,
        ApprovalStatus.ESCALATED.value,
    ):
        raise ApprovalError(f"Cannot reject a request in status {request.status}.")

    permitted = {request.assigned_to_user_id}
    if request.escalated_to_user_id is not None:
        permitted.add(request.escalated_to_user_id)
    if actor_id not in permitted:
        raise ApprovalError(
            "Only the assigned approver, or the person it escalated to, may resolve this request."
        )

    request.status = ApprovalStatus.REJECTED.value
    request.resolved_at = datetime.now(UTC)
    session.add(request)

    await _record_action(session, request, ApprovalActionType.REJECTED, actor_id, comment)
    await emit_event(
        session,
        event_type=EventType.APPROVAL_REJECTED,
        entity_type="ApprovalRequest",
        entity_id=request.id,
        application_id=request.application_id,
        payload={
            "approval_type": request.approval_type,
            "target_entity_type": request.entity_type,
            "target_entity_id": str(request.entity_id),
        },
    )
    return request


async def withdraw(
    session: AsyncSession, request: ApprovalRequest, actor_id: UUID | None = None
) -> ApprovalRequest:
    """
    Withdraw a request whose subject no longer needs approving.

    Used when the underlying thing is cancelled — a job posting closed, an offer
    superseded by a reissue. Distinct from rejection: nobody decided against it,
    the question simply stopped mattering.
    """
    if request.status not in (
        ApprovalStatus.PENDING.value,
        ApprovalStatus.ESCALATED.value,
    ):
        raise ApprovalError(f"Cannot withdraw a request in status {request.status}.")

    request.status = ApprovalStatus.WITHDRAWN.value
    request.resolved_at = datetime.now(UTC)
    session.add(request)

    await _record_action(
        session,
        request,
        ApprovalActionType.COMMENT_ADDED,
        actor_id,
        "Withdrawn: the subject no longer requires approval.",
    )
    return request
